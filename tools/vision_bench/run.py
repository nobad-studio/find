"""Runs the benchmark: one supervised child process per (candidate, device), so each one's memory is its own and a
crash or hang ends only that run (dev only, never shipped).

Parent: bench() -> supervise() each child, sampling private memory (and GPU memory when Windows counts it) over the
child and everything it started (the llama.cpp process). Child: run_one() loads the adapter once and answers every
item; a photo that can't be decoded is recorded and skipped.
"""
import ctypes
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from ctypes import wintypes

from .adapters import ADAPTERS, DecodeError, GpuNotUsed, NotSupported
from .score import aggregate, score_item

APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODELS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models.json")
LOAD_TIMEOUT = 600
ITEM_TIMEOUT = 120
SAMPLE_EVERY = 0.5


def models_json():
    with open(MODELS_JSON, encoding="utf-8") as f:
        return json.load(f)


# ---------- the child ----------

def run_one(candidate, device, items, models_dir, tools_dir, adapters=ADAPTERS):
    """Every item through one candidate on one device -> the result dict (see the plan's Task 5)."""
    """Scoring: a photo that can't be decoded and a task the candidate can't do are left out; a model error or a
    per-photo timeout counts as a wrong answer (0), so a model can't score better by failing on hard photos."""
    a = adapters[candidate](tools_dir=tools_dir)
    base = {"candidate": candidate, "device": device}
    rows, scores, ms = [], [], []
    try:
        t0 = time.perf_counter()
        a.load(models_dir, device)
        load_s = time.perf_counter() - t0
        for it in items:
            row = {"id": it["id"], "task": it["task"], "status": "ok", "answer": "", "score": None, "ms": None}
            t = time.perf_counter()
            a.last_ms = None
            try:
                row["answer"] = a.run(it["task"], it["image"], it.get("image2"), it.get("question"))
            except GpuNotUsed:
                raise
            except DecodeError:
                row["status"] = "error: decode"
            except NotSupported:
                row["status"] = "not supported"
            except subprocess.TimeoutExpired:
                row["status"], row["score"] = "timeout", 0.0
            except Exception as e:
                row["status"], row["score"] = f"error: {type(e).__name__}: {str(e)[:200]}", 0.0
            if row["status"] == "ok":
                row["ms"] = a.last_ms if a.last_ms is not None else (time.perf_counter() - t) * 1000
                try:
                    row["score"] = score_item(it, row["answer"])
                except Exception:
                    row["status"], row["score"] = "error: score", None
                else:
                    ms.append(row["ms"])
            if row["score"] is not None:
                scores.append((it["kind"], row["score"]))
            rows.append(row)
    except GpuNotUsed as e:
        return {**base, "status": "not available", "why": str(e)}
    finally:
        a.close()
    return {**base, "status": "ok", "load_s": round(load_s, 2),
            "ms_per_item": round(statistics.median(ms), 1) if ms else None, "scores": aggregate(scores),
            "errors": sum(1 for r in rows if r["status"].startswith("error")),
            "timeouts": sum(1 for r in rows if r["status"] == "timeout"), "items": rows}


# ---------- the parent ----------

def tree_pids(root, rows):
    """root and every process below it, from procs.snapshot() rows (pid, parent, exe)."""
    out, todo = [root], [root]
    while todo:
        p = todo.pop()
        for pid, parent, _ in rows:
            if parent == p and pid not in out and pid != parent:
                out.append(pid)
                todo.append(pid)
    return out


def _private_mb(pid):
    k, ps = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi")
    k.OpenProcess.restype = wintypes.HANDLE
    ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ("Peak", "WS", "a", "b", "c", "d", "Pagefile", "PeakPagefile")]
    h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return 0.0
    try:
        m = PMC()
        m.cb = ctypes.sizeof(m)
        return m.Pagefile / 1048576 if ps.GetProcessMemoryInfo(h, ctypes.byref(m), m.cb) else 0.0
    finally:
        k.CloseHandle(h)


class GpuMemory:
    """GPU memory (dedicated + shared, MB) of some PIDs from "GPU Process Memory" counters; None when Windows has
    no such counters. An integrated GPU (Intel Iris Xe) uses shared memory, so both are counted."""
    PATHS = ("\\GPU Process Memory(*)\\Dedicated Usage", "\\GPU Process Memory(*)\\Shared Usage")

    def __init__(self):
        self.ok = False
        try:
            from nobadfind import winapi
            self._w = winapi
            self.pdh = pdh = ctypes.WinDLL("pdh")
            pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
            pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_void_p)]
            pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
            pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                         ctypes.POINTER(wintypes.DWORD),
                                                         ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
            self.q = ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(self.q)) != 0:
                return
            self.counters = []
            for p in self.PATHS:
                c = ctypes.c_void_p()
                if pdh.PdhAddEnglishCounterW(self.q, p, None, ctypes.byref(c)) == 0:
                    self.counters.append(c)
            self.ok = bool(self.counters)
        except Exception:
            self.ok = False

    def mb(self, pids):
        if not self.ok:
            return None
        w, pdh = self._w, self.pdh
        try:
            if pdh.PdhCollectQueryData(self.q) != 0:
                return None
            keys, total = {f"pid_{p}_" for p in pids}, 0.0
            for c in self.counters:
                size, count = wintypes.DWORD(0), wintypes.DWORD(0)
                r = pdh.PdhGetFormattedCounterArrayW(c, w._PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
                                                     None)
                if (r & 0xFFFFFFFF) != w._PDH_MORE_DATA or not size.value:
                    continue
                buf = ctypes.create_string_buffer(size.value)
                if pdh.PdhGetFormattedCounterArrayW(c, w._PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
                                                    buf) != 0:
                    continue
                items = ctypes.cast(buf, ctypes.POINTER(w._PDH_ITEM))
                for i in range(count.value):
                    name = ctypes.wstring_at(items[i].szName) if items[i].szName else ""
                    if any(k in name + "_" for k in keys) and items[i].FmtValue.CStatus in (0, 1):
                        total += items[i].FmtValue.doubleValue
            return total / 1048576
        except Exception:
            return None


def _kill_tree(pid):
    subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def supervise(cmd, timeout_s, sample=None, env=None, err_tail=None):
    """Run cmd; every SAMPLE_EVERY s call sample(pids of its tree). (exit code, stdout), or (None, stdout so far)
    after killing the whole tree at the timeout. The tree is also killed if this process is interrupted. The last
    1,000 characters of stderr go into err_tail (a list), for the reason of a crash."""
    from nobadfind import procs
    stem = os.path.join(os.environ.get("TEMP", "."), f"vbench-{os.getpid()}-{time.monotonic_ns()}")
    code, p = None, None
    try:
        with open(stem + ".out", "wb") as out, open(stem + ".err", "wb") as err:
            p = subprocess.Popen(cmd, stdout=out, stderr=err, stdin=subprocess.DEVNULL, cwd=APP, env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            end = time.monotonic() + timeout_s
            while True:
                code = p.poll()
                if code is not None:
                    break
                if time.monotonic() >= end:
                    code = None
                    break
                if sample:
                    sample(tree_pids(p.pid, procs.snapshot()))
                time.sleep(SAMPLE_EVERY)
            if code is None:
                _kill_tree(p.pid)
                try:
                    p.wait(10)
                except Exception:
                    pass
        with open(stem + ".out", encoding="utf-8", errors="replace") as f:
            text = f.read()
        if err_tail is not None:
            with open(stem + ".err", encoding="utf-8", errors="replace") as f:
                err_tail.append(f.read()[-1000:])
        return code, text
    finally:
        if p is not None and p.poll() is None:        # interrupted (Ctrl+C): never leave the child running
            _kill_tree(p.pid)
        for ext in (".out", ".err"):
            try:
                os.remove(stem + ext)
            except OSError:
                pass


def last_json(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


def bench(items, pairs, devs, child_cmd, timeout_s=None):
    """[(candidate, device, backend)] -> one result each, in order. child_cmd(candidate, device) -> argv."""
    avail = {(d["device"], d["backend"]): d for d in devs}
    gpu = GpuMemory()
    results = []
    for cand, device, backend in pairs:
        base = {"candidate": cand, "device": device, "backend": backend}
        d = avail.get((device, backend))
        if not d or not d["available"]:
            results.append({**base, "status": "not available", "why": d["why"] if d else "unknown device"})
            continue
        peak = {"ram": 0.0, "gpu": None}

        def sample(pids):
            peak["ram"] = max(peak["ram"], sum(_private_mb(p) for p in pids))
            g = gpu.mb(pids)
            if g is not None:
                peak["gpu"] = max(peak["gpu"] or 0.0, g)
        limit = timeout_s if timeout_s is not None else LOAD_TIMEOUT + ITEM_TIMEOUT * max(1, len(items))
        tmp = tempfile.mkdtemp(prefix="vbench-run-")
        tail = []
        try:
            code, out = supervise(child_cmd(cand, device), limit, sample,
                                  env={**os.environ, "VBENCH_TMP": tmp}, err_tail=tail)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)      # resized photo copies, even if the child was killed
        res = last_json(out) if code == 0 else None
        if code is None:
            r = {**base, "status": "timeout", "why": f"no result within {limit:.0f} s"}
        elif code != 0 or res is None:
            last = [ln.strip() for ln in (tail[0] if tail else "").splitlines() if ln.strip()]
            r = {**base, "status": "crash", "exit_code": code,
                 "why": f"exit code {code}" + (f": {last[-1][:300]}" if last else "")}
        else:
            r = {**res, **base}
        r["peak_private_mb"] = round(peak["ram"], 1)
        r["peak_gpu_mb"] = None if peak["gpu"] is None else round(peak["gpu"], 1)
        results.append(r)
    return results


# ---------- downloads (only with --download) ----------

def _unzip(zip_path, dest):
    """Extract, refusing any member that would land outside dest (zip-slip)."""
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = os.path.realpath(os.path.join(root, m.filename))
            if os.path.commonpath([target, root]) != root:
                raise ValueError(f"{zip_path}: member {m.filename!r} leaves the folder")
        z.extractall(root)


def wanted_files(model, devices):
    """A candidate's files for these devices: Florence-2's int8 graphs only for the CPU, fp16 only for a GPU."""
    gpu = any(d != "cpu" for d in devices)
    return {n: v for n, v in model["files"].items()
            if not (n.endswith("_int8.onnx") and "cpu" not in devices) and not (n.endswith("_fp16.onnx") and not gpu)}


def download(candidates, devices, models_dir, tools_dir, progress=print):
    """Fetch only the pinned files the chosen candidates and devices need, each size + SHA-256 checked."""
    from nobadfind.embed import _fetch_verified
    data = models_json()
    llama_devices = [d for d in devices if d in ("cpu", "vulkan", "cuda")] if any(
        data["models"][c]["backend"] == "llama" for c in candidates) else []
    for cid in candidates:
        m = data["models"][cid]
        for name, (size, sha) in wanted_files(m, devices).items():
            dest = os.path.join(models_dir, cid, *name.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            progress(f"{cid}: {name} ({size // 1_000_000} MB)")
            _fetch_verified(f"https://huggingface.co/{m['repo']}/resolve/{m['rev']}/{name}", dest, size, sha, name)
    for dev in llama_devices:
        for key in ([dev, "cuda-runtime"] if dev == "cuda" else [dev]):
            b = data["llama"][key]
            z = os.path.join(tools_dir, b["zip"])
            progress(f"llama.cpp {b['tag']} {key} ({b['size'] // 1_000_000} MB)")
            _fetch_verified(b["url"], z, b["size"], b["sha256"], b["zip"])
            _unzip(z, os.path.join(tools_dir, f"llama-{dev}"))


def child_main(cfg_path):
    from .evalset import load_set
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    items = load_set(cfg["set"])
    if cfg.get("tasks"):
        items = [i for i in items if i["task"] in cfg["tasks"]]
    res = run_one(cfg["candidate"], cfg["device"], items, cfg["models_dir"], cfg["tools_dir"])
    sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
