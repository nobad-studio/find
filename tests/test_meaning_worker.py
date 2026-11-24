"""The meaning worker says why it ends, and doesn't reload its model for passing level or thread changes (1.2.0)."""
import concurrent.futures as cf
import concurrent.futures.process as cfp

import numpy as np

from nobadfind import governor as g
from nobadfind import indexer
from nobadfind.activity import Activity


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class FakeGov:
    def __init__(self, level):
        self.decision = g.Decision(level, "why")
        # a graphics card with room: the reserve and fit check (test_gpu_fit.py) let the level decide here
        self.sample = g.Sample(t=0.0, cpu=10.0, gpu=5.0, mem_load=40, free_mb=8000, find_cpu=0.0, foreground="",
                               game=False, presentation=False, hung=False, battery=False, call=False, idle_s=0.0,
                               gpu_mem={"kind": "dedicated", "free_mb": 6000, "used_mb": 2192, "budget_mb": 8192})


class _Proc:
    exitcode = None

    def terminate(self):
        pass


class Pool:
    """A ProcessPoolExecutor stand-in: every submit is answered at once (or fails with `fail`)."""
    made = []
    fail = None

    def __init__(self, *a, **k):
        self.args = k.get("initargs")
        self._processes = {4242: _Proc()}
        Pool.made.append(self)

    def submit(self, fn, *args):
        f = cf.Future()
        if Pool.fail is not None:
            f.set_exception(Pool.fail)
        else:
            f.set_result(np.zeros((len(args[0]), 4), np.float32).tobytes())
        return f

    def shutdown(self, **k):
        self._processes = {}


def _ix(monkeypatch, level=g.FULL, threads=6):
    Pool.made, Pool.fail = [], None
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(indexer.models, "model_dir", lambda mid: "dir")
    monkeypatch.setattr(indexer.models, "get", lambda mid: None)
    lines = []
    monkeypatch.setattr(indexer, "log", lambda msg, lvl="info": lines.append((lvl, msg)))
    fg = FakeGov(level)
    ix = indexer.Indexer(None, S(), governor=fg, activity=Activity())
    ix._vectors_in_worker = True
    ix.status["plan"] = {"model_threads": threads, "text_workers": threads, "text_workers_idle": threads}
    clock = [0.0]
    ix._clock = lambda: clock[0]
    ix._fg, ix._t, ix._lines = fg, clock, lines
    return ix


def _go(ix, level=None, at=None, threads=None, mid=None):
    if level is not None:
        ix._fg.decision = g.Decision(level, "why")
    if at is not None:
        ix._t[0] = at
    if threads is not None:
        ix.status["plan"] = {"model_threads": threads, "text_workers": threads, "text_workers_idle": threads}
    assert ix._encode(["a"], mid) is not None


def _ends(ix):
    return [m for _, m in ix._lines if m.startswith("meaning worker ended")]


def test_level_flip_up_and_down_restarts_once_per_hold(monkeypatch):
    ix = _ix(monkeypatch, g.FULL)
    _go(ix, at=0)
    assert len(Pool.made) == 1 and ix._mpool_gpu is True
    _go(ix, g.GENTLE, at=10)                     # down: at once
    assert len(Pool.made) == 2 and ix._mpool_gpu is False
    _go(ix, g.FULL, at=20)                       # short up blips: the processor worker keeps serving
    _go(ix, g.GENTLE, at=30)
    _go(ix, g.FULL, at=40)
    _go(ix, g.GENTLE, at=50)
    assert len(Pool.made) == 2


def test_up_after_hold_restarts_to_gpu(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE)
    _go(ix, at=0)
    _go(ix, g.FULL, at=10)
    _go(ix, at=100)                              # held 90 s: not yet
    assert len(Pool.made) == 1
    _go(ix, at=131)                              # held 121 s
    assert len(Pool.made) == 2 and ix._mpool_gpu is True
    assert any("level" in m for m in _ends(ix))


def test_more_threads_wait_and_fewer_threads_are_immediate(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE, threads=1)
    _go(ix, at=0)
    _go(ix, threads=6, at=10)                    # up: waits
    assert len(Pool.made) == 1
    _go(ix, at=131)
    assert len(Pool.made) == 2
    _go(ix, threads=1, at=140)                   # down: at once
    assert len(Pool.made) == 3


def test_fewer_threads_is_immediate(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE, threads=6)
    _go(ix, at=0)
    _go(ix, threads=1, at=1)
    assert len(Pool.made) == 2
    assert any("threads 6→1" in m for m in _ends(ix))


def test_model_change_is_immediate(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE)
    _go(ix, at=0, mid="a")
    _go(ix, at=1, mid="b")
    assert len(Pool.made) == 2
    assert any("model a→b" in m for m in _ends(ix))


def test_every_end_logs_its_reason(monkeypatch):
    ix = _ix(monkeypatch, g.FULL, threads=6)
    _go(ix, at=0, mid="a")
    _go(ix, g.GENTLE, at=1, mid="a")             # level
    _go(ix, threads=1, at=2, mid="a")            # threads (down)
    _go(ix, at=3, mid="b")                       # model
    ix._end_meaning_pool("idle")
    _go(ix, at=4, mid="b")
    Pool.fail = cfp.BrokenProcessPool("died")
    assert ix._encode(["a"], "b") is None        # failed
    Pool.fail = None
    _go(ix, at=5, mid="b")
    ix.stop_ev.set()
    ix._end_meaning_pool("idle")                 # stopping wins
    ends = _ends(ix)
    for word in ("level", "threads 6→1", "model a→b", "idle", "failed (BrokenProcessPool", "stopping"):
        assert sum(word in m for m in ends) == 1, (word, ends)


def test_pause_end_says_paused(monkeypatch):
    ix = _ix(monkeypatch, g.PAUSED)
    ix._mpool = Pool()
    ix._mpool_model = None
    ix._clock = lambda: 0.0
    c = [0.0]

    def wait(t=None):
        c[0] += 20
        ix._clock = lambda: c[0]
        return False
    ix._clock = lambda: c[0]
    ix.stop_ev.wait = wait
    ix._chunk_vectors()
    assert any("paused" in m for m in _ends(ix))


def test_broken_pool_exit_code_is_logged(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE)
    _go(ix, at=0)
    ix._mpool._processes[4242].exitcode = -1073741819
    Pool.fail = cfp.BrokenProcessPool("died")
    assert ix._encode(["a"]) is None
    assert any("-1073741819" in m for m in _ends(ix))


def test_restart_storm_warns_once_an_hour(monkeypatch):
    ix = _ix(monkeypatch, g.GENTLE)
    for i in range(14):
        _go(ix, at=i * 10, mid="a" if i % 2 else "b")      # a model change each time: 14 starts
    warns = [m for lvl, m in ix._lines if lvl == "warn" and "restarted" in m]
    assert len(warns) == 1 and "model" in warns[0] and "in the last hour" in warns[0]
    for i in range(14, 20):
        _go(ix, at=i * 10, mid="a" if i % 2 else "b")
    assert len([1 for lvl, m in ix._lines if lvl == "warn" and "restarted" in m]) == 1
    for i in range(14):                                     # an hour later: again, once
        _go(ix, at=4000 + i * 10, mid="a" if i % 2 else "b")
    assert len([1 for lvl, m in ix._lines if lvl == "warn" and "restarted" in m]) == 2
