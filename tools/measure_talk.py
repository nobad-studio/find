"""Talk about a photo: how long Describe / Ask / Compare take through the real talk worker (dev only, not shipped).

    python tools/measure_talk.py --model smolvlm2-500m --model-dir <folder with the model's two .gguf files>
        --runtime-dir <unpacked llama.cpp runtime> --device cpu|vulkan --images <folder> --level full|gentle|light
        --out <result.json>

The worker is the app's own (vlm.worker.Talker, a spawned talk worker process) and it runs under the same limits
as in the app: this script sets up Find's process groups (jobs.setup, so the worker joins its own WORKERS group,
never a running Find's), gives the group the governor's CPU hard cap for --level (governor.CPU_CAP: Full none,
Gentle 35 %, Light 15 %), puts the worker in efficiency mode (EcoQoS) at Light like governor._eco_workers, and
raises the group's memory limit by the model's measured need (jobs.set_talk_allowance). The worker sets its own
idle CPU priority (winapi.worker_priority). Nothing else from Find runs in the group, so the cap is the talk
worker's alone (in the app, indexing workers would share it).

One fresh worker per run. Jobs in order: Describe dog-01 (cold: start + load + answer), Ask "What's written here?"
on sign-01, Compare dog-01 with dog-02, Describe cat-01 (warm). For each: time to the first word (submit -> first
non-empty "answering" text), total, and the longest wait between two pieces of the answer (the app ends a worker
with no progress for vlm.worker.LOAD_S / ANSWER_S). Also the worker's peak private memory and working set, and its
graphics memory (PDH "GPU Process Memory" counters). Refuses to start when less than the model's need plus
--margin-mb of memory is free (default 1024).

Needs psutil and pywin32 (win32pdh), both in the dev environment. Results: docs/measurements.md.
"""
import argparse
import json
import os
import sys
import threading
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)

JOBS = [("describe", ["dog-01.jpg"], ""), ("ask", ["sign-01.jpg"], "What's written here?"),
        ("compare", ["dog-01.jpg", "dog-02.jpg"], ""), ("describe", ["cat-01.jpg"], "")]


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="talk model id (models.talk_models)")
    ap.add_argument("--model-dir", required=True, help="folder with the model's two .gguf files (catalog names)")
    ap.add_argument("--runtime-dir", required=True, help="unpacked llama.cpp runtime folder")
    ap.add_argument("--device", choices=("cpu", "vulkan"), required=True)
    ap.add_argument("--images", required=True, help="folder with dog-01.jpg, dog-02.jpg, sign-01.jpg, cat-01.jpg")
    ap.add_argument("--level", choices=("full", "gentle", "light"), required=True)
    ap.add_argument("--out", required=True, help="where the JSON result goes")
    ap.add_argument("--margin-mb", type=int, default=1024, help="free memory to keep beside the model's need")
    a = ap.parse_args(argv)

    import psutil
    from nobadfind import governor, jobs, models, winapi
    from nobadfind.vlm import worker

    m = models.get(a.model)
    if not m or m.get("feature") != "talk":
        sys.exit(f"not a talk model: {a.model}")
    rid = "llama-vulkan" if a.device == "vulkan" else "llama-cpu"
    need = models.talk_need_mb(m, rid)
    free0 = psutil.virtual_memory().available / 1048576
    if free0 < need + a.margin_mb:
        sys.exit(f"only {free0:.0f} MB free; {a.model} on {a.device} needs {need} MB + {a.margin_mb} MB margin")

    jobs.setup()                                          # OUTER + this run's own WORKERS group (memory limit)
    cap = governor.CPU_CAP[a.level]
    if cap is not None and not jobs.WORKERS.set_cpu_cap(cap):    # Full: no cap (a new group has none)
        sys.exit("could not set the worker group's CPU cap")
    if jobs.WORKERS.cpu_cap() != cap:
        sys.exit(f"the worker group's CPU cap is {jobs.WORKERS.cpu_cap()}, not {cap}")
    eco = a.level in governor.ECO_LEVELS

    names = {k: v[0] for k, v in m["files"].items()}
    model = {"id": a.model, "model": os.path.join(a.model_dir, names["model.gguf"]),
             "mmproj": os.path.join(a.model_dir, names["mmproj.gguf"]), "runtime": a.runtime_dir}
    settings = dict(m["talk"])
    settings["need_mb"] = need or None                    # as Api._vision_job
    events, cond = [], threading.Condition()

    def emit(ev):
        with cond:
            events.append((time.perf_counter(), dict(ev)))
            cond.notify_all()

    t = worker.Talker(emit, on_budget=jobs.set_talk_allowance)
    peak = {"ded": 0.0, "sh": 0.0, "ws": 0.0}
    seen = {"in_job": False, "eco": False}
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            pid = next(iter(t.pids()), None)
            if pid:
                inside = pid in jobs.WORKERS.pids()
                seen["in_job"] = seen["in_job"] or inside
                if eco and inside and not seen["eco"]:        # the governor sets it once per worker (its tick)
                    seen["eco"] = bool(winapi.eco_qos(True, pid=pid, job=jobs.WORKERS.handle))
                try:
                    peak["ws"] = max(peak["ws"], psutil.Process(pid).memory_info().rss / 1048576)
                    d, s = gpu_mem(pid)
                    peak["ded"], peak["sh"] = max(peak["ded"], d), max(peak["sh"], s)
                except Exception:
                    pass
            time.sleep(0.25)
    threading.Thread(target=sampler, daemon=True).start()

    rows = []
    for op, imgs, q in JOBS:
        jid = t.next_id()
        job = {"job": jid, "op": op, "paths": [os.path.join(a.images, i) for i in imgs], "question": q,
               "model": model, "settings": settings, "gpu_layers": 99 if a.device == "vulkan" else 0, "files": [1]}
        t0 = time.perf_counter()
        t.submit(job, m["name"])
        with cond:
            while True:
                done = [e for e in events if e[1]["job"] == jid and e[1]["state"] in ("done", "error", "cancelled")]
                if done or time.perf_counter() - t0 > 900:
                    break
                cond.wait(1)
            mine = [(ts, e) for ts, e in events if e["job"] == jid]
        words = [ts for ts, e in mine if e["state"] == "answering" and e["text"].strip()]
        end = done[0] if done else (time.perf_counter(), {"state": "timeout", "text": "", "note": ""})
        marks = [t0] + [ts for ts, _e in mine] + [end[0]]
        rows.append({"op": op, "images": imgs, "question": q, "state": end[1]["state"],
                     "first_word_s": round(words[0] - t0, 2) if words else None, "total_s": round(end[0] - t0, 2),
                     "longest_wait_s": round(max(b - x for x, b in zip(marks, marks[1:])), 2),
                     "text": end[1].get("text", "")[:300], "note": end[1].get("note", "")})
        print(json.dumps(rows[-1], ensure_ascii=True), flush=True)
    pid = next(iter(t.pids()), None)
    peak_private = psutil.Process(pid).memory_info().peak_pagefile / 1048576 if pid else 0
    stop.set()
    time.sleep(0.3)
    t.stop()
    res = {"model": a.model, "device": a.device, "level": a.level, "cpu_cap_percent": jobs.WORKERS.cpu_cap(),
           "eco_qos": seen["eco"], "worker_in_workers_group": seen["in_job"], "free_before_mb": round(free0),
           "peak_private_mb": round(peak_private), "peak_working_set_mb": round(peak["ws"]),
           "gpu_dedicated_mb": round(peak["ded"]), "gpu_shared_mb": round(peak["sh"]), "jobs": rows}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in res.items() if k != "jobs"}), flush=True)


if __name__ == "__main__":
    main()
