"""The reference-profile benchmark (dev only, not shipped): each model and variant on each reference profile, at
Gentle, against every dimension of the floor (spec 2026-11-22 hardware intelligence §5.1, A10, A12).

    python tools/bench_profiles.py --results <runs.jsonl> --work <scratch folder>
        --photos <folder of photos> --queries <queries.json>
        --photo-model siglip2-base:fp16-vision=<folder with vision.onnx, text.onnx, tokenizer.json> [...]
        --talk-model smolvlm2-500m=<folder with its two .gguf files> [...]
        --llama-cpu <unpacked llama.cpp CPU runtime> --llama-vulkan <unpacked Vulkan runtime>
        --talk-images <folder with dog-01.jpg, dog-02.jpg, sign-01.jpg, cat-01.jpg>
        [--profiles mid,low,high] [--max-runs N]
    python tools/bench_profiles.py --report --results <runs.jsonl>      (markdown tables + the catalog rows)

Every folder is an argument: nothing here knows a path on anyone's PC. Each model's files are checked against the
catalog's size and SHA-256 before a run (a folder that doesn't match is refused).

**The reference profiles are emulated on this PC** (constraints: "Reference profiles"), one fresh process per run,
inside a job object of its own:
- `low`: 4 threads (the job's processor affinity), Find's worker memory cap as on an 8 GB PC
  (jobs.worker_memory_limit_mb(8192) = 2,048 MB), processor only (no Vulkan run);
- `mid`: 8 threads, 16 GB (cap 4,096 MB), the built-in GPU allowed (talk on llama-vulkan too; ONNX CPU build);
- `high`: every thread, 16 GB. This PC has no dedicated graphics memory: discrete-GPU rows are not measured.
Gentle is emulated for a PC with that many threads: the worker group's CPU hard cap is governor.CPU_CAP["gentle"]
(35 %) of THAT PC's threads, so as a share of this PC's it is 35 % x threads / all threads (job CPU rate in 1/100 %);
the photo worker gets the threads the governor gives it at Gentle on that PC (governor.op_limits) and its idle
priority (winapi.worker_priority); the talk worker runs in its own WORKERS group as in the app (memory cap + the
model's measured need, jobs.set_talk_allowance) through tools/measure_talk.py's runner. Searches run like the
engine process: the profile's affinity, no worker cap.

**What each workload run measures:**
- `photo_search`: a 500-photo indexing run through photo.embed_photo (the app's worker code): photos/s, time to the
  first vector, peak private memory and working set, crashes (the process failing or a photo failing with
  out-of-memory) and watchdog kills (working set over watchdog.WORKER_MB, where the app would end the worker);
  then 50 searches (the first 50 non-negative questions in the file, warm: after one question not counted): the
  question encoded as the app does (TextEncoder.encode_question, uncached) and scored against the 500 vectors,
  p50/p95 ms. Usefulness is not measured here: it is the recorded evaluation (USEFULNESS, docs/measurements.md).
- `photo_talk`: 10 Describe / Ask / Compare jobs on one fresh worker (the first is the cold load): first word p95
  (nearest rank), load time (model + context + vision part), peak memory (private, working set and shared graphics
  memory; the floor counts the biggest once, as models.talk_need_mb does), crashes, hang kills (Talker's
  check_deadline, the app's) and watchdog kills (working set over max(WORKER_MB, TALK_SHARE x need)), and the
  three correctness checks of the real-model test (tests/test_vlm_session.py): a red circle described as red or a
  circle, its colour asked and answered "red", a compare that answers.

Before each run: at least MIN_FREE_MB free (and for talk the model's need + 1 GB), and no full-screen game
(winapi.fullscreen_game): otherwise it stops and records nothing, so a rerun picks up there. Each finished run is
appended to --results as one JSON line; a rerun skips the keys already there. Needs psutil, pywin32, Pillow (dev).
"""
import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

from nobadfind import governor, jobs, models  # noqa: E402
from nobadfind.modelsuggest import FLOORS  # noqa: E402  (the one floor table)

LEVEL = governor.GENTLE
MIN_FREE_MB = 2560
TALK_SPARE_MB = 1024
PROFILE_ORDER = ("mid", "low", "high")          # this PC's native profile first
PROFILES = {"low": {"threads": 4, "ram_mb": 8192, "cpu_only": True},
            "mid": {"threads": 8, "ram_mb": 16384, "cpu_only": False},
            "high": {"threads": None, "ram_mb": 16384, "cpu_only": False}}
PHOTOS_N, SEARCHES_N = 500, 50
RUN_TIMEOUT_S = 2400
# the floor: modelsuggest.FLOORS, the app's one table (constraints, "The floor is a guaranteed experience")
# Usefulness: the recorded evaluation (tools/eval_photo_search.py, 556 photos / 155 searches, 2026-11-22 "SigLIP 2
# base vs SigLIP base, side by side"; results files pm-siglip-base.json and pm-s2-tq-v16.json, their
# by_channel.find figures per channel: nDCG@10, recall@10, searches), Find's pipeline,
# the searches whose channels include V (look) or C (caption): the visual / described categories. Nothing tuned.
USEFULNESS = {
    ("siglip-base", "8bit"): {"V": (0.778, 0.860, 56), "C": (0.771, 0.849, 28)},
    ("siglip2-base", "fp16-vision"): {"V": (0.821, 0.877, 56), "C": (0.794, 0.844, 28)},
}
TALK_JOBS = [("describe", ["dog-01.jpg"], ""), ("ask", ["sign-01.jpg"], "What's written here?"),
             ("compare", ["dog-01.jpg", "dog-02.jpg"], ""), ("describe", ["cat-01.jpg"], ""),
             ("describe", ["red-circle.png"], ""), ("ask", ["red-circle.png"], "What colour is the shape?"),
             ("compare", ["red-circle.png", "blue-square.png"], ""), ("describe", ["dog-02.jpg"], ""),
             ("ask", ["cat-01.jpg"], "What animal is this?"), ("compare", ["cat-01.jpg", "dog-01.jpg"], "")]
TALK_PHOTOS = ("dog-01.jpg", "dog-02.jpg", "sign-01.jpg", "cat-01.jpg")


def usefulness(mid, variant):
    """{"visual_ndcg10", "visual_recall10", "n"} over the V and C searches (weighted by their counts), or None.
    Only a variant's own evaluation counts: fp32 vision gave fp16's vectors on 50 photos, but it doesn't take fp16's
    figures until the spec's 200-input equivalence check and its own evaluation are run."""
    u = USEFULNESS.get((mid, variant))
    if not u:
        return None
    n = sum(c[2] for c in u.values())
    return {"visual_ndcg10": round(sum(c[0] * c[2] for c in u.values()) / n, 3),
            "visual_recall10": round(sum(c[1] * c[2] for c in u.values()) / n, 3), "n": n}


def p95(xs):
    """Nearest-rank 95th percentile: the ceil(0.95 n)-th smallest (10 samples: the slowest). None when empty."""
    xs = sorted(x for x in xs if x is not None)
    return xs[math.ceil(0.95 * len(xs)) - 1] if xs else None


def emulation(profile, total_threads):
    p = PROFILES[profile]
    n = min(p["threads"] or total_threads, total_threads)
    photo = governor.op_limits(LEVEL, governor._fallback_plan(n), cpu_count=n)["photo"]["effective"]
    return {"profile": profile, "level": LEVEL, "threads": n, "affinity": list(range(n)), "ram_mb": p["ram_mb"],
            "job_memory_mb": jobs.worker_memory_limit_mb(p["ram_mb"]), "cpu_only": p["cpu_only"],
            "cpu_rate": round(governor.CPU_CAP[LEVEL] * n / total_threads * 100), "photo_threads": photo}


def _key(s):
    return "|".join((s["workload"], s["model"], s["variant"], s["backend"], s["profile"]))


def matrix(photo_models, talk_models, profiles=PROFILE_ORDER):
    """The runs, mid first: photo_search per (model, variant), photo_talk per model x runtime (cpu only on low)."""
    out = []
    for prof in [p for p in PROFILE_ORDER if p in profiles]:
        for mid, variant in photo_models:
            out.append({"workload": "photo_search", "model": mid, "variant": variant, "backend": "cpu",
                        "profile": prof})
        for mid in talk_models:
            variant = models.variants(mid)[0]["id"]
            for backend in ("cpu",) if PROFILES[prof]["cpu_only"] else ("cpu", "vulkan"):
                out.append({"workload": "photo_talk", "model": mid, "variant": variant, "backend": backend,
                            "profile": prof})
    for s in out:
        s["key"] = _key(s)
    return out


def need_mb(spec):
    if spec["workload"] != "photo_talk":
        return 0
    return models.talk_need_mb(models.get(spec["model"]), "llama-" + spec["backend"])


def preflight(spec, free_mb, game):
    if game():
        return "stopped: a full-screen game is running"
    free = free_mb()
    if free < MIN_FREE_MB:
        return f"only {free:.0f} MB free (at least {MIN_FREE_MB} MB needed)"
    need = need_mb(spec)
    if need and free < need + TALK_SPARE_MB:
        return f"only {free:.0f} MB free; {spec['model']} on {spec['backend']} needs {need} MB + {TALK_SPARE_MB} MB"
    return None


def done_keys(results):
    if not os.path.isfile(results):
        return set()
    with open(results, encoding="utf-8") as f:
        return {json.loads(x)["key"] for x in f if x.strip()}


def run_all(specs, runner, results, free_mb, game, total_threads, max_runs=None):
    """Run the specs not in results yet, appending each finished one. Stops (recording nothing) when memory is
    short or a game runs. -> {"ran": [keys], "stopped": reason or None, "left": n}."""
    done, ran = done_keys(results), []
    todo = [s for s in specs if s["key"] not in done]
    for spec in todo:
        if max_runs is not None and len(ran) >= max_runs:
            break
        why = preflight(spec, free_mb, game)
        if why:
            print(why, flush=True)
            return {"ran": ran, "stopped": why, "left": len(todo) - len(ran)}
        emu = emulation(spec["profile"], total_threads)
        free0 = free_mb()
        t0 = time.time()
        res = runner(spec, emu)
        line = {"key": spec["key"], "spec": spec, "emu": emu, "started": round(t0), "seconds": round(time.time() - t0, 1),
                "free_before_mb": round(free0), "result": res}
        with open(results, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=True) + "\n")
        ran.append(spec["key"])
        print(f"done {spec['key']} in {line['seconds']} s", flush=True)
    return {"ran": ran, "stopped": None, "left": len(todo) - len(ran)}


# ---------- judging a run against the floor ----------
def _v(ok):
    return "pass" if ok else "fail"


def _search_reliable(r):
    return (r.get("photos") == PHOTOS_N and r.get("searches") == SEARCHES_N and not r.get("crashes")
            and not r.get("kills") and not r.get("errors") and not r.get("search_crashes"))


def _search_memory(r, profile):
    ram = PROFILES[r.get("profile") or profile]["ram_mb"]
    cap = jobs.worker_memory_limit_mb(ram)
    return r.get("worker_peak_mb") is not None and r["worker_peak_mb"] <= min(FLOORS["photo_search"]["ram_share"] * ram,
                                                                             cap)


def judge_search(r, profile, use, smaller):
    """{dimension: pass | fail | not measured} for a photo_search run on a reference profile. use: usefulness() of
    the model; smaller: the same variant's run on the next smaller profile (None: not measured)."""
    f = FLOORS["photo_search"]
    out = {"usefulness": "not measured" if not use else _v(use["visual_ndcg10"] >= f["ndcg10"]
                                                           and use["visual_recall10"] >= f["recall10"]),
           "reliability": _v(_search_reliable(r)),
           "responsiveness": _v((r.get("items_s") or 0) >= f["items_s"] and r.get("query_p95_ms") is not None
                                and r["query_p95_ms"] <= f["query_p95_ms"]),
           "memory": _v(_search_memory(r, profile)),
           "availability": "pass",                     # every photo variant here runs on the ONNX CPU build
           "degradation": "not measured" if smaller is None else _v(
               _search_reliable(smaller) and _search_memory(smaller, profile))}
    return out


def _talk_reliable(r):
    return (r.get("runs") == FLOORS["photo_talk"]["runs"] and (r.get("cold") or 0) >= 1 and not r.get("crashes")
            and not r.get("hang_kills") and not r.get("kills"))


def _talk_memory(r, profile):
    ram = PROFILES[r.get("profile") or profile]["ram_mb"]
    return r.get("peak_mb") is not None and r["peak_mb"] <= FLOORS["photo_talk"]["ram_share"] * ram


def judge_talk(r, profile, cpu_ok, smaller):
    """As judge_search for a photo_talk run. cpu_ok: this model's llama-cpu run on this profile was reliable."""
    f = FLOORS["photo_talk"]
    return {"usefulness": _v(r.get("checks") == f["checks"] and r.get("checks_passed") == f["checks"]),
            "reliability": _v(_talk_reliable(r)),
            "responsiveness": _v(r.get("first_word_p95_s") is not None and r["first_word_p95_s"] <= f["first_word_p95_s"]
                                 and r.get("load_s") is not None and r["load_s"] <= f["load_s"]),
            "memory": _v(_talk_memory(r, profile)),
            "availability": _v(cpu_ok),
            "degradation": "not measured" if smaller is None else _v(
                _talk_reliable(smaller) and _talk_memory(smaller, profile))}


# ---------- the real runner (Windows) ----------
_LIMIT_AFFINITY = 0x10


def _job_affinity(job, cpus):
    info = jobs._Extended()
    if not jobs._k.QueryInformationJobObject(job.handle, jobs._CLS_EXTENDED, ctypes.byref(info), ctypes.sizeof(info),
                                             None):
        return False
    info.Basic.LimitFlags |= _LIMIT_AFFINITY
    info.Basic.Affinity = sum(1 << c for c in cpus)
    return bool(jobs._k.SetInformationJobObject(job.handle, jobs._CLS_EXTENDED, ctypes.byref(info),
                                                ctypes.sizeof(info)))


def set_cpu_rate(job, rate):
    """The job's CPU hard cap in 1/100 of a percent of all of this PC's CPU time (finer than Job.set_cpu_cap)."""
    info = jobs._CpuRate()
    info.ControlFlags = jobs._CPU_ENABLE | jobs._CPU_HARD_CAP
    info.CpuRate = max(1, min(10000, int(rate)))
    return bool(jobs._k.SetInformationJobObject(job.handle, jobs._CLS_CPU_RATE, ctypes.byref(info),
                                                ctypes.sizeof(info)))


def cpu_rate(job):
    info = jobs._CpuRate()
    if not jobs._k.QueryInformationJobObject(job.handle, jobs._CLS_CPU_RATE, ctypes.byref(info), ctypes.sizeof(info),
                                             None):
        return None
    return info.CpuRate if info.ControlFlags & jobs._CPU_ENABLE else None


def child(payload, emu, cap_memory_cpu, log_path):
    """Run one --child process in a job with the profile's affinity (and the worker caps when asked); -> its JSON
    result plus what the job saw (every process's affinity, the job's peak memory, the exit code)."""
    import psutil
    job = jobs.Job()
    if not job.handle or not _job_affinity(job, emu["affinity"]):
        return {"crashed": True, "why": "could not set the job's affinity"}
    if cap_memory_cpu and not (job.set_memory_limit(emu["job_memory_mb"]) and set_cpu_rate(job, emu["cpu_rate"])):
        return {"crashed": True, "why": "could not set the job's memory or CPU cap"}
    with open(log_path, "ab") as log:
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--child"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=log, cwd=APP)
        if not job.assign(p.pid):
            p.kill()
            return {"crashed": True, "why": "could not put the run in its job"}
        seen, stop = {}, threading.Event()

        def watch():
            while not stop.is_set():
                for pid in job.pids():
                    try:
                        seen.setdefault(pid, (psutil.Process(pid).name(), sorted(psutil.Process(pid).cpu_affinity())))
                    except Exception:
                        pass
                stop.wait(0.5)
        threading.Thread(target=watch, daemon=True).start()
        try:
            out, _ = p.communicate(json.dumps({"payload": payload, "emu": emu}).encode() + b"\n",
                                   timeout=RUN_TIMEOUT_S)
            timed_out = False
        except subprocess.TimeoutExpired:
            p.kill()
            out, _ = p.communicate()
            timed_out = True
        stop.set()
    lines = [x for x in out.decode("utf-8", "replace").splitlines() if x.startswith("{")]
    res = json.loads(lines[-1]) if lines and not timed_out else {}
    res.update({"exit_code": p.returncode, "timed_out": timed_out, "job_peak_mb": job.memory_peak_mb(),
                "job_cpu_rate": cpu_rate(job) if cap_memory_cpu else None,
                "affinities": sorted({json.dumps(a) for _n, a in seen.values()}),
                "processes": sorted({n for n, _a in seen.values()})})
    res["crashed"] = bool(timed_out or p.returncode != 0 or not lines)
    job.close()
    return res


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def check_files(mid, folder, names):
    """Each of the model's files in folder at the catalog's size and SHA-256 (names: catalog name -> file name)."""
    m = models.get(mid)
    for name, (_path, size, sha) in m["files"].items():
        fp = os.path.join(folder, names.get(name, name))
        if not os.path.isfile(fp) or os.path.getsize(fp) != size or _sha(fp) != sha:
            sys.exit(f"{fp} is not {mid}'s pinned {name}")


def real_runner(a, photo_dirs, talk_dirs, photos, queries):
    def run(spec, emu):
        log_path = os.path.join(a.work, "children.log")
        if spec["workload"] == "photo_search":
            d = photo_dirs[(spec["model"], spec["variant"])]
            vecs = os.path.join(a.work, spec["key"].replace("|", "_") + ".npy")
            idx = child({"phase": "index", "model_dir": d, "photos": photos, "threads": emu["photo_threads"],
                         "vectors": vecs}, emu, True, log_path)
            srch = child({"phase": "search", "model_dir": d, "style": models.get(spec["model"])["style"],
                          "vectors": vecs, "queries": queries}, emu, False, log_path) if not idx["crashed"] else {}
            return summarize_search(idx, srch)
        rid = "llama-" + spec["backend"]
        res = child({"phase": "talk", "model": spec["model"], "model_dir": talk_dirs[spec["model"]],
                     "runtime_dir": a.llama_cpu if spec["backend"] == "cpu" else a.llama_vulkan,
                     "device": spec["backend"], "images": os.path.join(a.work, "talk-images"),
                     "need_mb": models.talk_need_mb(models.get(spec["model"]), rid)}, emu, False, log_path)
        return summarize_talk(res, models.talk_need_mb(models.get(spec["model"]), rid))
    return run


def summarize_search(idx, srch):
    from nobadfind import watchdog
    return {"photos": idx.get("ok", 0), "errors": idx.get("oom", 0), "unreadable": idx.get("unreadable", 0),
            "crashes": int(bool(idx.get("crashed"))) + int(bool(srch.get("crashed"))) + idx.get("oom", 0),
            "kills": int((idx.get("peak_ws_mb") or 0) > watchdog.WORKER_MB),
            "items_s": idx.get("items_s"), "load_s": idx.get("load_s"), "first_vector_s": idx.get("first_vector_s"),
            "worker_peak_mb": max(idx.get("peak_private_mb") or 0, idx.get("peak_ws_mb") or 0) or None,
            "worker_peak_private_mb": idx.get("peak_private_mb"), "worker_peak_ws_mb": idx.get("peak_ws_mb"),
            "job_peak_mb": idx.get("job_peak_mb"), "job_cpu_rate": idx.get("job_cpu_rate"),
            "affinities": idx.get("affinities"), "searches": srch.get("n", 0),
            "search_crashes": int(bool(srch.get("crashed"))), "query_p50_ms": srch.get("p50_ms"),
            "query_p95_ms": srch.get("p95_ms"), "query_max_ms": srch.get("max_ms"),
            "query_load_s": srch.get("load_s"), "search_peak_private_mb": srch.get("peak_private_mb"),
            "search_affinities": srch.get("affinities"), "index_raw": {k: v for k, v in idx.items() if k != "errs"},
            "errs": idx.get("errs", [])[:5]}


def summarize_talk(res, need):
    from nobadfind import watchdog
    rows = res.get("jobs") or []
    texts = [(r.get("text") or "").lower() for r in rows]
    checks = [len(texts) > 4 and ("red" in texts[4] or "circle" in texts[4]),
              len(texts) > 5 and "red" in texts[5], len(texts) > 6 and bool(texts[6].strip())]
    peak = max(res.get("peak_private_mb") or 0, res.get("peak_working_set_mb") or 0, res.get("gpu_shared_mb") or 0)
    return {"runs": sum(r.get("state") == "done" for r in rows), "jobs": len(rows),
            "cold": 1 if rows and rows[0].get("state") == "done" else 0,
            "crashes": int(bool(res.get("crashed"))) + sum(r.get("state") == "error" for r in rows),
            "timeouts": sum(r.get("state") == "timeout" for r in rows),
            "hang_kills": res.get("hang_kills", 0) or 0,
            "kills": int((res.get("peak_working_set_mb") or 0) > max(watchdog.WORKER_MB, watchdog.TALK_SHARE * need)),
            "first_word_p95_s": p95([r.get("first_word_s") for r in rows]),
            "first_words_s": [r.get("first_word_s") for r in rows], "totals_s": [r.get("total_s") for r in rows],
            "cold_first_word_s": rows[0].get("first_word_s") if rows else None,
            "load_s": rows[0].get("load_s") if rows else None, "peak_mb": peak or None,
            "peak_private_mb": res.get("peak_private_mb"), "peak_ws_mb": res.get("peak_working_set_mb"),
            "gpu_shared_mb": res.get("gpu_shared_mb"), "gpu_dedicated_mb": res.get("gpu_dedicated_mb"),
            "private_plus_shared_mb": (res.get("peak_private_mb") or 0) + (res.get("gpu_shared_mb") or 0),
            "checks": 3, "checks_passed": sum(bool(c) for c in checks), "check_results": checks,
            "answers": [(r.get("op"), r.get("images"), (r.get("text") or "")[:120]) for r in rows],
            "cpu_cap": res.get("cpu_rate"), "workers_limit_mb": res.get("workers_limit_mb"),
            "free_before_mb": res.get("free_before_mb"), "min_free_mb": res.get("min_free_mb"),
            "affinities": res.get("affinities"), "processes": res.get("processes"), "why": res.get("why")}


# ---------- inside the child process ----------
def _peak_private_mb():
    from nobadfind import jobs as j
    pmc = j._PMC()
    pmc.cb = ctypes.sizeof(j._PMC)
    j._psapi.GetProcessMemoryInfo(j._k.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return round(pmc.PeakPagefileUsage / 1048576), round(pmc.PeakWorkingSetSize / 1048576)


def child_index(p):
    import importlib
    importlib.import_module("onnxruntime")              # before anything that loads winrt (MSVCP140)
    import numpy as np
    from nobadfind import photo, winapi
    winapi.worker_priority()                             # the photo worker's own idle priority, as in the app
    photo._threads[0] = int(p["threads"])
    out = {"threads": p["threads"], "ok": 0, "oom": 0, "unreadable": 0, "errs": []}
    vecs = []
    t0 = time.perf_counter()
    first = None
    for i, path in enumerate(p["photos"]):
        _id, _mt, blob, err = photo.embed_photo((i, path, 0, p["model_dir"]))
        if first is None:
            first = time.perf_counter()
            out["first_vector_s"] = round(first - t0, 2)     # the session's load + the first photo
        if err == photo.OUT_OF_MEMORY:
            out["oom"] += 1
        elif err:
            out["unreadable"] += 1
            out["errs"].append((os.path.basename(path), err))
        else:
            out["ok"] += 1
            vecs.append(np.frombuffer(blob, np.float16))
    t1 = time.perf_counter()
    out["seconds"] = round(t1 - t0, 2)
    out["items_s"] = round(len(p["photos"]) / (t1 - t0), 3)          # every photo, load included: honest wall time
    out["items_s_after_first"] = round((len(p["photos"]) - 1) / (t1 - first), 3) if len(p["photos"]) > 1 else None
    out["load_s"] = out["first_vector_s"]
    out["peak_private_mb"], out["peak_ws_mb"] = _peak_private_mb()
    np.save(p["vectors"], np.stack(vecs) if vecs else np.zeros((0, 768), np.float16))
    return out


def child_search(p):
    import importlib
    importlib.import_module("onnxruntime")
    import numpy as np
    from nobadfind import photo
    vecs = np.load(p["vectors"]).astype(np.float32)
    t0 = time.perf_counter()
    enc = photo.TextEncoder(p["model_dir"], style=p["style"])          # QUESTION_THREADS, as in the app
    enc.encode_question("a photo used to warm up")                      # warm: not counted
    out = {"load_s": round(time.perf_counter() - t0, 2)}
    ms = []
    for q in p["queries"]:
        t = time.perf_counter()
        v = enc.encode_question(q)
        s = vecs @ v
        top = np.argpartition(-s, min(60, len(s) - 1))[:60]
        out.setdefault("top1", []).append(int(top[np.argsort(-s[top])][0]))
        ms.append((time.perf_counter() - t) * 1000)
    out.update({"n": len(ms), "p50_ms": round(sorted(ms)[len(ms) // 2], 1), "p95_ms": round(p95(ms), 1),
                "max_ms": round(max(ms), 1)})
    out["peak_private_mb"], out["peak_ws_mb"] = _peak_private_mb()
    return out


def child_talk(p, emu):
    import importlib
    importlib.import_module("onnxruntime")
    import types
    import psutil
    from nobadfind import api, hardware as hw, winapi
    from nobadfind.vlm import worker
    spec = importlib.util.spec_from_file_location("measure_talk", os.path.join(APP, "tools", "measure_talk.py"))
    mt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mt)
    jobs.setup()                                          # this run's own WORKERS group, as the app makes it
    jobs._base_limit[0] = emu["job_memory_mb"]           # the profile's worker cap (an 8 GB PC's on low)
    if not (jobs.WORKERS.set_memory_limit(emu["job_memory_mb"]) and set_cpu_rate(jobs.WORKERS, emu["cpu_rate"])):
        return {"crashed": True, "why": "could not cap the worker group"}
    m = models.get(p["model"])
    rid = "llama-" + p["device"]
    a = types.SimpleNamespace(model=p["model"], model_dir=p["model_dir"], runtime_dir=p["runtime_dir"],
                              device=p["device"], images=p["images"], level=LEVEL, alloc_limit_mb=0, stops=False,
                              job_list=TALK_JOBS)
    free0 = psutil.virtual_memory().available / 1048576
    res = mt.run(a, m, rid, p["need_mb"], None, False, free0, psutil, api, hw, jobs, models, winapi, worker, None)
    res["cpu_rate"] = cpu_rate(jobs.WORKERS)
    res["workers_limit_mb"] = emu["job_memory_mb"]
    return res


def child_main():
    msg = json.loads(sys.stdin.readline())               # wait: the parent puts this process in its job first
    p, emu = msg["payload"], msg["emu"]
    res = {"index": child_index, "search": child_search}.get(p["phase"])
    res = res(p) if res else child_talk(p, emu)
    import psutil
    res["own_affinity"] = sorted(psutil.Process().cpu_affinity())
    print(json.dumps(res, ensure_ascii=True), flush=True)


def make_talk_images(src, dst):
    from PIL import Image, ImageDraw
    os.makedirs(dst, exist_ok=True)
    for n in TALK_PHOTOS:
        shutil.copyfile(os.path.join(src, n), os.path.join(dst, n))
    for name, shape, colour in (("red-circle.png", "circle", (220, 20, 20)), ("blue-square.png", "square",
                                                                              (20, 40, 220))):
        im = Image.new("RGB", (640, 480), (255, 255, 255))      # the drawings of tests/test_vlm_session.py
        d = ImageDraw.Draw(im)
        (d.ellipse if shape == "circle" else d.rectangle)((170, 90, 470, 390), fill=colour)
        im.save(os.path.join(dst, name), "PNG")


# ---------- the report ----------
def load(results):
    with open(results, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def judged(lines):
    """[(line, floor verdicts)] with the smaller profile's run for graceful degradation (mid -> low, high -> mid)."""
    by = {x["key"]: x for x in lines}
    smaller = {"mid": "low", "high": "mid", "low": None}
    out = []
    for x in lines:
        s, r = x["spec"], dict(x["result"], profile=x["spec"]["profile"])
        sm = smaller[s["profile"]]
        sm_line = by.get(_key(dict(s, profile=sm))) if sm else None
        if s["workload"] == "photo_talk" and sm_line is None and sm == "low" and s["backend"] == "vulkan":
            sm_line = by.get(_key(dict(s, profile=sm, backend="cpu")))     # low has no Vulkan: its CPU path
        sm_r = dict(sm_line["result"], profile=sm) if sm_line else None
        if s["workload"] == "photo_search":
            v = judge_search(r, s["profile"], usefulness(s["model"], s["variant"]), sm_r)
        else:
            cpu = by.get(_key(dict(s, backend="cpu")))
            v = judge_talk(r, s["profile"], bool(cpu) and _talk_reliable(cpu["result"]), sm_r)
        out.append((x, v))
    return out


def report(results):
    rows = judged(load(results))
    print("## photo_search\n")
    print("| profile | model, variant | photos/s (500, Gentle) | first vector s | worker peak MB (private / working set)"
          " | search p50 / p95 ms (50) | crashes / kills | usefulness V+C nDCG / recall | U | Rel | Resp | Mem | Avail"
          " | Degr |")
    print("|" + "---|" * 14)
    for x, v in rows:
        s, r = x["spec"], x["result"]
        if s["workload"] != "photo_search":
            continue
        u = usefulness(s["model"], s["variant"]) or {}
        print(f"| {s['profile']} | {s['model']} {s['variant']} | {r.get('items_s')} ({r.get('photos')} ok) | "
              f"{r.get('first_vector_s')} | {r.get('worker_peak_private_mb')} / {r.get('worker_peak_ws_mb')} | "
              f"{r.get('query_p50_ms')} / {r.get('query_p95_ms')} | {r.get('crashes')} / {r.get('kills')} | "
              f"{u.get('visual_ndcg10')} / {u.get('visual_recall10')} | " + " | ".join(
                  v[k] for k in ("usefulness", "reliability", "responsiveness", "memory", "availability",
                                 "degradation")) + " |")
    print("\n## photo_talk\n")
    print("| profile | model, runtime | runs done / 10 | first word p95 s | cold first word s | load s | peak MB "
          "(private / WS / shared) | crashes / hang / watchdog | checks | U | Rel | Resp | Mem | Avail | Degr |")
    print("|" + "---|" * 15)
    for x, v in rows:
        s, r = x["spec"], x["result"]
        if s["workload"] != "photo_talk":
            continue
        print(f"| {s['profile']} | {s['model']} {s['backend']} | {r.get('runs')} | {r.get('first_word_p95_s')} | "
              f"{r.get('cold_first_word_s')} | {r.get('load_s')} | {r.get('peak_private_mb')} / {r.get('peak_ws_mb')}"
              f" / {r.get('gpu_shared_mb')} | {r.get('crashes')} / {r.get('hang_kills')} / {r.get('kills')} | "
              f"{r.get('checks_passed')}/3 | " + " | ".join(
                  v[k] for k in ("usefulness", "reliability", "responsiveness", "memory", "availability",
                                 "degradation")) + " |")
    print("\n## catalog rows (models.MEASURED)\n")
    for x, v in rows:
        s, r = x["spec"], x["result"]
        row = {"workload": s["workload"], "items_s": r.get("items_s"), "query_ms": r.get("query_p95_ms"),
               # whole-process peak private bytes; working set and shared graphics memory beside it, never added
               "ram_mb": r.get("worker_peak_private_mb") if s["workload"] == "photo_search" else r.get("peak_private_mb"),
               "ws_mb": r.get("worker_peak_ws_mb") if s["workload"] == "photo_search" else r.get("peak_ws_mb"),
               "vram_mb": 0 if s["workload"] == "photo_search" else (r.get("gpu_dedicated_mb") or 0),
               "floor": v, "source": "measurements.md 2026-11-23: reference-profile benchmark"}
        # the need the floor and modelsuggest read: the biggest single figure (counters overlap; never summed)
        row["need_mb"] = max(row["ram_mb"] or 0, row["ws_mb"] or 0, r.get("gpu_shared_mb") or 0)
        if s["workload"] == "photo_talk":
            row.update(first_word_s=r.get("first_word_p95_s"), load_s=r.get("load_s"),
                       shared_mb=r.get("gpu_shared_mb") or 0)
        print(f"    {(s['model'], s['variant'], s['backend'], s['profile'])!r}: {json.dumps(row)},")
    print("\nruns: " + ", ".join(f"{x['key']} {x['seconds']} s" for x, _v in rows))
    print(f"total PC time: {sum(x['seconds'] for x, _v in rows) / 60:.1f} min")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--child"]:
        return child_main()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--work")
    ap.add_argument("--photos")
    ap.add_argument("--queries")
    ap.add_argument("--photo-model", action="append", default=[], help="model:variant=folder")
    ap.add_argument("--talk-model", action="append", default=[], help="model=folder")
    ap.add_argument("--llama-cpu")
    ap.add_argument("--llama-vulkan")
    ap.add_argument("--talk-images")
    ap.add_argument("--profiles", default=",".join(PROFILE_ORDER))
    ap.add_argument("--max-runs", type=int)
    a = ap.parse_args(argv)
    if a.report:
        return report(a.results)
    import psutil
    from nobadfind import llama_pins, winapi
    if not (a.work and a.photos and a.queries):
        sys.exit("--work, --photos and --queries are needed")
    os.makedirs(a.work, exist_ok=True)
    photo_dirs, talk_dirs = {}, {}
    for pm in a.photo_model:
        mv, d = pm.split("=", 1)
        mid, variant = mv.split(":")
        if variant not in {v["id"] for v in models.variants(mid)}:
            sys.exit(f"{mid} has no variant {variant}")
        if any(v["id"] == variant and v["files"] is None for v in models.variants(mid)):
            check_files(mid, d, {})
        else:
            sys.exit(f"{mid} {variant}: its files aren't pinned in the catalog, so they can't be checked")
        photo_dirs[(mid, variant)] = d
    for tm in a.talk_model:
        mid, d = tm.split("=", 1)
        check_files(mid, d, {n: p for n, (p, _s, _h) in models.get(mid)["files"].items()})
        talk_dirs[mid] = d
    for rdir, dlls in ((a.llama_cpu, llama_pins.CPU_DLLS), (a.llama_vulkan, llama_pins.VULKAN_DLLS)):
        if talk_dirs and rdir:
            for n, (size, sha) in dict(dlls).items():
                fp = os.path.join(rdir, n)
                if not os.path.isfile(fp) or os.path.getsize(fp) != size or _sha(fp) != sha:
                    sys.exit(f"{fp} is not the pinned {n}")
    if talk_dirs:
        make_talk_images(a.talk_images, os.path.join(a.work, "talk-images"))
    names = sorted(n for n in os.listdir(a.photos) if n.lower().endswith((".jpg", ".jpeg", ".png")))[:PHOTOS_N]
    photos = [os.path.join(a.photos, n) for n in names]
    with open(a.queries, encoding="utf-8") as f:
        qs = [q["text"] for q in json.load(f)["queries"] if q.get("category") != "negative"][:SEARCHES_N]
    specs = matrix(list(photo_dirs), list(talk_dirs), tuple(a.profiles.split(",")))
    out = run_all(specs, real_runner(a, photo_dirs, talk_dirs, photos, qs), a.results,
                  free_mb=lambda: psutil.virtual_memory().available / 1048576, game=winapi.fullscreen_game,
                  total_threads=os.cpu_count(), max_runs=a.max_runs)
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
