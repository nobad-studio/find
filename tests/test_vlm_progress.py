"""Talk about a photo, release fix: the hang deadline follows real progress per phase, Stop reaches a load, the
worker's memory / I/O priority is normal only while a job runs, and the capability path of PR #16 is used when it
is there (vlm/worker.py, api.talk_assess). Fake worker messages and fake sessions; no model."""
import importlib.util
import multiprocessing
import os
import sys
import threading
import time
import types

import pytest

from nobadfind import api as api_mod, models
from nobadfind.vlm import worker

from test_vision_api import FakeSession, SMOL, PC, thread_start, _wait, _final

STALL = {p: s for p, (s, _c) in worker.PHASES.items()}


class Conn:
    def __init__(self):
        self.sent, self.closed = [], False

    def send(self, m):
        self.sent.append(m)

    def recv(self):
        time.sleep(3600)

    def close(self):
        self.closed = True


class Proc:
    pid = 4242

    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def join(self, timeout=None):
        pass

    def is_alive(self):
        return not self.terminated


def talker(now):
    """A Talker whose worker is a fake pipe: the test plays the worker's messages with `say`."""
    ev, conns = [], []

    def start():
        conns.append((Conn(), Proc()))
        return conns[-1]
    t = worker.Talker(ev.append, start=start, clock=lambda: now[0])

    def say(**msg):
        t._on(conns[-1][0], msg)
    return t, ev, conns, say


def job(jid, mid=SMOL):
    return {"job": jid, "op": "describe", "paths": ["x.jpg"], "question": "", "model": {"id": mid},
            "settings": {"need_mb": 900}, "gpu_layers": 0, "files": [1]}


# ---------- the deadline moves only on real progress of the phase the worker is in ----------
def test_load_progress_moves_the_deadline_only_when_the_fraction_increases():
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1), "SmolVLM2 500M")
    say(t="state", job=1, state="loading")
    say(t="phase", job=1, phase="model")
    assert t.work()["deadline"] == STALL["model"]
    now[0] = 50
    say(t="progress", job=1, phase="model", frac=0.10)
    assert t.work()["deadline"] == 50 + STALL["model"]                 # it grew: the deadline moves
    now[0] = 100
    say(t="progress", job=1, phase="model", frac=0.10)                 # the same fraction again ...
    say(t="progress", job=1, phase="model", frac=0.05)                 # ... or a smaller one
    assert t.work()["deadline"] == 50 + STALL["model"]                 # never moves it
    now[0] = 109
    say(t="progress", job=1, phase="model", frac=0.20)
    assert t.work()["deadline"] == 109 + STALL["model"]
    notes = [e["note"] for e in ev if e["state"] == "loading"]
    assert notes == ["Loading SmolVLM2 500M", "Loading SmolVLM2 500M… 10 %", "Loading SmolVLM2 500M… 20 %"]
    now[0] = 109 + STALL["model"] - 1
    assert t.check_deadline() is False


def test_no_progress_in_a_load_ends_the_worker_as_hung():
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="state", job=1, state="loading")
    say(t="phase", job=1, phase="model")
    say(t="progress", job=1, phase="model", frac=0.3)
    now[0] = STALL["model"] - 0.5
    assert t.check_deadline() is False
    now[0] = STALL["model"] + 0.5
    assert t.check_deadline() is True
    assert ev[-1]["state"] == "error" and ev[-1]["note"] == worker.HUNG
    assert conns[0][1].terminated and not t.state()["running"]


def test_a_flat_heartbeat_never_extends_a_load():
    """'Still computing' calls (frac None) and a repeated fraction in a load phase count for nothing."""
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="phase", job=1, phase="model")
    say(t="progress", job=1, phase="model", frac=0.5)
    for s in range(1, STALL["model"] + 1):
        now[0] = s
        say(t="progress", job=1, phase="model", frac=None)
        say(t="progress", job=1, phase="model", frac=0.5)
        say(t="phase", job=1, phase="model")                           # entering it again is no reset either
        say(t="phase", job=1, phase="prepare")                         # nor going back
    assert t.work()["deadline"] == STALL["model"]
    assert t.check_deadline() is True and ev[-1]["note"] == worker.HUNG


def test_still_computing_in_the_photo_eval_is_bounded_by_its_cap():
    now = [0.0]
    stall, cap = worker.PHASES["image"]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="state", job=1, state="answering")                            # reading the photo
    assert t.work()["phase"] == "image"
    step = stall / 2
    while now[0] + step < cap:
        now[0] += step
        say(t="progress", job=1, phase="image", frac=None)
        assert t.check_deadline() is False                              # it keeps computing: fine ...
    assert t.work()["deadline"] == cap                                  # ... but never past the cap
    now[0] = cap + 0.5
    say(t="progress", job=1, phase="image", frac=None)
    assert t.check_deadline() is True and ev[-1]["note"] == worker.HUNG


def test_load_activity_and_answer_activity_are_kept_apart():
    """Progress of another phase never counts: a load fraction while answering, a token-free answer phase."""
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="phase", job=1, phase="image")
    say(t="phase", job=1, phase="answer")
    assert t.work()["deadline"] == worker.ANSWER_S
    now[0] = 30
    say(t="progress", job=1, phase="model", frac=0.9)                   # a load's progress in the answer phase
    say(t="progress", job=1, phase="answer", frac=0.9)                  # a fraction where tokens are the progress
    say(t="progress", job=1, phase="answer", frac=None)
    assert t.work()["deadline"] == worker.ANSWER_S
    say(t="token", job=1, s="A ")                                       # a token is
    assert t.work()["deadline"] == 30 + worker.ANSWER_S


def test_a_stopped_job_keeps_its_bound_until_the_worker_says_it_ended():
    """The engine let job 1 go, but the worker is still in it: its phase's bound holds (a worker stuck there is
    still ended), the new question says "Stopping the last answer…" after a second, then gets its own bounds."""
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="phase", job=1, phase="context")                              # not stoppable
    now[0] = 10
    t.submit(job(2))
    assert ev[-1] == {"job": 1, "state": "cancelled", "text": "", "model": SMOL, "note": ""}
    assert t.work()["job"] == 1 and t.work()["deadline"] == STALL["context"]
    now[0] = 10.5
    assert t.check_deadline() is False and ev[-1]["job"] == 1
    now[0] = 11.5
    assert t.check_deadline() is False
    assert ev[-1] == {"job": 2, "state": "loading", "text": "", "model": SMOL, "note": worker.STOPPING}
    now[0] = 12
    say(t="state", job=1, state="cancelled")                            # the worker let go of job 1
    assert t.work() == {"job": 2, "phase": "start", "since": 12, "deadline": 12 + STALL["start"], "frac": -1.0,
                        "pings": 0, "last": 12}
    assert [e["job"] for e in ev].count(2) == 1                         # nothing of job 1 shown after that
    say(t="phase", job=2, phase="photo")
    assert t.work()["phase"] == "photo"


@pytest.mark.parametrize("how", ["stop", "newer smaller question"])
def test_stop_mid_load_keeps_the_memory_allowance_until_the_worker_ended_the_job(how):
    """Review I1: the worker may still be allocating the model (context: can't be stopped), so its need stays in
    the budget (talk limit, Find's total, the WORKERS commit limit) until the worker reports the job ended."""
    now = [0.0]
    budgets = []
    t, ev, conns, say = talker(now)
    t._on_budget = budgets.append
    t.submit({**job(1, "qwen3vl-2b"), "settings": {"need_mb": 3500}})
    say(t="state", job=1, state="loading")
    say(t="phase", job=1, phase="context")
    assert t.budget_mb() == 3500
    if how == "stop":
        t.cancel()
    else:
        t.submit(job(2))                                                # SmolVLM2, need 900
    assert ev[-1]["job"] == 1 and ev[-1]["state"] == "cancelled"        # the UI shows it stopped at once ...
    assert t.budget_mb() == 3500 and budgets == [3500]                  # ... the allowance stays
    say(t="state", job=1, state="cancelled")                            # the worker let go of job 1
    assert t.budget_mb() == (0 if how == "stop" else 900)
    assert budgets == [3500, 0 if how == "stop" else 900]


def test_a_worker_stuck_in_a_job_nobody_follows_is_still_ended():
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1))
    say(t="phase", job=1, phase="vision")
    t.cancel()
    now[0] = STALL["vision"] + 1
    n = len(ev)
    assert t.check_deadline() is True and conns[0][1].terminated
    assert len(ev) == n                                                 # no job to tell


def test_vision_part_notes():
    now = [0.0]
    t, ev, conns, say = talker(now)
    t.submit(job(1), "Qwen3-VL 2B")
    for m in ({"t": "phase", "phase": "vision"}, {"t": "progress", "phase": "vision", "frac": 0.4},
              {"t": "progress", "phase": "vision", "frac": 0.401}, {"t": "progress", "phase": "vision", "frac": 1.0}):
        say(job=1, **m)
    assert [e["note"] for e in ev] == ["Loading the vision part of Qwen3-VL 2B…",
                                       "Loading the vision part of Qwen3-VL 2B… 40 %",
                                       "Loading the vision part of Qwen3-VL 2B… 100 %"]


# ---------- the worker: progress messages, Stop during a load, priorities ----------
def _worker(opts, activity=None):
    a, b = multiprocessing.Pipe()
    th = threading.Thread(target=worker.serve, args=(b,), daemon=True,
                          kwargs={"open_session": lambda m, s, g, p=None: FakeSession(m, s, g, progress=p, **opts),
                                  "decode": lambda p, s: (b"\x00" * 12, 2, 2), "activity": activity})
    th.start()
    return a, th


def _until(conn, pred, timeout=10):
    got, end = [], time.monotonic() + timeout
    while time.monotonic() < end:
        if conn.poll(0.05):
            got.append(conn.recv())
            if pred(got[-1]):
                return got
    raise AssertionError(f"timed out; got {got[-5:]}")


def test_the_worker_reports_each_phase_and_only_growing_fractions():
    conn, th = _worker({"load_steps": 8, "step_s": 0.05})
    conn.send(job(1))
    got = _until(conn, lambda m: m.get("t") == "done")
    phases = [m["phase"] for m in got if m.get("t") == "phase"]
    assert phases == ["prepare", "photo", "model", "context", "vision"]
    fr = [m["frac"] for m in got if m.get("t") == "progress" and m["phase"] == "model"]
    assert fr == sorted(fr) and len(set(fr)) == len(fr) and fr[-1] == 1.0       # rate-limited, always the last
    conn.send({"op": "quit"})
    th.join(5)


@pytest.mark.parametrize("how", ["cancel", "newer question", "quit"])
def test_stop_during_a_load_aborts_it_through_the_progress_callback(how):
    FakeSession.log = []
    conn, th = _worker({"load_steps": 400, "step_s": 0.01})              # a 4 s load
    conn.send(job(1))
    _until(conn, lambda m: m.get("t") == "progress" and m["phase"] == "model")
    t0 = time.monotonic()
    conn.send({"cancel": {"op": "cancel", "job": 1}, "newer question": job(2, "qwen3vl-2b"),
               "quit": {"op": "quit"}}[how])
    if how == "quit":
        th.join(5)
        assert not th.is_alive()
    else:
        _until(conn, lambda m: m.get("t") == "state" and m.get("state") == "cancelled" and m["job"] == 1)
    took = time.monotonic() - t0
    stopped = [x for x in FakeSession.log if x[0] == "load stopped"]
    assert stopped and stopped[0][2] < 400 and took < 1.0                 # within the POLL_EVERY look, not 4 s
    if how == "newer question":
        _until(conn, lambda m: m.get("t") == "done" and m["job"] == 2)
    if th.is_alive():
        conn.send({"op": "quit"})
        th.join(5)


def test_engine_stop_during_a_load_ends_the_worker_without_terminating_it(tmp_path):
    """Talker.stop (pause, memory, runtime swap) sends the same cancel first: the load stops at its next callback
    and the worker exits by itself."""
    FakeSession.log = []
    ev, opts = [], {"load_steps": 1000, "step_s": 0.01}                 # a 10 s load
    start = thread_start(opts)
    t = worker.Talker(ev.append, start=start)
    (tmp_path / "x.jpg").write_bytes(b"jpeg")
    t.submit({**job(1), "paths": [str(tmp_path / "x.jpg")]})
    assert _wait(lambda: (t.work() or {}).get("phase") == "model" and t.work()["frac"] > 0)
    t0 = time.monotonic()
    assert t.stop("Stopped: NOBAD Find paused.") is True
    assert time.monotonic() - t0 < 2.0 and not start.procs[0].terminated
    assert _final(ev, 1)["note"] == "Stopped: NOBAD Find paused."
    assert [x for x in FakeSession.log if x[0] == "load stopped"]


def test_memory_and_io_priority_are_normal_only_while_a_job_runs():
    """Each priority change is read from a queue in the order the worker made it (review M4: no race between the
    worker's end message and its finally)."""
    import queue
    calls = queue.Queue()

    def nxt():
        return calls.get(timeout=10)
    FakeSession.log = []
    conn, th = _worker({"script": [f"t{i} " for i in range(200)], "delay": 0.005}, activity=calls.put)
    conn.send(job(1))                                   # (the pipe is read first: the worker must not block on it)
    _until(conn, lambda m: m.get("t") == "done")
    assert (nxt(), nxt()) == (True, False)                              # raised for the job, low again after it
    conn.send(job(2))
    _until(conn, lambda m: m.get("t") == "token")
    assert nxt() is True
    conn.send(job(3))                                                   # a newer question: stays raised
    _until(conn, lambda m: m.get("t") == "done" and m["job"] == 3)
    assert (nxt(), nxt()) == (True, False)                              # job 3 raises, and only its end lowers
    conn.send({**job(4), "paths": []})                                  # a refused job (an error) ...
    _until(conn, lambda m: m.get("t") == "error")
    assert (nxt(), nxt()) == (True, False)                              # ... restores it too
    conn.send(job(5))
    _until(conn, lambda m: m.get("t") == "token")
    assert nxt() is True
    conn.send({"op": "cancel", "job": 5})
    _until(conn, lambda m: m.get("state") == "cancelled")
    assert nxt() is False                                               # cancelled: low again
    conn.send({"op": "quit"})
    th.join(5)
    assert calls.empty()


def test_a_priority_windows_refuses_never_stops_a_job():
    def refuse(on):
        raise OSError("access denied")
    conn, th = _worker({}, activity=refuse)
    conn.send(job(1))
    assert _until(conn, lambda m: m.get("t") in ("done", "error"))[-1]["t"] == "done"
    conn.send({"op": "quit"})
    th.join(5)


def test_the_real_worker_uses_worker_activity(monkeypatch):
    from nobadfind import jobs, winapi
    seen = {}
    monkeypatch.setattr(jobs, "join_workers", lambda: None)
    monkeypatch.setattr(winapi, "worker_priority", lambda low=True: seen.setdefault("priority", low))
    monkeypatch.setattr(worker, "serve", lambda conn, activity=None: seen.setdefault("activity", activity))
    worker.main(Conn())
    assert seen == {"priority": True, "activity": winapi.worker_activity}


# ---------- the real worker process with the real runtime and SmolVLM2 (dev only) ----------
RUNTIME = os.environ.get("NOBAD_FIND_LLAMA_DIR")
SMOL_DIR = os.environ.get("NOBAD_FIND_SMOLVLM2_DIR")
real = pytest.mark.skipif(not (RUNTIME and SMOL_DIR and importlib.util.find_spec("PIL")),
                          reason="NOBAD_FIND_LLAMA_DIR / NOBAD_FIND_SMOLVLM2_DIR / Pillow not there (dev only)")


def _real_talker(tmp_path):
    from test_vlm_session import _drawing
    pic = tmp_path / "red.png"
    pic.write_bytes(_drawing())
    m = models.get(SMOL)
    files = {k: os.path.join(SMOL_DIR, remote) for k, (remote, _s, _h) in m["files"].items()}
    gpu = 99 if os.path.isfile(os.path.join(RUNTIME, "ggml-vulkan.dll")) else 0
    trace, ev = [], []
    t = worker.Talker(ev.append, trace=lambda msg, now: trace.append((time.perf_counter(), msg)))

    def ask(jid):
        t.submit({"job": jid, "op": "describe", "paths": [str(pic)], "question": "", "gpu_layers": gpu,
                  "model": {"id": SMOL, "model": files["model.gguf"], "mmproj": files["mmproj.gguf"],
                            "runtime": RUNTIME}, "settings": dict(m["talk"]), "files": [1]}, m["name"])
    return t, ask, trace, ev


@real
def test_real_worker_reports_real_progress_in_every_phase(tmp_path):
    t, ask, trace, ev = _real_talker(tmp_path)
    try:
        ask(1)
        assert _wait(lambda: _final(ev, 1), 180) and _final(ev, 1)["state"] == "done", ev[-3:]
    finally:
        t.stop()
    mine = [m for _ts, m in trace if m.get("job") == 1]
    phases = [m["phase"] for m in mine if m.get("t") == "phase"]
    assert phases == ["prepare", "photo", "model", "context", "vision", "image", "answer"]
    for p in ("model", "vision"):                                         # llama's and mtmd's own fractions
        fr = [m["frac"] for m in mine if m.get("t") == "progress" and m["phase"] == p]
        assert fr and fr == sorted(fr) and fr[-1] == 1.0, (p, fr)          # SmolVLM2 loads in ~0.3 s: maybe one
    assert any(e["note"].endswith(" %") for e in ev if e["state"] == "loading")


@real
@pytest.mark.parametrize("phase", ["model", "image"])
def test_real_stop_reaches_the_load_and_the_photo_eval(tmp_path, phase):
    t, ask, trace, ev = _real_talker(tmp_path)
    try:
        if phase == "image":                                              # loaded first
            ask(1)
            assert _wait(lambda: _final(ev, 1), 180)
        ask(2)
        at = (lambda m: m.get("t") == "progress" and m["phase"] == "model" and m["frac"] >= 0.2) \
            if phase == "model" else (lambda m: m.get("t") == "phase" and m["phase"] == "image")
        assert _wait(lambda: any(m.get("job") == 2 and at(m) for _ts, m in trace), 180)
        c0 = time.perf_counter()
        t.cancel()
        assert _wait(lambda: any(m.get("job") == 2 and m.get("state") == "cancelled" for _ts, m in trace), 30)
        took = next(ts for ts, m in trace if m.get("job") == 2 and m.get("state") == "cancelled") - c0
        assert took < 2.0, took
        assert not [m for _ts, m in trace if m.get("job") == 2 and m.get("t") == "token"]
        assert t.state()["loaded"] == ("" if phase == "model" else SMOL)  # a stopped load leaves nothing loaded
    finally:
        t.stop()


# ---------- PR #16: the capability path is used as soon as nobadfind.capability exists ----------
def test_talk_assess_uses_capability_assess_when_the_module_is_there(monkeypatch):
    """Until PR #16 merges, talk_assess falls back to models.capable + free RAM (temporary). With a capability
    module that has assess(), only assess() decides, and the fallback is not called."""
    calls = []
    fake = types.ModuleType("nobadfind.capability")

    def assess(sample, hardware, measured=None, catalog=None):
        calls.append((sample, hardware, [m["id"] for m in catalog]))
        return {"can_run": {m["id"]: False for m in catalog}, "why": {m["id"]: "Not now: assess says so"
                                                                     for m in catalog}, "device": {}, "budget": {}}
    fake.assess = assess
    monkeypatch.setitem(sys.modules, "nobadfind.capability", fake)
    import nobadfind
    monkeypatch.setattr(nobadfind, "capability", fake, raising=False)

    def fallback(*a, **k):
        raise AssertionError("the free-RAM fallback ran although capability.assess exists")
    monkeypatch.setattr(models, "capable", fallback)
    monkeypatch.setattr(api_mod, "talk_fits", fallback)
    qwen = models.get("qwen3vl-2b")
    sample = object()
    assert api_mod.talk_assess(qwen, sample, dict(PC)) == (False, "Not now: assess says so")
    assert calls == [(sample, dict(PC), ["qwen3vl-2b"])]


def test_without_the_capability_module_the_fallback_decides(monkeypatch):
    monkeypatch.setitem(sys.modules, "nobadfind.capability", None)      # import fails, as on this branch
    seen = []
    monkeypatch.setattr(models, "capable", lambda m, pc: seen.append("capable") or (True, ""))
    monkeypatch.setattr(api_mod, "talk_fits", lambda m, s: seen.append("fits") or (True, ""))
    assert api_mod.talk_assess(models.get("qwen3vl-2b"), None, dict(PC)) == (True, "")
    assert seen == ["capable", "fits"]
