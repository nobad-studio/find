"""Talk about a photo: the vision worker (vlm/worker.py) and the Api's vision_* methods.

The worker's real loop (`serve`) runs on a thread with a fake session and a fake decoder; one real test runs the
worker process with SmolVLM2 (dev only: NOBAD_FIND_LLAMA_DIR, NOBAD_FIND_SMOLVLM2_DIR).
"""
import importlib.util
import multiprocessing
import os
import subprocess
import sys
import threading
import time

import pytest

from nobadfind import api as api_mod, embed, models, search
from nobadfind.governor import Decision
from nobadfind.store import KEPT_ORD
from nobadfind.vlm import worker
from nobadfind.vlm.session import AllocFailed

from test_api_status import make

PC = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "avx512_vnni": False, "gpu": "", "vram_gb": 0.0,
      "directml": False, "disk_free_gb": 200.0, "ssd": True}
SMOL, QWEN = "smolvlm2-500m", "qwen3vl-2b"
IMG = (b"\x00" * 12, 2, 2)


class FakeSession:
    """Stands in for vlm.session.Session. `script` is the answer's tokens; `fail_after` raises AllocFailed then."""
    log = []

    def __init__(self, model, settings, gpu_layers, script=("A ", "red ", "circle."), delay=0.0, fail_after=None,
                 hang=None):
        if hang is not None:
            hang.wait(30)                       # a driver stall while loading (I3)
        self.model, self.settings, self.gpu_layers = model, settings, gpu_layers
        self.script, self.delay, self.fail_after = list(script), delay, fail_after
        FakeSession.log.append(("load", model["id"], dict(settings), gpu_layers))

    def answer(self, images, prompt, max_tokens, on_token, cancelled):
        FakeSession.log.append(("answer", len(images), prompt))
        out = []
        for i, t in enumerate(self.script):
            if cancelled():
                break
            if self.fail_after is not None and i == self.fail_after:
                raise AllocFailed(self.settings.get("need_mb") or 1, "answer")
            out.append(t)
            on_token(t)
            time.sleep(self.delay)
        return "".join(out).strip()

    def close(self):
        FakeSession.log.append(("close", self.model["id"]))


class ThreadProc:
    def __init__(self, t, pid=0):
        self._t, self.pid = t, pid
        self.terminated = False

    def is_alive(self):
        return self._t.is_alive()

    def join(self, timeout=None):
        self._t.join(timeout)

    def terminate(self):
        self.terminated = True


def thread_start(opts, decode=None, pid=0):
    """A Talker start() that runs the real worker loop on a thread (opts: FakeSession keyword arguments, read at
    each load, so a test can change them between jobs)."""
    started = []

    def fake_decode(path, side):
        return IMG if os.path.isfile(path) else worker.GONE

    def start():
        a, b = multiprocessing.Pipe()
        t = threading.Thread(target=worker.serve, args=(b,), daemon=True,
                             kwargs={"open_session": lambda m, s, g: FakeSession(m, s, g, **opts),
                                     "decode": decode or fake_decode})
        t.start()
        started.append(t)
        start.procs.append(ThreadProc(t, pid))
        return a, start.procs[-1]
    start.started, start.procs = started, []
    return start


def _names(mid):
    """{file name on disk: pinned size} of a talk model or runtime."""
    m = models.get(mid)
    return ({n: size for n, (size, _s) in m["files_in_zip"].items()} if m["feature"] == "runtime"
            else {n: size for n, (_p, size, _s) in m["files"].items()})


def _put_files(d, mid):
    """One-byte stand-ins (the real sizes would put gigabytes on the disk; _fake_sizes counts them as pinned)."""
    root = models.model_dir(mid, d)
    os.makedirs(root, exist_ok=True)
    for name in _names(mid):
        with open(os.path.join(root, name), "wb") as f:
            f.write(b"x")


def _fake_sizes(monkeypatch):
    def there(mid, d):
        return {n: size for n, size in _names(mid).items() if os.path.isfile(os.path.join(models.model_dir(mid, d), n))}

    def ready(mid, data_dir=models.DATA_DIR):
        return models.get(mid) is not None and len(there(mid, data_dir)) == len(_names(mid))

    def missing_mb(mid, data_dir=models.DATA_DIR):
        if ready(mid, data_dir):
            return 0
        if models.get(mid)["feature"] == "runtime":
            return round(models.size_mb(models.get(mid)))
        have = there(mid, data_dir)
        return round(sum(size for n, size in _names(mid).items() if n not in have) / 1048576)
    monkeypatch.setattr(models, "ready", ready)
    monkeypatch.setattr(models, "missing_mb", missing_mb)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod.hw, "scan", lambda: dict(PC))
    monkeypatch.setattr(api_mod.winapi, "memory_status", lambda: (40, 8000))
    _fake_sizes(monkeypatch)
    a, s = make(tmp_path)
    data = str(tmp_path / "data")
    a._models_dir = data
    for mid in (SMOL, QWEN, "llama-cpu"):
        _put_files(data, mid)
    pics = tmp_path / "pics"
    pics.mkdir()
    rows = []
    for name in ("sea.jpg", "dog.jpg", "sign.jpg"):
        (pics / name).write_bytes(b"jpeg")
        rows.append((str(pics / name), name, str(pics), ".jpg", "image", 4, 5.0, 5.0, 1))
    rows.append((str(pics / "notes.txt"), "notes.txt", str(pics), ".txt", "document", 4, 5.0, 5.0, 1))
    (pics / "notes.txt").write_bytes(b"text")
    s.upsert_files(rows)
    ids = {n: s.one("SELECT id FROM files WHERE name=?", (n,)) for n in ("sea.jpg", "dog.jpg", "sign.jpg",
                                                                         "notes.txt")}
    events, opts = [], {}
    start = thread_start(opts)
    a._talk = worker.Talker(events.append, start=start)
    FakeSession.log = []
    box = {"a": a, "s": s, "ids": ids, "events": events, "opts": opts, "start": start, "data": data, "pics": pics}
    yield box
    a.vision_stop()
    s.close()


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return False


def _final(events, job):
    got = [e for e in events if e["job"] == job and e["state"] in ("done", "error", "cancelled")]
    return got[-1] if got else None


# ---------- refusals ----------
def test_vision_ask_missing_file(env):
    a, ids = env["a"], env["ids"]
    assert a.vision_ask(99999, "what is it?") == {"ok": False, "error": "This photo is no longer there.", "job": 0}
    assert a.vision_describe("7")["error"] == "This photo is no longer there."
    os.remove(env["pics"] / "sea.jpg")                       # indexed, then deleted
    assert a.vision_describe(ids["sea.jpg"])["error"] == "This photo is no longer there."
    assert env["start"].started == []                        # no worker for a refusal


def test_photo_gone_between_the_ask_and_the_worker(env):
    a, ids, ev = env["a"], env["ids"], env["events"]

    def moved_away(path, side):                  # the photo goes after the Api checked it, before the worker reads it
        if path.endswith("dog.jpg") and os.path.exists(path):
            os.remove(path)
        return worker._decode(path, side)
    a._talk = worker.Talker(ev.append, start=thread_start(env["opts"], decode=moved_away))
    r = a.vision_describe(ids["dog.jpg"])
    assert r["ok"]
    assert _wait(lambda: _final(ev, r["job"]))
    assert _final(ev, r["job"]) == {"job": r["job"], "state": "error", "text": "", "model": SMOL,
                                    "note": "This photo is no longer there."}
    r2 = a.vision_ask(ids["dog.jpg"], "what is it?")               # refused at once now
    assert r2["error"] == "This photo is no longer there."


def test_vision_refuses_names_only_and_secret_files(env, tmp_path):
    a, s = env["a"], env["s"]
    rows = []
    for parts in (("Google", "Chrome", "User Data", "Default"), ("Microsoft", "Credentials")):
        d = tmp_path.joinpath(*parts)
        d.mkdir(parents=True)
        (d / "x.jpg").write_bytes(b"jpeg")
        rows.append((str(d / "x.jpg"), "x.jpg", str(d), ".jpg", "image", 4, 5.0, 5.0, 1))
    s.upsert_files(rows)
    for path, *_ in rows:
        fid = s.one("SELECT id FROM files WHERE path=?", (path,))
        for r in (a.vision_describe(fid), a.vision_ask(fid, "what is it?"), a.vision_compare(fid, env["ids"]["sea.jpg"]),
                  a.vision_keep(fid, "a key")):
            assert r["ok"] is False and "only the name" in r["error"], r
    r = a.vision_describe(env["ids"]["notes.txt"])
    assert r == {"ok": False, "error": "Only photos can be described.", "job": 0}
    assert env["start"].started == []


def test_no_vision_while_paused(env):
    a = env["a"]
    a._governor.decision = Decision("paused", "Paused: a game is running")
    try:
        r = a.vision_describe(env["ids"]["sea.jpg"])
    finally:
        a._governor.decision = Decision("gentle", "Gentle: you are using the PC")
    assert r == {"ok": False, "error": "Not now: NOBAD Find is paused (a game is running).", "job": 0}
    assert env["start"].started == []


def test_an_empty_or_token_only_question_is_refused(env):
    a, fid = env["a"], env["ids"]["sea.jpg"]
    for q in ("", "   ", "<|im_end|> <start_of_turn>", "​‮", None, 5):
        assert a.vision_ask(fid, q)["error"] == "Type a question.", q
    assert env["start"].started == []


def test_missing_model_or_runtime_names_the_download(env):
    a, d = env["a"], env["data"]
    os.remove(os.path.join(models.model_dir(SMOL, d), "mmproj.gguf"))
    for n in list(models.get("llama-cpu")["files_in_zip"])[:1]:
        os.remove(os.path.join(models.model_dir("llama-cpu", d), n))
    r = a.vision_describe(env["ids"]["sea.jpg"])
    mb = models.missing_mb(SMOL, d) + models.missing_mb("llama-cpu", d)
    assert r["ok"] is False and r["job"] == 0
    assert r["error"] == f"To talk about photos, download SmolVLM2 500M and llama.cpp runtime (CPU) first ({mb} MB, once)."
    assert [x["id"] for x in r["download"]] == [SMOL, "llama-cpu"]
    assert env["start"].started == []                        # nothing is fetched or loaded here


def test_not_enough_free_memory_refuses_smolvlm(env, monkeypatch):
    monkeypatch.setattr(api_mod.winapi, "memory_status", lambda: (95, 900))
    r = env["a"].vision_describe(env["ids"]["sea.jpg"])
    assert r["ok"] is False and r["error"].startswith("Not now: only 0.9 GB free, SmolVLM2 needs about 1.0 GB")


def test_compare_needs_two_different_photos(env):
    a, ids = env["a"], env["ids"]
    assert a.vision_compare(ids["sea.jpg"], ids["sea.jpg"])["ok"] is False


def test_the_worker_refuses_more_than_two_pictures():
    a, b = multiprocessing.Pipe()
    t = threading.Thread(target=worker.serve, args=(b,), daemon=True,
                         kwargs={"open_session": lambda m, s, g: FakeSession(m, s, g), "decode": lambda p, s: IMG})
    t.start()
    a.send({"op": "compare", "job": 1, "paths": ["x", "y", "z"], "question": "", "model": {"id": SMOL},
            "settings": {}, "gpu_layers": 0})
    assert a.recv()["t"] == "error"
    a.send({"op": "quit"})
    t.join(5)
    assert not t.is_alive()


# ---------- answers ----------
def test_describe_streams_then_done(env):
    a, ev = env["a"], env["events"]
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert r["ok"] and r["error"] == "" and r["job"] >= 1
    assert _wait(lambda: _final(ev, r["job"]))
    mine = [e for e in ev if e["job"] == r["job"]]
    assert [e["state"] for e in mine] == ["loading", "answering", "answering", "answering", "answering", "done"]
    assert mine[0]["note"] == "Loading SmolVLM2 500M" and all(e["model"] == SMOL for e in mine)
    assert [e["text"] for e in mine[1:]] == ["", "A ", "A red ", "A red circle.", "A red circle."]
    load = [x for x in FakeSession.log if x[0] == "load"]
    assert load == [("load", SMOL, {**models.get(SMOL)["talk"], "need_mb": models.get(SMOL)["ram_mb"]}, 0)]
    st = a.vision_state()
    assert st["loaded"] == SMOL and st["busy"] is False and st["running"] is True


def test_vision_state_sends_the_measured_timing_of_the_runtime_in_use(env):
    """The UI's "about N s" comes from the catalog's measured figures for the runtime a question would use, at the
    governor's level now (I1: the talk worker runs under the worker group's CPU cap)."""
    a = env["a"]

    def state(level):
        a._governor.decision = Decision(level, level)
        try:
            return {m["id"]: m for m in a.vision_state()["models"]}
        finally:
            a._governor.decision = Decision("gentle", "Gentle: you are using the PC")
    assert a.vision_state()["runtime"]["id"] == "llama-cpu"
    st = state("full")
    assert st[QWEN]["load_s"] == 12 and st[QWEN]["answer_s"] == [4, 22]          # measured on the CPU, Full
    assert st[SMOL]["load_s"] == 3 and st[SMOL]["answer_s"] == [3, 11]
    assert st[QWEN]["slow_note"] == st[SMOL]["slow_note"] == ""
    st = state("light")                                                           # 15 % cap + efficiency mode
    assert st[QWEN]["answer_s"] == [7, 32] and st[SMOL]["answer_s"] == [5, 15]
    assert st[QWEN]["slow_note"] == st[SMOL]["slow_note"] == "Slower now: NOBAD Find is in Very light mode."
    st = state("gentle")
    assert st[SMOL]["answer_s"] == [3, 11] and st[SMOL]["slow_note"] == ""
    _put_files(env["data"], "llama-vulkan")
    st = state("full")
    assert st[QWEN]["load_s"] == 13 and st[QWEN]["answer_s"] == [1, 12]         # measured on Vulkan (Iris Xe)
    assert st[SMOL]["load_s"] == 1 and st[SMOL]["answer_s"] == [1, 3]
    st = state("light")
    assert st[SMOL]["answer_s"] == [1, 3] and st[SMOL]["slow_note"] == ""     # the graphics do the work: no note
    assert st[QWEN]["slow_note"] == ""


@pytest.mark.parametrize("vram_gb", [0.1, 8.0])        # Iris Xe (shared) and a graphics card: the same need
def test_vulkan_runtime_passes_the_bigger_need_and_layers(env, monkeypatch, vram_gb):
    """On Vulkan the need is max(ram_mb, vram_mb) on every graphics card (measured: Qwen on Vulkan / Iris Xe
    committed more system RAM than its graphics memory; shared and dedicated memory can't be told apart)."""
    _put_files(env["data"], "llama-vulkan")
    monkeypatch.setattr(api_mod.hw, "scan", lambda: {**PC, "gpu": "A graphics card", "vram_gb": vram_gb})
    r = env["a"].vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(env["events"], r["job"]))
    (_, mid, settings, gpu) = [x for x in FakeSession.log if x[0] == "load"][0]
    m = models.get(SMOL)
    assert settings["need_mb"] == max(m["ram_mb"], m["vram_mb"]) and gpu == 99


def test_new_ask_cancels_old_stream(env):
    a, ev, ids = env["a"], env["events"], env["ids"]
    env["opts"].update(script=[f"t{i} " for i in range(400)], delay=0.005)
    r1 = a.vision_ask(ids["sea.jpg"], "what is happening?")
    assert _wait(lambda: any(e["job"] == r1["job"] and e["text"] for e in ev))
    r2 = a.vision_ask(ids["dog.jpg"], "what animal?")
    at = len(ev)
    assert _wait(lambda: _final(ev, r2["job"]), 10)
    after = ev[at:]
    assert not [e for e in after if e["job"] == r1["job"]]                    # nothing of job 1 once job 2 started
    assert _final(ev, r1["job"])["state"] == "cancelled"
    assert _final(ev, r2["job"])["state"] == "done"
    assert [x[2] for x in FakeSession.log if x[0] == "answer"][-1].endswith("Question: what animal?")
    assert [x[0] for x in FakeSession.log].count("load") == 1               # the model stayed loaded


def test_cancel_stops_the_stream_and_keeps_the_model(env):
    a, ev = env["a"], env["events"]
    env["opts"].update(script=[f"t{i} " for i in range(400)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    assert a.vision_cancel() == {"ok": True, "error": "", "job": None}
    n = len(ev)
    assert ev[-1] == {"job": r["job"], "state": "cancelled", "text": "", "model": SMOL, "note": ""}
    time.sleep(0.1)
    assert len(ev) == n                                                      # no late tokens
    assert _wait(lambda: not a.vision_state()["busy"]) and a.vision_state()["loaded"] == SMOL


def test_out_of_memory_mid_answer_is_an_error_and_the_next_job_works(env):
    a, ev = env["a"], env["events"]
    env["opts"].update(fail_after=2)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"]))
    assert any(e["job"] == r["job"] and e["text"] == "A red " for e in ev)        # tokens were streamed ...
    end = _final(ev, r["job"])
    assert end["state"] == "error" and end["text"] == ""                          # ... and the answer failed
    assert end["note"] == ("Not enough memory right now (needs about 1.0 GB). Close something or try again "
                           "later.")
    assert ("close", SMOL) in FakeSession.log                                     # unloaded
    env["opts"].update(fail_after=None)
    r2 = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r2["job"])) and _final(ev, r2["job"])["state"] == "done"
    assert [x[0] for x in FakeSession.log].count("load") == 2                   # loaded again, once


def test_deeper_needs_capability(env, monkeypatch):
    a, ev = env["a"], env["events"]
    monkeypatch.setattr(api_mod, "talk_assess",
                        lambda m, sample, pc: (False, "Not now: only 3.0 GB free, Qwen3-VL needs about 2.4 GB plus margin"))
    r = a.vision_ask(env["ids"]["sea.jpg"], "what is the mood here?", deeper=True)
    assert r == {"ok": False, "error": "Not now: only 3.0 GB free, Qwen3-VL needs about 2.4 GB plus margin", "job": 0}
    assert not [x for x in FakeSession.log if x[0] == "load"] and env["start"].started == []
    monkeypatch.setattr(api_mod, "talk_assess", lambda m, sample, pc: (True, ""))
    r1 = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r1["job"]))
    r2 = a.vision_ask(env["ids"]["sea.jpg"], "what is the mood here?", deeper=True)
    assert _wait(lambda: _final(ev, r2["job"])) and _final(ev, r2["job"])["model"] == QWEN
    seq = [(x[0], x[1]) for x in FakeSession.log if x[0] in ("load", "close")]
    assert seq == [("load", SMOL), ("close", SMOL), ("load", QWEN)]             # the other model leaves first


def test_the_fallback_assessment_checks_the_pc_and_free_memory(monkeypatch):
    qwen = models.get(QWEN)
    small_pc = dict(PC, ram_gb=7.8, cores=4)
    ok, why = api_mod.talk_assess(qwen, None, small_pc)
    assert not ok and "16 GB" in why
    sample = type("S", (), {"free_mb": 3072})()
    ok, why = api_mod.talk_assess(qwen, sample, PC)
    assert not ok and why == "Not now: only 3.0 GB free, Qwen3-VL needs about 2.4 GB plus margin"
    sample.free_mb = 6000
    assert api_mod.talk_assess(qwen, sample, PC) == (True, "")


def test_text_question_shows_stored_ocr_first(env):
    a, s, ev, fid = env["a"], env["s"], env["events"], env["ids"]["sign.jpg"]
    s.set_text(fid, 5.0, ["OPEN 9 TO 5", "MON-SAT"])
    r = a.vision_ask(fid, "what does the sign say?")
    assert r["ok"] and r["job"]
    assert ev[-1] == {"job": r["job"], "state": "done", "text": "OPEN 9 TO 5\nMON-SAT", "model": "",
                      "note": "Text read from the photo"}
    assert env["start"].started == []                                       # the model wasn't asked
    r2 = a.vision_ask(fid, "what does the sign say?", more=True)              # "ask the model too"
    assert _wait(lambda: _final(ev, r2["job"])) and _final(ev, r2["job"])["model"] == SMOL
    s.upsert_files([(s.one("SELECT path FROM files WHERE id=?", (fid,)), "sign.jpg", str(env["pics"]), ".jpg",
                     "image", 4, 9.0, 9.0, 1)])                            # the photo changed: its OCR is stale
    r3 = a.vision_ask(fid, "what does the sign say?")
    assert _wait(lambda: _final(ev, r3["job"])) and _final(ev, r3["job"])["model"] == SMOL


def test_keep_stores_vdesc_and_it_goes_with_the_file(env):
    a, s, ev, fid = env["a"], env["s"], env["events"], env["ids"]["sea.jpg"]
    r = a.vision_describe(fid)
    assert _wait(lambda: _final(ev, r["job"]))
    assert a.vision_keep(fid, "A red circle.") == {"ok": True, "error": "", "kept": True}
    kept = s.kept_description(fid)
    assert kept["text"] == "A red circle." and kept["model"] == SMOL and kept["at"] > 0
    assert s.q("SELECT body FROM chunks WHERE file_id=? AND ord=?", (fid, KEPT_ORD)) == [("A red circle.",)]
    s.set_text(fid, 5.0, ["SEA VIEW"])                                       # read again: OCR replaced, kept stays
    assert sorted(r[0] for r in s.q("SELECT body FROM chunks WHERE file_id=?", (fid,))) == ["A red circle.", "SEA VIEW"]
    assert s.read_text(fid) == "SEA VIEW"
    assert a.vision_keep(fid, "my own words\x00‮ here")["ok"]            # edited by the user: no model
    assert s.kept_description(fid) == {"text": "my own words here", "model": "", "at": s.kept_description(fid)["at"]}
    path = s.one("SELECT path FROM files WHERE id=?", (fid,))
    s.remove_paths([path])
    assert s.kept_description(fid) is None
    assert s.q("SELECT count(*) FROM chunks WHERE file_id=?", (fid,)) == [(0,)]
    assert a.vision_keep(fid, "x")["error"] == "This photo is no longer there."


def test_keep_with_empty_text_forgets(env):
    a, s, fid = env["a"], env["s"], env["ids"]["dog.jpg"]
    a.vision_keep(fid, "a brown dog")
    assert a.vision_keep(fid, "  ") == {"ok": True, "error": "", "kept": False}
    assert s.kept_description(fid) is None and s.q("SELECT count(*) FROM chunks WHERE file_id=?", (fid,)) == [(0,)]


def test_kept_description_is_searchable_and_labelled(env):
    a, s, ids = env["a"], env["s"], env["ids"]
    a.vision_keep(ids["dog.jpg"], "A lighthouse on a rocky shore at sunset.")
    s.set_text(ids["sign.jpg"], 5.0, ["LIGHTHOUSE TOURS"])                    # OCR of another photo
    out = {r["id"]: r for r in search.search(s, "lighthouse")["results"]}
    assert search.KEPT_MATCH in out[ids["dog.jpg"]]["why"]
    assert "text inside matches" not in out[ids["dog.jpg"]]["why"]
    assert "text inside matches" in out[ids["sign.jpg"]]["why"]
    assert search.KEPT_MATCH not in out[ids["sign.jpg"]]["why"]
    assert s.wipe() is None and s.q("SELECT count(*) FROM vdesc") == [(0,)]


# ---------- the worker's lifetime ----------
def test_idle_release_stops_the_worker(env):
    a, ev = env["a"], env["events"]
    now = [0.0]
    a._talk = worker.Talker(ev.append, start=env["start"], clock=lambda: now[0])
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"]))
    now[0] = worker.IDLE - 1
    assert a.vision_release_idle() is False and a.vision_state()["running"]
    now[0] = worker.IDLE + 1
    assert a.vision_release_idle() is True
    assert not a.vision_state()["running"] and a.vision_state()["loaded"] == ""
    assert _wait(lambda: not env["start"].started[-1].is_alive()) and ("close", SMOL) in FakeSession.log
    r = a.vision_describe(env["ids"]["sea.jpg"])                            # the next question starts it again
    assert _wait(lambda: _final(ev, r["job"])) and _final(ev, r["job"])["state"] == "done"
    assert len(env["start"].started) == 2


def test_idle_is_the_lazy_models_idle():
    assert worker.IDLE == embed.Lazy.IDLE


def _hook_parts(order):
    class Ix:
        def release_models(self):
            order.append("indexer release")

        def release_idle_models(self):
            order.append("indexer idle")

        def recycle_workers(self):
            order.append("indexer recycle")

        def worker_names(self):
            return {7: "text reader"}
    return Ix()


def test_worker_hooks_reach_the_talk_worker_first(env):
    from nobadfind import engine
    a, ev = env["a"], env["events"]
    order = []
    hooks = engine.worker_hooks({"indexer": _hook_parts(order), "api": a})
    real_tick = a.vision_tick
    a.vision_tick = lambda: order.append("talk tick") or real_tick()
    hooks["release_idle"]()
    assert order == ["talk tick", "indexer idle"]                        # the talk worker first (I2)

    def boom():
        raise RuntimeError("x")
    a.vision_tick = boom
    order.clear()
    hooks["release_idle"]()
    assert order == ["indexer idle"]                                     # one failing never skips the other
    a.vision_tick = real_tick
    env["opts"].update(script=[f"t{i} " for i in range(400)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    assert hooks["names"]() == {7: "text reader"}           # a thread worker has no pid
    assert hooks["talk_mb"]() == models.get(SMOL)["ram_mb"]
    assert hooks["release_talk"]() is True
    assert _final(ev, r["job"]) == {"job": r["job"], "state": "cancelled", "text": "", "model": SMOL,
                                    "note": "Stopped: NOBAD Find needed the memory."}
    assert not a.vision_state()["running"] and hooks["talk_mb"]() == 0


def _watchdog(a, mb, job_mb, order, keep=False, start=None):
    from nobadfind import engine
    from nobadfind.activity import Activity
    from nobadfind.watchdog import Watchdog
    hooks = engine.worker_hooks({"indexer": _hook_parts(order), "api": a})
    kills = []
    w = Watchdog(Activity(), kill=kills.append, info=lambda pid: {"memory_mb": mb[pid]}, pids=lambda: list(mb),
                 job_usage=lambda: {"memory_mb": job_mb[0]}, keep_models=lambda: keep,
                 **{k: hooks[k] for k in ("release", "recycle", "names", "talk_mb", "release_talk")})
    return w, kills


def test_the_watchdog_gives_the_deeper_talk_worker_its_own_budget(env, monkeypatch):
    """C1: Qwen (2411 MB measured) in the talk worker is not killed at WORKER_MB, and Find's total may grow by it."""
    from nobadfind import watchdog as wd
    a, ev = env["a"], env["events"]
    monkeypatch.setattr(api_mod, "talk_assess", lambda m, sample, pc: (True, ""))
    budgets = []
    start = thread_start(env["opts"], pid=4242)
    a._talk = worker.Talker(ev.append, start=start, on_budget=budgets.append)
    env["opts"].update(script=[f"t{i} " for i in range(800)], delay=0.005)
    r = a.vision_ask(env["ids"]["sea.jpg"], "what is the mood here?", deeper=True)
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    qwen = models.get(QWEN)["ram_mb"]
    assert budgets[0] == qwen and a.vision_budget_mb() == qwen        # raised when the job was sent
    order = []
    mb, job_mb = {4242: 2400, 5151: 1600}, [wd.JOB_MB + 2000]
    w, kills = _watchdog(a, mb, job_mb, order)
    assert w.worker_limit("talk worker") == int(1.5 * qwen) and w.job_limit() == wd.JOB_MB + qwen
    w.check()
    assert kills == [5151]                       # a text reader over 1500 MB still goes; the talk worker stays
    assert order == [] and a.vision_state()["busy"]                   # under JOB_MB + Qwen: nothing released
    mb[4242] = int(1.5 * qwen) + 10                                   # past its own budget: it goes
    del mb[5151]
    w.check()
    assert kills == [5151, 4242]
    a.vision_stop()
    assert budgets[-1] == 0 and w.worker_limit("talk worker") == wd.WORKER_MB and w.job_limit() == wd.JOB_MB


def test_memory_pressure_releases_the_talk_model_first_even_with_keep_models(env):
    """I2: over the total, the talk model goes first, also with "Keep models loaded" on; the indexer's models and
    workers stay until the next look."""
    from nobadfind import watchdog as wd
    a, ev = env["a"], env["events"]
    env["opts"].update(script=[f"t{i} " for i in range(800)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    order = []
    job_mb = [wd.JOB_MB + models.get(SMOL)["ram_mb"] + 100]
    w, kills = _watchdog(a, {}, job_mb, order, keep=True)
    w.check()
    assert order == [] and not a.vision_state()["running"]
    assert _final(ev, r["job"])["note"] == "Stopped: NOBAD Find needed the memory."
    w.check()                                                         # still over, no talk model now
    assert order == ["indexer recycle"]                              # then the old rule (keep: workers first)


def test_a_pause_stops_the_running_answer_and_the_model(env):
    """I1: a game or low memory (the governor's PAUSED) while an answer streams: it stops, the model goes."""
    a, ev = env["a"], env["events"]
    env["opts"].update(script=[f"t{i} " for i in range(800)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    assert a.vision_tick() is False                                   # gentle: it goes on
    a._governor.decision = Decision("paused", "Paused: low on memory (300 MB free)")
    try:
        assert a.vision_tick() is True
    finally:
        a._governor.decision = Decision("gentle", "Gentle: you are using the PC")
    assert _final(ev, r["job"]) == {"job": r["job"], "state": "cancelled", "text": "", "model": SMOL,
                                    "note": "Stopped: NOBAD Find paused (low on memory (300 MB free))."}
    assert not a.vision_state()["running"] and a.vision_budget_mb() == 0
    n = len(ev)
    time.sleep(0.05)
    assert len(ev) == n                                               # no late tokens


def test_a_hung_worker_is_ended_and_the_next_question_gets_a_fresh_one(env):
    """I3: a stall in load (or image encode) past the deadline: the worker is ended, the job gets an error."""
    a, ev = env["a"], env["events"]
    now = [0.0]
    stuck = threading.Event()
    env["opts"].update(hang=stuck)
    a._talk = worker.Talker(ev.append, start=env["start"], clock=lambda: now[0])
    try:
        r = a.vision_describe(env["ids"]["sea.jpg"])
        assert _wait(lambda: any(e["job"] == r["job"] and e["state"] == "loading" for e in ev))
        now[0] = worker.LOAD_S - 1
        assert a.vision_tick() is False and a.vision_state()["busy"]
        now[0] = worker.LOAD_S + 1
        assert a.vision_tick() is True
        assert _final(ev, r["job"]) == {"job": r["job"], "state": "error", "text": "", "model": SMOL,
                                        "note": "The photo model stopped responding. Try again."}
        assert env["start"].procs[0].terminated and not a.vision_state()["running"]
        env["opts"].pop("hang")
        r2 = a.vision_describe(env["ids"]["sea.jpg"])
        assert _wait(lambda: _final(ev, r2["job"])) and _final(ev, r2["job"])["state"] == "done"
        assert len(env["start"].started) == 2                          # a fresh worker
    finally:
        stuck.set()


def test_no_token_for_too_long_also_counts_as_hung(env):
    a, ev = env["a"], env["events"]
    now = [0.0]
    a._talk = worker.Talker(ev.append, start=env["start"], clock=lambda: now[0])
    env["opts"].update(script=[f"t{i} " for i in range(800)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    now[0] = worker.LOAD_S + worker.ANSWER_S - 5                      # tokens keep coming: deadline moves on
    assert _wait(lambda: a._talk._job and a._talk._job["deadline"] > now[0])
    assert a.vision_tick() is False
    now[0] += worker.ANSWER_S + 1
    a._talk._job["deadline"] = now[0] - 1                             # no token since (frozen fake clock)
    assert a.vision_tick() is True and _final(ev, r["job"])["note"] == worker.HUNG


def test_a_worker_that_cannot_start_ends_the_job_with_an_error(env):
    """I4: the reply named the job, so an event must follow even when the process can't start."""
    a, ev = env["a"], env["events"]

    def start():
        raise OSError("no more processes")
    a._talk = worker.Talker(ev.append, start=start)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert r["ok"]
    assert ev[-1] == {"job": r["job"], "state": "error", "text": "", "model": SMOL,
                      "note": "The picture model could not start. Try again."}
    assert not a.vision_state()["running"] and not a.vision_state()["busy"]


def test_idle_release_never_kills_a_question_that_just_came(env):
    """M1: the idle check and the stop are one step under the Talker's lock."""
    a, ev = env["a"], env["events"]
    now = [0.0]
    a._talk = worker.Talker(ev.append, start=env["start"], clock=lambda: now[0])
    env["opts"].update(script=[f"t{i} " for i in range(800)], delay=0.005)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["text"] for e in ev))
    now[0] = worker.IDLE + 5
    assert a._talk.stop(only_if_idle=worker.IDLE) is False and a.vision_state()["busy"]


def test_a_gone_photo_costs_no_model_load(env):
    """The photo is decoded before the model loads (M7)."""
    a, ev, ids = env["a"], env["events"], env["ids"]

    def gone(path, side):
        return worker.GONE
    a._talk = worker.Talker(ev.append, start=thread_start(env["opts"], decode=gone))
    r = a.vision_describe(ids["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"])) and _final(ev, r["job"])["note"] == worker.GONE
    assert not [x for x in FakeSession.log if x[0] == "load"]


def test_set_talk_allowance_raises_and_restores_the_worker_limit(monkeypatch):
    from nobadfind import jobs
    got = []

    class W:
        def set_memory_limit(self, mb):
            got.append(mb)
            return True
    monkeypatch.setattr(jobs, "WORKERS", W())
    monkeypatch.setattr(jobs, "_base_limit", [4096])
    assert jobs.set_talk_allowance(2411) and jobs.set_talk_allowance(0)
    assert got == [4096 + 2411, 4096]
    monkeypatch.setattr(jobs, "_base_limit", [0])
    assert jobs.set_talk_allowance(2411) is False                     # no limit set at start: none added


def test_runtime_reinstall_stops_the_worker_first(env, monkeypatch):
    a, ev = env["a"], env["events"]
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"]))
    seen = []
    monkeypatch.setattr(api_mod.vlm_runtime, "install",
                        lambda mid, d, progress: seen.append((mid, a.vision_state()["running"])))
    assert a.model_download("llama-cpu", "DOWNLOAD")["ok"]
    a._mdl_thread.join(5)
    assert seen == [("llama-cpu", False)]


def test_no_new_question_while_the_runtime_downloads(env):
    a = env["a"]
    a._mdl = {"llama-cpu": {"state": "downloading"}}
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert r["ok"] is False and "being downloaded" in r["error"]


def test_a_worker_that_dies_ends_the_job_with_an_error(env):
    a, ev = env["a"], env["events"]
    conns = []

    def start():
        x, y = multiprocessing.Pipe()
        conns.append(y)
        t = threading.Thread(target=lambda: (y.recv(), y.close()), daemon=True)       # takes the job, then dies
        t.start()
        return x, ThreadProc(t)
    a._talk = worker.Talker(ev.append, start=start)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"]))
    assert _final(ev, r["job"])["note"] == "The picture model stopped unexpectedly. Try again."
    assert not a.vision_state()["running"]


def test_the_vision_modules_import_no_network_library():
    """The worker's own modules (and photo decoding) bring in no HTTP/TLS client and none of Find's download code.
    (`socket` itself comes with multiprocessing, whose pipes on Windows are named pipes.)"""
    code = ("import sys; import nobadfind.vlm.worker, nobadfind.vlm.session, nobadfind.vlm.prompts, "
            "nobadfind.vlm.llama_api, nobadfind.photo; bad = [m for m in ('ssl', 'http.client', 'urllib.request', "
            "'requests', 'httpx', 'nobadfind.embed', 'nobadfind.update', 'nobadfind.vlm.runtime') "
            "if m in sys.modules]; print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


# ---------- the real model in the worker process (dev only) ----------
RUNTIME = os.environ.get("NOBAD_FIND_LLAMA_DIR")
SMOL_DIR = os.environ.get("NOBAD_FIND_SMOLVLM2_DIR")


def _link(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copyfile(src, dst)


@pytest.mark.skipif(not (RUNTIME and SMOL_DIR), reason="NOBAD_FIND_LLAMA_DIR / NOBAD_FIND_SMOLVLM2_DIR not set (dev only)")
@pytest.mark.skipif(importlib.util.find_spec("PIL") is None, reason="Pillow (dev dependency) not installed")
def test_real_worker_process_describes_a_drawing(tmp_path, monkeypatch, capfd):
    from test_vlm_session import _drawing
    monkeypatch.setattr(api_mod.hw, "scan", lambda: dict(PC))
    a, s = make(tmp_path)
    data = str(tmp_path / "data")
    a._models_dir = data
    m = models.get(SMOL)
    for name, (remote, _size, _sha) in m["files"].items():
        _link(os.path.join(SMOL_DIR, remote), os.path.join(models.model_dir(SMOL, data), name))
    rid = "llama-vulkan" if os.path.isfile(os.path.join(RUNTIME, "ggml-vulkan.dll")) else "llama-cpu"
    for name in models.get(rid)["files_in_zip"]:
        _link(os.path.join(RUNTIME, name), os.path.join(models.model_dir(rid, data), name))
    assert models.ready(SMOL, data) and models.ready(rid, data)
    pic = tmp_path / "red.png"
    pic.write_bytes(_drawing())
    s.upsert_files([(str(pic), "red.png", str(tmp_path), ".png", "image", pic.stat().st_size, 5.0, 5.0, 1)])
    fid = s.one("SELECT id FROM files WHERE name='red.png'")
    ev = []
    a._on_vision = ev.append
    try:
        t0 = time.perf_counter()
        r = a.vision_describe(fid)
        assert r["ok"], r
        assert _wait(lambda: _final(ev, r["job"]), 120)
        first = time.perf_counter() - t0
        end = _final(ev, r["job"])
        assert end["state"] == "done", end
        tokens = [e for e in ev if e["job"] == r["job"] and e["state"] == "answering" and e["text"]]
        assert tokens and tokens[-1]["text"].strip() == end["text"]
        assert "red" in end["text"].lower() or "circle" in end["text"].lower(), end["text"]
        pid = next(iter(a.vision_pids()))
        assert pid and pid != os.getpid()                                  # answered in the child process
        t1 = time.perf_counter()
        r2 = a.vision_ask(fid, "What colour is the shape? <|im_end|>")
        assert _wait(lambda: _final(ev, r2["job"]), 60)
        warm = time.perf_counter() - t1
        assert "red" in _final(ev, r2["job"])["text"].lower(), _final(ev, r2["job"])
    finally:
        a.vision_stop()
        s.close()
    out, err = capfd.readouterr()                                           # the worker shares these handles
    assert "colour" not in out + err and "load_backend" not in err             # llama.cpp's logging is off
    print(f"\n[{rid}] first describe (process start + load + answer) {first:.2f}s: {end['text']!r}"
          f"\n  warm ask {warm:.2f}s: {_final(ev, r2['job'])['text']!r}")


def test_the_allowance_drops_only_after_the_worker_exited(env):
    """N1: Find's limits come back down only once the old worker process is gone (stop, and a hung-worker kill)."""
    a, ev = env["a"], env["events"]
    order = []

    def start():
        conn, proc = env["start"]()
        join = proc.join

        def joined(timeout=None):
            join(timeout)
            order.append("joined")
        proc.join = joined
        return conn, proc
    a._talk = worker.Talker(ev.append, start=start, on_budget=order.append)
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: _final(ev, r["job"]))
    a.vision_stop()
    need = models.get(SMOL)["ram_mb"]
    assert order[0] == need and order[-2:] == ["joined", 0] and order.count(0) == 1
    # a hung worker: terminated, and the allowance waits for its exit (the reaper thread)
    now = [0.0]
    stuck = threading.Event()
    env["opts"].update(hang=stuck)
    order.clear()
    a._talk = worker.Talker(ev.append, start=start, on_budget=order.append, clock=lambda: now[0])
    r = a.vision_describe(env["ids"]["sea.jpg"])
    assert _wait(lambda: any(e["job"] == r["job"] and e["state"] == "loading" for e in ev))
    now[0] = worker.LOAD_S + 1
    assert a.vision_tick() is True
    assert 0 not in order                              # the (fake) process hasn't ended yet
    stuck.set()                                        # now it does
    assert _wait(lambda: order[-2:] == ["joined", 0])


# ---------- the deeper model (Qwen) in the real worker process, inside the real WORKERS job (dev only) ----------
QWEN_DIR = os.environ.get("NOBAD_FIND_QWEN_DIR")


def _peak_private_mb(pid):
    """PeakPagefileUsage (peak private commit) of one process, MB."""
    import ctypes
    from nobadfind import jobs
    h = jobs._k.OpenProcess(0x1000, False, int(pid))
    if not h:
        return 0
    try:
        pmc = jobs._PMC()
        pmc.cb = ctypes.sizeof(jobs._PMC)
        ok = jobs._psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
        return round(pmc.PeakPagefileUsage / 1048576) if ok else 0
    finally:
        jobs._k.CloseHandle(h)


def _job_limit_mb():
    import ctypes
    from nobadfind import jobs
    info = jobs._Extended()
    jobs._k.QueryInformationJobObject(jobs.WORKERS.handle, jobs._CLS_EXTENDED, ctypes.byref(info),
                                      ctypes.sizeof(info), None)
    return int(info.JobMemoryLimit // 1048576)


def qwen_child(tmp):
    """Run in a separate Python (it puts itself in Find's job objects): vision_ask(deeper=True) through the real
    worker process, the real watchdog checking during the answer. Prints one JSON line."""
    import json
    from nobadfind import engine, jobs
    from nobadfind import watchdog as wd
    from nobadfind.activity import Activity
    from test_vlm_session import _drawing
    jobs.setup()                                       # OUTER + WORKERS (with its memory limit), as engine.run does
    base = jobs._base_limit[0]
    a, s = make(__import__("pathlib").Path(tmp))
    data = os.path.join(tmp, "data")
    a._models_dir = data
    m = models.get(QWEN)
    names = {"model.gguf": "Qwen3VL-2B-Instruct-Q4_K_M.gguf", "mmproj.gguf": "mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf"}
    for name, remote in names.items():
        _link(os.path.join(QWEN_DIR, remote), os.path.join(models.model_dir(QWEN, data), name))
    rid = "llama-vulkan" if os.path.isfile(os.path.join(RUNTIME, "ggml-vulkan.dll")) else "llama-cpu"
    for name in models.get(rid)["files_in_zip"]:
        _link(os.path.join(RUNTIME, name), os.path.join(models.model_dir(rid, data), name))
    for name, (_p, size, _s) in m["files"].items():
        assert os.path.getsize(os.path.join(models.model_dir(QWEN, data), name)) == size, name
    pic = os.path.join(tmp, "red.png")
    with open(pic, "wb") as f:
        f.write(_drawing())
    s.upsert_files([(pic, "red.png", tmp, ".png", "image", os.path.getsize(pic), 5.0, 5.0, 1)])
    fid = s.one("SELECT id FROM files WHERE name='red.png'")
    ev, limits, kills, acts = [], [], [], Activity()
    a._on_vision = ev.append
    a._on_talk_budget = lambda mb: (jobs.set_talk_allowance(mb), limits.append((mb, _job_limit_mb())))
    hooks = engine.worker_hooks({"api": a})

    def kill(pid):
        kills.append(pid)
        wd.kill_process(pid)
    w = wd.Watchdog(acts, kill=kill, **{k: hooks[k] for k in ("release", "recycle", "names", "talk_mb",
                                                            "release_talk")})
    peak_ws, peak_job_ws, checks, stop = [0], [0], [0], threading.Event()

    def watch():
        while not stop.wait(0.25):
            for pid in a.vision_pids():
                peak_ws[0] = max(peak_ws[0], jobs.process_info(pid)["memory_mb"])
            peak_job_ws[0] = max(peak_job_ws[0], jobs.OUTER.usage()["memory_mb"])
            w.check()
            checks[0] += 1
    t = threading.Thread(target=watch, daemon=True)
    t.start()
    out = {"runtime": rid, "base_limit_mb": base}
    try:
        t0 = time.perf_counter()
        r = a.vision_ask(fid, "What colour is the shape?", deeper=True)
        out["reply"] = r
        if r["ok"]:
            _wait(lambda: _final(ev, r["job"]), 300)
            out["seconds"] = round(time.perf_counter() - t0, 2)
            out["final"] = _final(ev, r["job"])
            pids = list(a.vision_pids())
            out["worker_peak_private_mb"] = _peak_private_mb(pids[0]) if pids else 0
            out["job_peak_commit_mb"] = jobs.WORKERS.memory_peak_mb()
            out["budget_mb"] = a.vision_budget_mb()
            out["worker_limit_mb"] = w.worker_limit("talk worker")
            out["find_limit_mb"] = w.job_limit()
            out["job_commit_limit_mb"] = _job_limit_mb()
            out["still_running"] = a.vision_state()["running"]
    finally:
        stop.set()
        t.join(2)
        a.vision_stop()
        s.close()
    out.update(kills=kills, checks=checks[0], peak_working_set_mb=peak_ws[0], find_peak_working_set_mb=peak_job_ws[0],
               limits=limits, limit_after_mb=_job_limit_mb(), activity=[x["text"] for x in acts.recent(20)])
    print("QWEN " + json.dumps(out), flush=True)


@pytest.mark.skipif(not (RUNTIME and QWEN_DIR), reason="NOBAD_FIND_LLAMA_DIR / NOBAD_FIND_QWEN_DIR not set (dev only)")
@pytest.mark.skipif(importlib.util.find_spec("PIL") is None, reason="Pillow (dev dependency) not installed")
def test_real_qwen_deeper_answer_inside_the_workers_job(tmp_path):
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    code = f"import sys; sys.path[:0] = [{here!r}, {os.path.dirname(here)!r}]; import test_vision_api as t; " \
           f"t.qwen_child({str(tmp_path)!r})"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600, cwd=here)
    line = next((x for x in p.stdout.splitlines() if x.startswith("QWEN ")), None)
    assert line, p.stdout[-2000:] + p.stderr[-2000:]
    got = json.loads(line[5:])
    print("\n" + json.dumps(got, indent=1))
    assert got["reply"]["ok"], got["reply"]
    assert got["final"]["state"] == "done", got["final"]                       # an answer arrived ...
    assert got["final"]["model"] == QWEN and got["final"]["text"].strip()
    assert got["kills"] == [] and got["still_running"]                         # ... the worker wasn't killed ...
    assert "memory" not in got["final"]["note"].lower()                        # ... and no allocation failure
    need = models.talk_need_mb(models.get(QWEN), got["runtime"])
    assert got["budget_mb"] == need and got["job_commit_limit_mb"] == got["base_limit_mb"] + need
    assert got["limit_after_mb"] == got["base_limit_mb"]                       # back down once it has gone
    assert got["checks"] > 0
