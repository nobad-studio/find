"""Talk about a photo: how long Describe / Ask / Compare take through the real talk worker (dev only, not shipped).

    python tools/measure_talk.py --model smolvlm2-500m --model-dir <folder with the model's two .gguf files>
        --runtime-dir <unpacked llama.cpp runtime> --device cpu|vulkan --images <folder> --level full|gentle|light
        --out <result.json> [--stops] [--leave-free-mb 3800 [--floor-mb 1536]] [--alloc-limit-mb 600]
        [--assess-only]

The worker is the app's own (vlm.worker.Talker, a spawned talk worker process) and it runs under the same limits
as in the app: this script sets up Find's process groups (jobs.setup, so the worker joins its own WORKERS group,
never a running Find's), gives the group the governor's CPU hard cap for --level (governor.CPU_CAP: Full none,
Gentle 35 %, Light 15 %), puts the worker in efficiency mode (EcoQoS) at Light like governor._eco_workers, and
raises the group's memory limit by the model's measured need (jobs.set_talk_allowance). The worker sets its own
idle CPU priority (winapi.worker_priority) and its normal memory / I/O priority while a job runs
(winapi.worker_activity). Nothing else from Find runs in the group, so the cap is the talk worker's alone (in the
app, indexing workers would share it).

One fresh worker per run. Jobs in order: Describe dog-01 (cold: start + load + answer), Ask "What's written here?"
on sign-01, Compare dog-01 with dog-02, Describe cat-01 (warm). For each: time to the first word (submit -> first
non-empty "answering" text), total, the longest wait between two events, and from the worker's own messages
(Talker's trace) each phase's length and its longest time without progress as the Talker counts it (a phase
start, a growing load fraction, a "still computing" call in a capped phase, a token in the answer). Also the
worker's peak private memory and working set, and its graphics memory (PDH "GPU Process Memory" counters).

--stops: then Stop (Talker.cancel) in each phase that can be stopped, timed from the cancel to the worker's
"cancelled": "model" (a fresh worker, at about 30 % of llama's load), "vision" (mtmd's load), "image" (half a
second into reading the photo), "answer" (after the first word); and the engine's own stop (Talker.stop, as a
pause / memory / runtime swap does) during "model", timed until the worker process has exited, with whether it had
to be terminated. The phases that can't be stopped are reported with their measured length (how long a Stop can
wait there).

--leave-free-mb: a memory hog (a child process, ended in a finally and with this script's process group) takes
memory until about that much is free, and gives it back whenever free memory falls under --floor-mb (default
1536), so the PC is never pushed below it. Then also: what the app says for both talk models at that free memory
on the runtime measured (api.talk_assess, i.e. capability.assess), and the processes older than a minute that were
gone at the end (nothing should be: Find only ever ends its own workers).

--alloc-limit-mb: the low-memory failure itself: the worker group's memory limit is set that low and NOT raised
for the model, one Describe is asked, and its final event is reported (it must be the plain "Not enough memory
right now ..." note, and the worker keeps serving).

Refuses to start when less than the model's need plus --margin-mb of memory is free (default 1024), counted after
the hog. Needs psutil and pywin32 (win32pdh), both in the dev environment. Results: docs/measurements.md.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

JOBS = [("describe", ["dog-01.jpg"], ""), ("ask", ["sign-01.jpg"], "What's written here?"),
        ("compare", ["dog-01.jpg", "dog-02.jpg"], ""), ("describe", ["cat-01.jpg"], "")]
FLOOR_MB = 1536
MIN_FLOOR_MB = 1024             # --floor-mb below this is refused: the hog never pushes the PC under 1 GB free
CHUNK_MB = 128


def gpu_mem(pid):
    """(dedicated MB, shared MB) the process holds now, from PDH; 0 for a counter that isn't there."""
    import win32pdh
    out = []
    for what in ("Dedicated Usage", "Shared Usage"):
        try:
            paths = win32pdh.ExpandCounterPath(rf"\GPU Process Memory(pid_{pid}_*)\{what}")
        except Exception:
            out.append(0)
            continue
        q = win32pdh.OpenQuery()
        hs = [win32pdh.AddCounter(q, p) for p in paths]
        win32pdh.CollectQueryData(q)
        tot = 0
        for h in hs:
            try:
                tot += win32pdh.GetFormattedCounterValue(h, win32pdh.PDH_FMT_LARGE)[1]
            except Exception:
                pass
        win32pdh.CloseQuery(q)
        out.append(tot / 1048576)
    return tuple(out)


# ---------- the memory hog (its own process) ----------
def hog(target_mb, floor_mb, parent):
    """Hold memory until about target_mb is free; give it back below floor_mb; end with the parent."""
    import psutil
    floor_mb = max(float(floor_mb), MIN_FLOOR_MB)
    held = []
    while psutil.pid_exists(parent):
        free = psutil.virtual_memory().available / 1048576
        if free < floor_mb and held:
            while held and psutil.virtual_memory().available / 1048576 < floor_mb + CHUNK_MB:
                held.pop()
        elif free > target_mb + CHUNK_MB:
            b = bytearray(CHUNK_MB * 1048576)
            b[::4096] = b"x" * len(b[::4096])               # touched: really committed and resident
            held.append(b)
            continue
        time.sleep(0.2)


def start_hog(target_mb, floor_mb, held, wait_s=60):
    """Start the hog and wait until free memory settles. The Popen goes into `held` BEFORE the wait, so a Ctrl+C
    during it still leaves the caller's finally something to kill."""
    import psutil
    if floor_mb < MIN_FLOOR_MB:
        raise ValueError(f"floor {floor_mb} MB is under the hard minimum {MIN_FLOOR_MB} MB")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--hog", str(target_mb), str(floor_mb),
                          str(os.getpid())])
    held.append(p)
    end = time.monotonic() + wait_s
    last, steady = -1.0, 0
    while time.monotonic() < end:                             # until it stops growing
        time.sleep(0.5)
        free = psutil.virtual_memory().available / 1048576
        steady = steady + 1 if abs(free - last) < 64 else 0
        last = free
        if steady >= 4:
            break
    return p


def stop_hog(p):
    if p is None:
        return
    try:
        p.kill()
        p.wait(10)
    except Exception:
        pass


# ---------- what the worker's messages say about progress ----------
def phase_stats(trace, t0, t_end, jid):
    """{phase: {"s": length, "longest_no_progress_s": ..., "progress": n}} for one job, counted as Talker does."""
    from nobadfind.vlm import worker
    order = worker.PHASE_ORDER
    phase, since, last, frac = "start", t0, t0, -1.0
    out = {}

    def note(p, a, b):
        d = out.setdefault(p, {"s": 0.0, "longest_no_progress_s": 0.0, "progress": 0})
        d["longest_no_progress_s"] = round(max(d["longest_no_progress_s"], b - a), 2)

    def close(p, a, b):
        out.setdefault(p, {"s": 0.0, "longest_no_progress_s": 0.0, "progress": 0})["s"] = round(b - a, 2)

    for ts, m in trace:
        if m.get("job") != jid or ts < t0:
            continue
        t = m.get("t")
        new = {"phase": m.get("phase"), "token": "answer",
               "state": {"loading": "prepare", "answering": "image"}.get(m.get("state"))}.get(t)
        if new in order and order.index(new) > order.index(phase):
            note(phase, last, ts)
            close(phase, since, ts)
            phase, since, last, frac = new, ts, ts, -1.0
            if t != "token":
                continue
        moved = False
        if t == "progress" and m.get("phase") == phase:
            f = m.get("frac")
            if f is not None and phase in worker.FRACTION_PHASES and f > frac:
                frac, moved = f, True
            elif f is None and worker.PHASES[phase][1] is not None:
                moved = True
        elif t == "token" and phase == "answer":
            moved = True
        if moved:
            note(phase, last, ts)
            out[phase]["progress"] += 1
            last = ts
        if t in ("done", "error") or (t == "state" and m.get("state") == "cancelled"):
            break
    note(phase, last, t_end)
    close(phase, since, t_end)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--hog"]:
        return hog(float(argv[1]), float(argv[2]), int(argv[3]))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="talk model id (models.talk_models)")
    ap.add_argument("--model-dir", required=True, help="folder with the model's two .gguf files (catalog names)")
    ap.add_argument("--runtime-dir", required=True, help="unpacked llama.cpp runtime folder")
    ap.add_argument("--device", choices=("cpu", "vulkan"), required=True)
    ap.add_argument("--images", required=True, help="folder with dog-01.jpg, dog-02.jpg, sign-01.jpg, cat-01.jpg")
    ap.add_argument("--level", choices=("full", "gentle", "light"), required=True)
    ap.add_argument("--out", required=True, help="where the JSON result goes")
    ap.add_argument("--margin-mb", type=int, default=1024, help="free memory to keep beside the model's need")
    ap.add_argument("--stops", action="store_true", help="also time Stop in each phase")
    ap.add_argument("--leave-free-mb", type=int, default=0, help="a memory hog leaves about this much free")
    ap.add_argument("--floor-mb", type=int, default=FLOOR_MB, help="the hog never lets free memory fall below")
    ap.add_argument("--alloc-limit-mb", type=int, default=0, help="only the low-memory failure, at this job limit")
    ap.add_argument("--assess-only", action="store_true", help="only what the app says at this free memory")
    a = ap.parse_args(argv)

    import psutil
    from nobadfind import api, governor, jobs, models, winapi
    from nobadfind import hardware as hw
    from nobadfind.vlm import worker

    m = models.get(a.model)
    if not m or m.get("feature") != "talk":
        sys.exit(f"not a talk model: {a.model}")
    if a.floor_mb < MIN_FLOOR_MB:
        sys.exit(f"--floor-mb {a.floor_mb} is under the hard minimum {MIN_FLOOR_MB} MB")
    if a.leave_free_mb and a.leave_free_mb < a.floor_mb:
        sys.exit(f"--leave-free-mb {a.leave_free_mb} is under the floor {a.floor_mb}")
    rid = "llama-vulkan" if a.device == "vulkan" else "llama-cpu"
    need = models.talk_need_mb(m, rid)
    if psutil.virtual_memory().available / 1048576 < need + a.margin_mb and not (a.leave_free_mb or a.assess_only):
        sys.exit(f"only {psutil.virtual_memory().available / 1048576:.0f} MB free; {a.model} on {a.device} needs "
                 f"{need} MB + {a.margin_mb} MB margin")

    jobs.setup()                                          # OUTER + this run's own WORKERS group (memory limit)
    cap = governor.CPU_CAP[a.level]
    if cap is not None and not jobs.WORKERS.set_cpu_cap(cap):    # Full: no cap (a new group has none)
        sys.exit("could not set the worker group's CPU cap")
    if jobs.WORKERS.cpu_cap() != cap:
        sys.exit(f"the worker group's CPU cap is {jobs.WORKERS.cpu_cap()}, not {cap}")
    eco = a.level in governor.ECO_LEVELS

    old = {p.pid: (p.info["name"], p.info["create_time"]) for p in psutil.process_iter(["name", "create_time"])
           if p.info["create_time"] and time.time() - p.info["create_time"] > 60}
    held, hogp = [], None
    try:
        if a.leave_free_mb:
            hogp = start_hog(a.leave_free_mb, a.floor_mb, held)
        free0 = psutil.virtual_memory().available / 1048576
        if a.assess_only:
            res = {"model": a.model, "device": a.device, "level": a.level, "hog": bool(hogp),
                   "floor_mb": a.floor_mb if hogp else None, "assess": assess(free0, api, hw, models, rid)}
        elif free0 < need + a.margin_mb:
            sys.exit(f"only {free0:.0f} MB free; {a.model} on {a.device} needs {need} MB + {a.margin_mb} MB margin")
        else:
            res = run(a, m, rid, need, cap, eco, free0, psutil, api, hw, jobs, models, winapi, worker, hogp)
    finally:
        for p in held:                                    # also when Ctrl+C came while the hog was settling
            stop_hog(p)
    gone = sorted({n for pid, (n, ct) in old.items()
                   if not (psutil.pid_exists(pid) and psutil.Process(pid).create_time() == ct)})
    res["old_processes_gone"] = gone
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in res.items() if k not in ("jobs", "stops")}), flush=True)


def assess(free_mb, api, hw, models, runtime):
    """What the app says now (Api._vision_model's check) at this free memory, on the runtime measured: api.talk_assess
    (capability.assess with the model's measured need on that runtime) for the deeper model and the quick one."""
    sample = type("Sample", (), {"free_mb": free_mb})()
    pc = hw.scan()
    talk = models.talk_models()
    return {"free_mb": round(free_mb), "runtime": runtime,
            "deeper": list(api.talk_assess(models.get("qwen3vl-2b"), sample, pc, runtime)),
            "quick": list(api.talk_assess(talk[0], sample, pc, runtime))}


def run(a, m, rid, need, cap, eco, free0, psutil, api, hw, jobs, models, winapi, worker, hogp):
    names = {k: v[0] for k, v in m["files"].items()}
    model = {"id": a.model, "model": os.path.join(a.model_dir, names["model.gguf"]),
             "mmproj": os.path.join(a.model_dir, names["mmproj.gguf"]), "runtime": a.runtime_dir}
    settings = dict(m["talk"])
    settings["need_mb"] = need or None                    # as Api._vision_job
    events, trace, cond = [], [], threading.Condition()
    verdict = assess(free0, api, hw, models, rid)

    def emit(ev):
        with cond:
            events.append((time.perf_counter(), dict(ev)))
            cond.notify_all()

    def seen(msg, _now):
        with cond:
            trace.append((time.perf_counter(), dict(msg)))
            cond.notify_all()

    budget = (lambda mb: None) if a.alloc_limit_mb else jobs.set_talk_allowance
    if a.alloc_limit_mb:
        jobs.WORKERS.set_memory_limit(a.alloc_limit_mb)
    t = worker.Talker(emit, on_budget=budget, trace=seen)
    peak = {"ded": 0.0, "sh": 0.0, "ws": 0.0, "private": 0.0, "min_free": free0, "hang_kills": 0}
    state = {"in_job": False, "eco": False, "pid": None}
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            peak["min_free"] = min(peak["min_free"], psutil.virtual_memory().available / 1048576)
            pid = next(iter(t.pids()), None)
            if pid:
                inside = pid in jobs.WORKERS.pids()
                state["in_job"] = state["in_job"] or inside
                if eco and inside and state["pid"] != pid:      # the governor sets it once per worker (its tick)
                    if winapi.eco_qos(True, pid=pid, job=jobs.WORKERS.handle):
                        state["eco"], state["pid"] = True, pid
                try:
                    mi = psutil.Process(pid).memory_info()
                    peak["ws"] = max(peak["ws"], mi.rss / 1048576)
                    peak["private"] = max(peak["private"], mi.peak_pagefile / 1048576)
                    d, s = gpu_mem(pid)
                    peak["ded"], peak["sh"] = max(peak["ded"], d), max(peak["sh"], s)
                except Exception:
                    pass
            if t.check_deadline():                            # the governor's tick: the real hang deadline
                peak["hang_kills"] += 1
                print("DEADLINE: the worker was ended as hung", flush=True)
            time.sleep(0.25)
    threading.Thread(target=sampler, daemon=True).start()

    def submit(op, imgs, q):
        jid = t.next_id()
        job = {"job": jid, "op": op, "paths": [os.path.join(a.images, i) for i in imgs], "question": q,
               "model": model, "settings": settings, "gpu_layers": 99 if a.device == "vulkan" else 0, "files": [1]}
        t0 = time.perf_counter()
        t.submit(job, m["name"])
        return jid, t0

    def wait_trace(pred, timeout=900):
        end = time.perf_counter() + timeout
        with cond:
            while time.perf_counter() < end:
                for ts, msg in trace:
                    if pred(msg):
                        return ts
                cond.wait(0.5)
        return None

    def finished(jid, timeout=900):
        end = time.perf_counter() + timeout
        with cond:
            while time.perf_counter() < end:
                done = [e for e in events if e[1]["job"] == jid and e[1]["state"] in ("done", "error", "cancelled")]
                if done:
                    return done[0]
                cond.wait(1)
        return None

    rows = []
    jobs_to_run = JOBS[:1] if a.alloc_limit_mb else (getattr(a, "job_list", None) or JOBS)   # bench_profiles: 10
    for op, imgs, q in jobs_to_run:
        jid, t0 = submit(op, imgs, q)
        done = finished(jid)
        with cond:
            mine = [(ts, e) for ts, e in events if e["job"] == jid]
            tr = list(trace)
        words = [ts for ts, e in mine if e["state"] == "answering" and e["text"].strip()]
        end = done or (time.perf_counter(), {"state": "timeout", "text": "", "note": ""})
        marks = [t0] + [ts for ts, _e in mine] + [end[0]]
        ph = phase_stats(tr, t0, end[0], jid)
        image_at = next((ts for ts, msg in tr if msg.get("job") == jid and msg.get("t") == "phase"
                         and msg.get("phase") == "image"), None)
        model_at = next((ts for ts, msg in tr if msg.get("job") == jid and msg.get("t") == "phase"
                         and msg.get("phase") == "model"), None)
        rows.append({"op": op, "images": imgs, "question": q, "state": end[1]["state"],
                     "first_word_s": round(words[0] - t0, 2) if words else None, "total_s": round(end[0] - t0, 2),
                     "longest_wait_s": round(max(b - x for x, b in zip(marks, marks[1:])), 2),
                     "load_s": round(image_at - model_at, 2) if image_at and model_at else None,
                     "until_photo_read_s": round(image_at - t0, 2) if image_at else None,
                     "phases": ph, "text": end[1].get("text", "")[:300], "note": end[1].get("note", "")})
        print(json.dumps(rows[-1], ensure_ascii=True), flush=True)
    if a.alloc_limit_mb:                                  # the worker keeps serving after the failure?
        jobs.set_talk_allowance(0)
        jobs.WORKERS.set_memory_limit(jobs._base_limit[0] + need)
        jid, t0 = submit("describe", ["dog-01.jpg"], "")
        done = finished(jid)
        rows.append({"op": "describe (limit back up)", "state": done[1]["state"] if done else "timeout",
                     "total_s": round((done[0] if done else time.perf_counter()) - t0, 2),
                     "note": done[1].get("note", "") if done else "", "text": done[1].get("text", "")[:120] if done
                     else ""})
        print(json.dumps(rows[-1], ensure_ascii=True), flush=True)
    pid = next(iter(t.pids()), None)
    try:
        peak["private"] = max(peak["private"], psutil.Process(pid).memory_info().peak_pagefile / 1048576 if pid
                              else 0)
    except Exception:
        pass

    stops = []
    if a.stops and not a.alloc_limit_mb:
        def stop_in(phase, ready, fresh):
            if fresh:
                t.stop()
            jid, t0 = submit("describe", ["dog-01.jpg"], "")
            at = wait_trace(lambda msg: msg.get("job") == jid and ready(msg), 600)
            if at is None:
                return {"phase": phase, "error": "never reached"}
            time.sleep(0.05 if phase != "image" else 0.5)
            c0 = time.perf_counter()
            t.cancel()
            got = wait_trace(lambda msg: msg.get("job") == jid and (
                msg.get("t") in ("done", "error") or msg.get("state") == "cancelled"), 600)
            with cond:
                last = [msg for ts, msg in trace if msg.get("job") == jid and ts <= c0 and msg.get("t") == "phase"]
                endmsg = next((msg for ts, msg in trace if ts == got), {})
            return {"phase": phase, "in": last[-1]["phase"] if last else "?",
                    "stop_to_cancelled_s": round(got - c0, 3) if got else None,
                    "ended_as": endmsg.get("state") or endmsg.get("t")}

        stops.append(stop_in("model", lambda msg: msg.get("t") == "progress" and msg.get("phase") == "model"
                             and (msg.get("frac") or 0) >= 0.3, True))
        stops.append(stop_in("vision", lambda msg: msg.get("t") == "phase" and msg.get("phase") == "vision", True))
        stops.append(stop_in("image", lambda msg: msg.get("t") == "phase" and msg.get("phase") == "image", False))
        stops.append(stop_in("answer", lambda msg: msg.get("t") == "token", False))
        t.stop()
        jid, t0 = submit("describe", ["dog-01.jpg"], "")       # the engine's stop during the model load
        at = wait_trace(lambda msg: msg.get("job") == jid and msg.get("t") == "progress"
                        and msg.get("phase") == "model" and (msg.get("frac") or 0) >= 0.3, 600)
        with t._lock:
            proc = t._proc
        c0 = time.perf_counter()
        t.stop("Stopped: NOBAD Find paused.")
        stops.append({"phase": "model (engine stop: pause / memory / runtime swap)",
                      "stop_to_exited_s": round(time.perf_counter() - c0, 3) if at else None,
                      "exitcode": getattr(proc, "exitcode", None)})
        for s in stops:
            print(json.dumps(s), flush=True)
    stop.set()
    time.sleep(0.3)
    t.stop()
    return {"model": a.model, "device": a.device, "level": a.level, "cpu_cap_percent": jobs.WORKERS.cpu_cap(),
            "eco_qos": state["eco"], "worker_in_workers_group": state["in_job"], "free_before_mb": round(free0),
            "min_free_mb": round(peak["min_free"]), "hog": bool(hogp), "floor_mb": a.floor_mb if hogp else None,
            "alloc_limit_mb": a.alloc_limit_mb or None, "assess": verdict,
            "peak_private_mb": round(peak["private"]), "peak_working_set_mb": round(peak["ws"]),
            "gpu_dedicated_mb": round(peak["ded"]), "gpu_shared_mb": round(peak["sh"]), "hang_kills": peak["hang_kills"],
            "jobs": rows, "stops": stops}


if __name__ == "__main__":
    main()
