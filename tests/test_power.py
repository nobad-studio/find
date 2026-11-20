"""0.9.3: Boost (every thread), the safety net, and Performance settings that apply at once."""
from nobadfind import governor as g, indexer, settings as settings_mod
from nobadfind.activity import Activity
from nobadfind.watchdog import JOB_MB, RELEASE_EVERY, Watchdog
from test_governor import GAME, brain, smp


class S(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def test_boost_plans_every_thread(monkeypatch):
    monkeypatch.setattr(indexer.os, "cpu_count", lambda: 16)
    calm = indexer.plan(S(), [], ssd=True)
    assert (calm["text_workers"], calm["text_workers_idle"], calm["model_threads"]) == (8, 15, 8)
    boost = indexer.plan(S(power="boost"), [], ssd=True)
    assert (boost["text_workers"], boost["text_workers_idle"], boost["model_threads"]) == (16, 16, 16)
    assert boost["walk_threads"] > calm["walk_threads"] and boost["boost"] is True
    assert indexer.plan(S(power="boost", workers=6), [], ssd=True)["text_workers"] == 6   # your number wins
    hdd = indexer.plan(S(power="boost"), [], ssd=False)
    assert hdd["text_workers"] == 2 and hdd["walk_threads"] == 2   # a spinning disk only seeks with more


def test_power_setting_is_checked():
    assert settings_mod.coerce("power", "boost") == "boost"
    assert settings_mod.coerce("power", "monster") == "balanced"
    assert settings_mod.coerce("safety_net", "no") is True


def test_boost_works_hard_while_you_use_the_pc():
    assert brain().decide(smp()).level == g.GENTLE
    d = brain(power="boost").decide(smp())
    assert d.level == g.FULL and d.reason.startswith("Boost")


def test_the_safety_net_steps_boost_down_before_it_pauses():
    b = brain(power="boost")
    assert b.decide(smp(free_mb=2500)).level == g.LIGHT                      # memory getting tight
    assert brain(power="boost").decide(smp(cpu=90.0)).level == g.GENTLE     # other apps busy, not yet long
    assert brain(power="boost").decide(smp(free_mb=1000)).level == g.PAUSED  # really low: paused, as always
    assert brain(power="boost").decide(smp(hung=True)).level == g.PAUSED
    assert brain(power="boost").decide(smp(**GAME)).level == g.LIGHT         # games keep their rule
    assert brain().decide(smp(free_mb=2500)).level == g.GENTLE              # Balanced: unchanged


def test_without_the_safety_net_only_the_crash_guards_stay():
    b = brain(power="boost", safety_net=False)
    assert b.decide(smp(free_mb=2500)).level == g.FULL
    b = brain(power="boost", safety_net=False)
    b.decide(smp(t=0, cpu=95.0))
    assert b.decide(smp(t=20, cpu=95.0)).level == g.FULL                    # busy CPU no longer pauses it
    assert brain(power="boost", safety_net=False).decide(smp(free_mb=1000)).level == g.PAUSED
    assert brain(power="boost", safety_net=False).decide(smp(hung=True)).level == g.PAUSED


def test_workers_and_boost_apply_without_a_restart(tmp_path):
    from nobadfind import api as api_mod
    from nobadfind.store import Store
    calls = []

    class Gov:
        def now(self):
            calls.append("now")

    class Ix:
        embedder = photo_text = pindex = None
        drive_list = []
        governor = Gov()

        def roots(self, d):
            return []

        def replan(self):
            calls.append("replan")

        def warm_models(self):
            calls.append("warm")

    s = Store(str(tmp_path / "i.db"), encrypt=False)
    a = api_mod.Api(s, settings_mod.Settings(str(tmp_path / "s.json")), Ix(), None)
    a.set_settings({"workers": 3})
    a.set_settings({"power": "boost"})
    a.set_settings({"safety_net": False})
    assert calls == ["replan", "replan", "now"]
    a.set_settings({"models_stay_loaded": True})
    import time
    for _ in range(50):
        if "warm" in calls:
            break
        time.sleep(0.02)
    assert "warm" in calls                                                    # loaded now, not at the next search
    s.close()


def test_replan_is_picked_up_by_the_running_indexer(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer.os, "cpu_count", lambda: 16)
    ix = indexer.Indexer.__new__(indexer.Indexer)
    ix.settings = S(power="boost")
    ix.status = {"plan": indexer.plan(S(), [], ssd=True)}
    ix.governor = None
    ix.wake = type("E", (), {"set": lambda self: None})()
    new = ix.replan()
    assert ix.status["plan"] is new and new["text_workers"] == 16


def test_keep_models_loaded_restarts_the_workers_first():
    t = [1000.0]
    log = {"release": 0, "recycle": 0}
    act = Activity()
    w = Watchdog(act, job_usage=lambda: {"memory_mb": JOB_MB + 1},
                 release=lambda: log.__setitem__("release", log["release"] + 1),
                 recycle=lambda: log.__setitem__("recycle", log["recycle"] + 1),
                 clock=lambda: t[0], keep_models=lambda: True)
    w.check()
    assert log == {"release": 0, "recycle": 1} and "stay loaded" in act.recent()[0]["text"]
    t[0] += RELEASE_EVERY + 1
    w.check()                                                                 # still too much: now the models too
    assert log == {"release": 1, "recycle": 2}


def test_what_to_index_counts_are_kept_until_something_changes(tmp_path, monkeypatch):
    from nobadfind import api as api_mod, scope
    from nobadfind.store import Store
    calls = []
    monkeypatch.setattr(scope, "info", lambda s, drives, store=None: calls.append(1) or {"n": len(calls)})
    monkeypatch.setattr(api_mod.winapi, "drives", lambda: [{"root": "C:\\", "type": "fixed"}])
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    ix = type("Ix", (), {"embedder": None, "photo_text": None, "pindex": None, "drive_list": [],
                         "roots": lambda self, d: [], "rescan": lambda self: None})()
    a = api_mod.Api(s, st, ix, None)
    assert a.scope_info() == {"n": 1} and a.scope_info() == {"n": 1} and len(calls) == 1   # counted once
    st.update({"include_caches": False})
    assert a.scope_info() == {"n": 2}                                                     # a change: again
    s.close()
