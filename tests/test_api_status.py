import os
import threading
import time

import pytest

from nobadfind import api as api_mod, hardware, settings, winapi
from nobadfind.activity import Activity
from nobadfind.governor import Decision
from nobadfind.store import Store


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    """The Processes rows come from fakes here: no snapshot of this PC, no command lines read."""
    monkeypatch.setattr(api_mod.procs, "snapshot", lambda: [])
    monkeypatch.setattr(api_mod.procs, "command_line", lambda pid: "")


class Ix:
    embedder = photo_text = pindex = None
    drive_list = []

    def __init__(self, phase="text"):
        self.status = {"phase": phase, "files": 3, "texts": 0, "vectors": 0, "paused": "", "rate": 0, "errors": 0,
                       "plan": {}, "last_scan": 0}

    def models_loaded(self):
        return []

    def roots(self, drives=None):
        return []

    def worker_names(self):
        return {}


class Gov:
    decision = Decision("gentle", "Gentle: you are using the PC")
    history = [{"t": 1.0, "cpu": 5.0, "gpu": 2.0, "find_cpu": 1.0, "find_mb": 100, "level": "gentle"}]

    def __init__(self):
        self.calls = []

    def pause_for(self, s):
        self.calls.append(("pause", s))

    def resume(self):
        self.calls.append(("resume",))


def counted(a):
    """The phase counts run in the background (0.9.0): start them and wait, as the Index page's next poll would."""
    a._counts(a._clock())
    if a._refresher is not None:
        a._refresher.join(10)
    return a


def make(tmp_path, phase="text", **changes):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.docx", "a.docx", "C:/p", ".docx", "document", 10, 1.0, 1.0, 1),
                    ("C:/p/b.pdf", "b.pdf", "C:/p", ".pdf", "document", 10, 1.0, 1.0, 1),
                    ("C:/p/c.jpg", "c.jpg", "C:/p", ".jpg", "image", 50000, 1.0, 1.0, 1)])
    st = settings.Settings(str(tmp_path / "s.json"))
    if changes:
        st.update(changes)
    a = api_mod.Api(s, st, Ix(phase), None)
    a._governor, a._activity = Gov(), Activity()
    return a, s


def test_status_has_transparency_keys(tmp_path):
    a, s = make(tmp_path)
    a._activity.add("info", "hello")
    st = a.status()
    assert st["level"] == "gentle" and st["reason"].startswith("Gentle")
    assert isinstance(st["history"], list) and st["history"][0]["find_mb"] == 100
    r = st["resources"]
    assert isinstance(r["cpu"], float) and isinstance(r["memory_mb"], int) and isinstance(r["read_mb_s"], float)
    assert r["gpu"] == 2.0 and isinstance(r["processes"], list)
    for p in r["processes"]:
        assert set(p) == {"name", "role", "about", "pid", "cpu", "memory_mb", "private_mb", "age_s", "readable",
                          "note"}
    assert {p["id"] for p in st["phases"]} == {"names", "text", "ocr", "meaning", "rebuild", "photos", "watching"}
    for p in st["phases"]:
        assert p["state"] in ("waiting", "running", "done", "off")
        assert isinstance(p["label"], str) and isinstance(p["done"], int) and isinstance(p["rate"], float)
        assert p["total"] is None or isinstance(p["total"], int)
        assert p["eta_s"] is None or isinstance(p["eta_s"], int)
    assert [m["id"] for m in st["models"]] == ["meaning", "photo", "ocr"]
    assert st["activity"][0]["text"] == "hello"
    assert st["files"] == 3 and "model" in st and "photo_model" in st      # old keys stay
    s.close()


def test_status_without_governor(tmp_path):
    a, s = make(tmp_path)
    a._governor = a._activity = None
    st = a.status()
    assert st["history"] == [] and st["activity"] == [] and st["resources"]["gpu"] is None
    assert a.pause_for(60) == {"ok": False} and a.resume() == {"ok": False}
    s.close()


def test_phase_states(tmp_path):
    a, s = make(tmp_path, "text")
    ph = {p["id"]: p for p in counted(a).status()["phases"]}
    assert ph["text"]["state"] == "running" and ph["text"]["total"] == 2 and ph["text"]["done"] == 0
    assert ph["names"]["state"] == "done"
    assert ph["meaning"]["state"] == "off"                     # meaning search is not on
    s.close()
    a, s = make(tmp_path, "text", content=False)
    ph = {p["id"]: p for p in counted(a).status()["phases"]}
    assert ph["text"]["state"] == "off" and ph["ocr"]["state"] == "off"
    s.close()


def test_phase_done_and_eta(tmp_path):
    a, s = make(tmp_path, "watching")
    s.set_text(1, 1.0, ["x"])
    s.set_text(2, 1.0, ["y"])
    ph = {p["id"]: p for p in counted(a).status()["phases"]}
    assert ph["text"]["state"] == "done" and ph["text"]["done"] == 2
    assert ph["watching"]["state"] == "running"
    s.close()


def test_models_cards_for_meaning_photo_ocr(tmp_path):
    a, s = make(tmp_path)
    a._model.update(state="downloading", got=5 * 1048576, size=23 * 1048576)
    m = {x["id"]: x for x in a.status()["models"]}
    assert m["meaning"]["license"] == "Apache-2.0" and m["meaning"]["size_mb"] == 22
    assert m["meaning"]["download"]["got_mb"] == 5 and m["meaning"]["download"]["size_mb"] == 23
    assert m["photo"]["download"] is None and m["photo"]["size_mb"] > 100
    assert m["ocr"]["device"] == "Windows" and m["ocr"]["size_mb"] == 0 and m["ocr"]["memory_mb"] is None
    for x in m.values():
        assert isinstance(x["on_disk"], bool) and isinstance(x["loaded"], bool) and isinstance(x["items"], int)
    s.close()


def test_pause_for_and_resume_reach_the_governor(tmp_path):
    a, s = make(tmp_path)
    assert a.pause_for(900) == {"ok": True}
    assert a.resume() == {"ok": True}
    assert a._governor.calls == [("pause", 900), ("resume",)]
    assert a.pause_for("x") == {"ok": False} and a.pause_for(True) == {"ok": False}
    s.close()


def test_learned_apps_and_reset(tmp_path):
    class Apps:
        def __init__(self):
            self.reset_with = "unset"

        def list(self):
            return [{"exe": "game.exe"}]

        def reset(self, exe=None):
            self.reset_with = exe
    a, s = make(tmp_path)
    assert a.learned_apps() == []
    a._apps = Apps()
    assert a.learned_apps() == [{"exe": "game.exe"}]
    a.reset_learned(None)
    assert a._apps.reset_with is None
    a.reset_learned("game.exe")
    assert a._apps.reset_with == "game.exe"
    assert a.reset_learned(5) == {"ok": False}
    s.close()


@pytest.mark.skipif(not winapi.WIN, reason="Windows only")
def test_hardware_scan_shape():
    h = hardware.scan()
    assert h["ram_gb"] > 0 and h["cores"] >= 1 and h["threads"] >= h["cores"]
    assert isinstance(h["avx2"], bool) and isinstance(h["avx512_vnni"], bool)
    assert isinstance(h["gpu"], str) and h["vram_gb"] >= 0 and isinstance(h["directml"], bool)
    assert h["disk_free_gb"] >= 0 and h["ssd"] in (True, False, None)
    assert hardware.scan() is h                                  # cached


def _clock(a):
    t = [0.0]
    a._clock = lambda: t[0]
    return t


class FakeJob:
    def __init__(self):
        self.cpu, self.read = 0.0, 0

    def pids(self):
        return [os.getpid(), 999]

    def usage(self):
        return {"cpu_seconds": self.cpu, "read_bytes": self.read, "write_bytes": 0, "memory_mb": 0, "processes": 2}


def test_resource_rates_are_deltas(tmp_path, monkeypatch):
    a, s = make(tmp_path)
    t = _clock(a)
    job, secs = FakeJob(), {os.getpid(): 0.0, 999: 0.0}
    monkeypatch.setattr(api_mod.jobs, "OUTER", job)
    monkeypatch.setattr(api_mod.jobs, "process_info",
                        lambda pid: {"pid": pid, "cpu_seconds": secs[pid], "memory_mb": 50 if pid == 999 else 100})
    r = a.status()["resources"]
    assert r["cpu"] == 0.0 and r["read_mb_s"] == 0.0 and r["memory_mb"] == 150          # first call: no rates
    t[0] = 10.0
    cores = os.cpu_count() or 1
    job.cpu, job.read, secs[999] = 5.0, 20 * 1048576, 5.0
    r = a.status()["resources"]
    assert r["read_mb_s"] == 2.0
    assert r["cpu"] == round(5.0 / 10 / cores * 100, 1)
    proc = {p["pid"]: p for p in r["processes"]}
    assert proc[os.getpid()]["role"] == "engine" and proc[999]["role"] == "other"
    assert proc[999]["cpu"] == round(5.0 / 10 / cores * 100, 1) and proc[os.getpid()]["cpu"] == 0.0
    s.close()


def test_model_cards_describe_the_worker(tmp_path, monkeypatch):
    a, s = make(tmp_path)
    a._indexer.worker_names = lambda: {999: "meaning worker"}
    a._indexer.meaning_device = lambda: "GPU"
    monkeypatch.setattr(api_mod.jobs, "OUTER", FakeJob())
    monkeypatch.setattr(api_mod.jobs, "process_info", lambda pid: {"pid": pid, "cpu_seconds": 0.0, "memory_mb": 77})
    m = {x["id"]: x for x in a.status()["models"]}
    assert m["meaning"]["loaded"] and m["meaning"]["memory_mb"] == 77 and m["meaning"]["device"] == "GPU"
    assert not m["photo"]["loaded"] and m["photo"]["memory_mb"] is None and m["photo"]["device"] == "CPU"
    s.close()


def test_eta_rate_window_and_reset(tmp_path):
    a, s = make(tmp_path, "text")
    t = _clock(a)
    counted(a)
    a._indexer.status["texts"] = 0
    a.status()
    t[0] = 10.0
    a._indexer.status["texts"] = 20
    ph = {p["id"]: p for p in a.status()["phases"]}["text"]
    remaining = ph["total"] - ph["done"]
    assert ph["rate"] == 2.0 and ph["eta_s"] == int(remaining / 2.0)
    t[0] = 11.0
    a._indexer.status["phase"] = "watching"
    a.status()
    t[0] = 12.0
    a._indexer.status.update(phase="text", texts=40)
    ph = {p["id"]: p for p in a.status()["phases"]}["text"]
    assert ph["rate"] == 0.0 and ph["eta_s"] is None          # old samples were dropped when the phase stopped
    s.close()


def test_download_speed(tmp_path):
    a, s = make(tmp_path)
    t = _clock(a)
    a._model.update(state="downloading", got=5 * 1048576, size=23 * 1048576)
    assert a.status()["models"][0]["download"]["mb_s"] == 0.0
    t[0] = 5.0
    a._model["got"] = 15 * 1048576
    assert a.status()["models"][0]["download"]["mb_s"] == 2.0
    s.close()


def test_counts_are_cached_and_refreshed_in_background(tmp_path):
    a, s = make(tmp_path)
    calls = []
    real = s.count_needs_text
    s.count_needs_text = lambda *x, **k: (calls.append(1), real(*x, **k))[1]
    assert a._counts(0.0) == {}                                  # the first call never counts inline (0.9.0)
    a._refresher.join(5)
    n = len(calls)
    assert n > 0
    first = a._counts(1.0)                                       # the background count's result
    assert first and a._counts(5.0) is first and len(calls) == n  # inside 10 s: no queries
    assert a._counts(11.0) is first                              # stale: old values now, refresh in the background
    a._refresher.join(5)
    assert len(calls) > n and a._counts(12.0) is not first
    s.close()


def test_newest_first_listing_and_version_for_the_home_screen(tmp_path):
    a, s = make(tmp_path)
    r = a.search("", {"sort": "newest"})                      # the Home screen's "Recently changed"
    assert {x["name"] for x in r["results"]} == {"a.docx", "b.pdf", "c.jpg"}
    assert a.search("", {"sort": "bogus"})["results"] == []   # an unknown order alone is still not a search
    assert a.search("", {})["results"] == []
    from nobadfind.const import APP_VER
    assert a.status()["version"] == APP_VER


def test_open_starts_the_file_outside_finds_job(tmp_path, monkeypatch):
    """C-1: Api.open goes through the breakaway launcher, so Quit never takes the opened app down."""
    a, s = make(tmp_path)
    f = tmp_path / "note.txt"
    f.write_text("hi")
    s.upsert_files([(str(f), "note.txt", str(tmp_path), ".txt", "text", 2, 1.0, 1.0, 1)])
    fid = s.one("SELECT id FROM files WHERE path=?", (str(f),))
    opened, started = [], []
    monkeypatch.setattr(api_mod.winapi, "open_outside_job", lambda p: opened.append(p))
    monkeypatch.setattr(api_mod.os, "startfile", lambda p: started.append(p), raising=False)
    assert a.open(fid) == {"ok": True}
    assert opened == [str(f)] and started == []

    def refused(p):
        raise PermissionError(5, "Access is denied")
    monkeypatch.setattr(api_mod.winapi, "open_outside_job", refused)
    assert a.open(fid) == {"ok": True}                  # breakaway refused: the old way, logged
    assert started == [str(f)]
    s.close()


def test_open_outside_job_starts_explorer_with_breakaway(monkeypatch):
    calls = []

    class P:
        def __init__(self, argv, **kw):
            calls.append((argv, kw))
    monkeypatch.setattr(winapi.subprocess, "Popen", P)
    monkeypatch.setenv("WINDIR", r"C:\Planted")                  # never from the environment (review L3)
    monkeypatch.setattr(winapi, "windows_dir", lambda: r"C:\Windows")
    path = "C:\\a, b & c\\\u00e4 \u65e5.txt"
    winapi.open_outside_job(path)
    argv, kw = calls[0]
    assert argv == [os.path.join(r"C:\Windows", "explorer.exe"), path]       # a list: no shell string
    assert kw["creationflags"] & winapi.CREATE_BREAKAWAY_FROM_JOB and not kw.get("shell")


class _Timer:
    made = []

    def __init__(self, secs, fn):
        self.secs, self.fn, self.daemon, self.started = secs, fn, False, False
        _Timer.made.append(self)

    def start(self):
        self.started = True


class _StopIx(Ix):
    def __init__(self):
        super().__init__()
        self.calls = []

    def stop(self, keep_watching=False):
        self.calls.append("stop")

    def join(self, timeout=10):
        self.calls.append(("join", timeout))
        return True


def test_quit_arms_a_hard_exit_that_lets_the_indexer_finish_first(tmp_path):
    """I-1: a hung exit can't keep NOBAD Find running; the indexer stops and is joined before the process ends,
    so a SQLite write in progress is committed."""
    a, s = make(tmp_path)
    a._indexer = _StopIx()
    exits = []
    a._timer, a._exit = _Timer, exits.append
    _Timer.made.clear()
    assert a.quit() == {"ok": True}
    t = _Timer.made[0]
    assert t.secs == api_mod.QUIT_TIMEOUT == 15 and t.daemon and t.started
    assert exits == []                                # nothing happens unless the quit hangs
    a._indexer.calls.clear()
    t.fn()
    assert a._indexer.calls == ["stop", ("join", 5)] and exits == [0]
    s.close()


def test_hide_tells_the_engine(tmp_path):
    """I-2: Api.hide (ui_hidden, or the UI's pipe closing) calls the engine's hook (lifecycle.after_hide)."""
    a, s = make(tmp_path)
    order = []
    assert a.hide() == {"ok": True}                  # no hook set: nothing happens
    a._on_hide = lambda: order.append("hook")
    a.hide()
    assert order == ["hook"]
    s.close()


def test_hard_exit_is_armed_once(tmp_path):
    a, s = make(tmp_path)
    a._timer = _Timer
    _Timer.made.clear()
    a._arm_hard_exit()
    a._arm_hard_exit()
    assert len(_Timer.made) == 1 and _Timer.made[0].daemon and _Timer.made[0].started
    s.close()


def test_the_first_status_never_waits_for_the_counts(tmp_path):
    """0.9.0: on a big index the counts take seconds; the first status answers at once (phases "waiting", no
    total) and the counts come in the background, so the Index and Settings pages never stay blank."""
    import threading
    a, s = make(tmp_path, "watching")
    gate = threading.Event()
    real = a._refresh

    def slow(now, key):
        gate.wait(5)
        return real(now, key)
    a._refresh = slow
    ph = {p["id"]: p for p in a.status()["phases"]}              # answers while the count is held back
    assert ph["text"]["state"] == "waiting" and ph["text"]["total"] is None
    assert a.status() and a._refresher.is_alive()                # a second poll starts no second count
    gate.set()
    a._refresher.join(5)
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["text"]["total"] == 2
    s.close()


def test_status_shows_the_governors_limits_and_a_default_without_them(tmp_path):
    a, s = make(tmp_path)
    assert set(a.status()["limits"]) == {"walk", "readers", "photo", "vision"}          # Gov has no limits yet
    a._governor.limits = {"walk": {"effective": 3}}
    assert a.status()["limits"] == {"walk": {"effective": 3}}
    s.close()


def test_capability_state_uses_the_governors_last_reading(tmp_path, monkeypatch):
    from nobadfind.governor import Sample
    monkeypatch.setattr(hardware, "scan", lambda: {"ram_gb": 15.7, "cores": 8, "threads": 16, "directml": False,
                                                   "vram_gb": 0.1, "disk_free_gb": 100.0})
    a, s = make(tmp_path)
    r = a.capability_state()
    assert r["budget"]["live"] is False and all(r["can_run"].values())       # no reading yet: installed facts
    a._governor.sample = Sample(t=0.0, cpu=20.0, gpu=None, mem_load=80, free_mb=1700, find_cpu=0.0, foreground="",
                                game=False, presentation=False, hung=False, battery=False, call=False, idle_s=0.0)
    r = a.capability_state()
    assert r["budget"]["free_mb"] == 1700 and r["can_run"]["multilingual-e5-base"] is False
    assert r["can_run"]["windows-ocr"] is True
    s.close()


# ---------- 1.1.1: the index totals (Store.stats) are counted in the background, one count at a time ----------
class SlowStats:
    """Store.stats as on a big index: six COUNTs that take seconds. Each count waits for `go` (when given)."""

    def __init__(self, go=None):
        self.go, self.calls, self.n = go, 0, 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.calls += 1
        if self.go is not None:
            assert self.go.wait(10)
        self.n += 100
        return {"files": 3, "with_text": self.n, "chunks": 9, "vectors": 7, "name_vectors": 5, "photo_vectors": 1,
                "encrypted": False, "db_bytes": 1}


def stats_counted(a):
    t = a._stats_thread
    if t is not None:
        t.join(10)
        assert not t.is_alive()


def test_status_never_counts_inline(tmp_path):
    a, s = make(tmp_path)
    go = threading.Event()
    s.stats = SlowStats(go)
    t0 = time.monotonic()
    st = a.status()                                              # even the first time
    assert time.monotonic() - t0 < 0.2
    assert st["counting_totals"] is True                         # the UI says "Counting..." for these
    assert (st["files"], st["with_text"], st["chunks"], st["name_vectors"], st["photo_vectors"]) == (3, 0, 0, 0, 0)
    assert st["db_bytes"] == sum(os.path.getsize(p) for p in (s.db_path, s.db_path + "-wal") if os.path.exists(p))
    go.set()
    stats_counted(a)
    st = a.status()
    assert st["counting_totals"] is False and st["with_text"] == 100 and st["photo_vectors"] == 1
    assert st["db_bytes"] > 1                                    # the size is always the file's, never the cache's
    s.close()


def test_concurrent_status_calls_start_one_count(tmp_path):
    a, s = make(tmp_path)
    go = threading.Event()
    s.stats = slow = SlowStats(go)
    out = []
    polls = [threading.Thread(target=lambda: out.append(a.status())) for _ in range(4)]
    for t in polls:
        t.start()
    for t in polls:
        t.join(10)
    assert len(out) == 4 and all(st["counting_totals"] for st in out)
    assert slow.calls == 1
    go.set()
    stats_counted(a)
    a.status()
    assert slow.calls == 1                                       # just counted: no second count
    s.close()


def test_stats_refresh_after_ttl(tmp_path):
    a, s = make(tmp_path)
    now = [100.0]
    a._clock = lambda: now[0]
    s.stats = slow = SlowStats()
    a.status()
    stats_counted(a)
    assert a.status()["with_text"] == 100 and slow.calls == 1
    now[0] += api_mod.STATS_TTL - 1
    assert a.status()["with_text"] == 100 and slow.calls == 1    # fresh: reused
    go = slow.go = threading.Event()
    now[0] += 2                                                  # stale
    st = a.status()
    assert st["with_text"] == 100 and st["counting_totals"] is False      # the old totals at once
    assert a.status()["with_text"] == 100 and slow.calls == 2    # one refresh, however many polls
    go.set()
    stats_counted(a)
    assert a.status()["with_text"] == 200 and slow.calls == 2
    s.close()


# ---------- 1.2.0 S1: the snapshots say when they were counted and whether the last count worked ----------
def snapshot(a, prefix, key):
    st = a.status()
    return st[prefix + "_state"], st[prefix + "_at"], st[prefix + "_error"], st


def test_totals_state_goes_counting_ready_refreshing_ready(tmp_path):
    a, s = make(tmp_path)
    now, wall = [100.0], [5000.0]
    a._clock, a._wall = (lambda: now[0]), (lambda: wall[0])
    go = threading.Event()
    s.stats = slow = SlowStats(go)
    state, at, err, st = snapshot(a, "totals", None)
    assert (state, at, err) == ("counting", None, "") and st["counting_totals"] is True
    go.set()
    stats_counted(a)
    state, at, err, st = snapshot(a, "totals", None)
    assert (state, at, err) == ("ready", 5000.0, "") and st["counting_totals"] is False
    now[0] += api_mod.STATS_TTL + 1
    wall[0] = 5100.0
    go.clear()
    slow.go = go
    state, at, err, st = snapshot(a, "totals", None)
    assert (state, at) == ("refreshing", 5000.0) and st["with_text"] == 100 and st["counting_totals"] is False
    go.set()
    stats_counted(a)
    state, at, _e, st = snapshot(a, "totals", None)
    assert (state, at, st["with_text"]) == ("ready", 5100.0, 200)
    s.close()


def test_a_failed_totals_count_keeps_the_values_and_the_time(tmp_path):
    a, s = make(tmp_path)
    now, wall = [100.0], [5000.0]
    a._clock, a._wall = (lambda: now[0]), (lambda: wall[0])
    s.stats = SlowStats()
    a.status()
    stats_counted(a)
    assert a.status()["totals_state"] == "ready"

    def boom():
        raise RuntimeError("secret text from inside")
    s.stats = boom
    now[0] += api_mod.STATS_TTL + 1
    wall[0] = 5100.0
    a.status()
    stats_counted(a)
    state, at, err, st = snapshot(a, "totals", None)
    assert state == "failed" and at == 5000.0 and st["with_text"] == 100
    assert err and "secret" not in err and "RuntimeError" not in err
    assert st["counting_totals"] is False
    s.close()


def test_a_first_totals_count_that_fails_says_so(tmp_path):
    a, s = make(tmp_path)

    def boom():
        raise RuntimeError("x")
    s.stats = boom
    a.status()
    stats_counted(a)
    state, at, err, st = snapshot(a, "totals", None)
    assert state == "failed" and at is None and err and st["counting_totals"] is False
    s.close()


def test_counts_state_goes_counting_ready_refreshing_ready(tmp_path):
    a, s = make(tmp_path, "watching")
    now, wall = [100.0], [7000.0]
    a._clock, a._wall = (lambda: now[0]), (lambda: wall[0])
    gate = threading.Event()
    real = a._refresh

    def slow(n, key):
        gate.wait(5)
        return real(n, key)
    a._refresh = slow
    state, at, err, _st = snapshot(a, "counts", None)
    assert (state, at, err) == ("counting", None, "")
    gate.set()
    a._refresher.join(5)
    state, at, err, _st = snapshot(a, "counts", None)
    assert (state, at, err) == ("ready", 7000.0, "")
    now[0] += api_mod.TOTALS_TTL + 1
    wall[0] = 7100.0
    gate.clear()
    state, at, _e, _st = snapshot(a, "counts", None)
    assert (state, at) == ("refreshing", 7000.0)
    gate.set()
    a._refresher.join(5)
    state, at, _e, _st = snapshot(a, "counts", None)
    assert (state, at) == ("ready", 7100.0)
    s.close()


def test_a_failed_counts_refresh_keeps_the_old_snapshot(tmp_path):
    a, s = make(tmp_path, "watching")
    now, wall = [100.0], [7000.0]
    a._clock, a._wall = (lambda: now[0]), (lambda: wall[0])
    counted(a)
    before = a._totals[2]
    assert before and a.status()["counts_state"] == "ready"

    def boom(*_a, **_k):
        raise RuntimeError("secret")
    s.count_readable = boom
    now[0] += api_mod.TOTALS_TTL + 1
    wall[0] = 7100.0
    counted(a)
    state, at, err, _st = snapshot(a, "counts", None)
    assert state == "failed" and at == 7000.0 and err and "secret" not in err
    assert a._totals[2] == before
    s.close()


def test_a_phase_ending_does_not_bring_the_stats_count_forward(tmp_path):
    a, s = make(tmp_path, "text")
    now = [100.0]
    a._clock = lambda: now[0]
    s.stats = slow = SlowStats()
    a.status()
    stats_counted(a)
    calls = slow.calls
    a._stats_cache = (a._stats_cache[0], 1000.0, a._stats_cache[2])    # a slow index: the share-of-a-core wait
    a._indexer.status["phase"] = "meaning"                      # a phase ended
    now[0] += 1
    a.status()
    now[0] += api_mod.STATS_TTL                                 # past the 10 s floor, not past the full ttl
    a.status()
    stats_counted(a)
    assert slow.calls == calls                                  # the mark never brings a refresh forward
    now[0] = a._stats_cache[0] + 1000.0                         # the full ttl has passed
    a.status()
    stats_counted(a)
    assert slow.calls == calls + 1
    a.status()
    stats_counted(a)
    assert slow.calls == calls + 1                              # one count for one event


def test_a_phase_ending_does_not_bring_the_phase_counts_forward(tmp_path):
    a, s = make(tmp_path, "text")
    now = [100.0]
    a._clock = lambda: now[0]
    calls = []
    real = a._refresh

    def refresh(at, key):
        calls.append(at)
        real(at, key)

    a._refresh = refresh
    counted(a)
    assert len(calls) == 1
    a._totals_took = 1000.0 / api_mod.COUNT_SHARE               # a slow index: ttl = 1000 s
    now[0] += api_mod.TOTALS_TTL + 1                            # past the 10 s floor, not past the full ttl
    counted(a)
    assert len(calls) == 1
    now[0] = a._totals[0] + 1000.0                              # the full ttl has passed
    counted(a)
    assert len(calls) == 2
    counted(a)
    assert len(calls) == 2


def test_a_count_finishing_between_the_two_reads_is_not_reported_ready_and_empty(tmp_path):
    a, s = make(tmp_path)
    s.stats = SlowStats()
    real = a._stats

    def stats_then_the_count_lands():
        got = real()                                            # None: the first count has just been started
        assert got is None
        stats_counted(a)                                        # ...and it finishes before status() looks at it
        return got

    a._stats = stats_then_the_count_lands
    st = a.status()
    assert st["totals_state"] == "ready" and st["totals_at"] is not None
    assert st["with_text"] == 100 and st["chunks"] == 9         # the real totals, not zeros
    assert st["counting_totals"] is False


def test_the_status_fields_validate_against_the_schema(tmp_path):
    # the repo's own checker (tests/schemacheck.py): jsonschema isn't in the hash-pinned lock the build and CI use
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from schemacheck import Checker
    a, s = make(tmp_path)
    s.stats = SlowStats()
    a.status()
    stats_counted(a)
    st = a.status()
    check = Checker(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract"))
    props = check.doc("methods.schema.json")["$defs"]["status_full"]["properties"]
    for k in ("totals_at", "totals_state", "totals_error", "counts_at", "counts_state", "counts_error"):
        assert k in props, k
        assert not check.unknown_keywords(props[k]), k
        errs = check.errors(st[k], props[k], "methods.schema.json")
        assert not errs, (k, errs)
    s.close()
