"""1.2.0 (spec 2026-11-22 §4.2, §8b): the performance goal (quiet | balanced | fast), the one-time move from
`power`, the user's overrides and "Reset to safe defaults". Time only from the samples (fake ones)."""
import json

from nobadfind import api as api_mod, governor as g, indexer, profile, settings as settings_mod
from nobadfind.const import DEFAULTS
from nobadfind.store import Store
from test_governor import FakeApps, FakeSettings, brain, smp


class Ix:
    embedder = photo_text = pindex = None
    drive_list = []
    governor = None

    def __init__(self):
        self.calls = []

    def roots(self, d=None):
        return []

    def replan(self):
        self.calls.append("replan")

    def rescan(self):
        self.calls.append("rescan")


def _settings_file(tmp_path, **raw):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(dict({"settings_rev": 3}, **raw)), encoding="utf-8")
    return str(p)


def _api(tmp_path, path):
    store = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings_mod.Settings(path)
    return api_mod.Api(store, st, Ix(), None), store, st


# ---------- the move from power (A18) ----------
def test_power_migrates_once(tmp_path):
    path = _settings_file(tmp_path, power="boost")
    a, store, st = _api(tmp_path, path)
    assert st.get("performance_goal") == "fast" and st.get("power") == "boost"
    assert store.meta("goal_migrated") == "1"
    saved = json.loads(open(path, encoding="utf-8").read())
    assert saved["performance_goal"] == "fast"                          # kept in the file, not only in memory
    a.set_settings({"performance_goal": "quiet"})                       # power becomes balanced (compat layer)
    store.close()
    a2, store2, st2 = _api(tmp_path, path)
    assert st2.get("performance_goal") == "quiet"                       # not taken from power again
    assert st2.get("power") == "balanced"
    assert store2.meta("goal_migrated") == "1"
    store2.close()


def _unreadable(monkeypatch, path):
    """settings.json can't be opened for reading (antivirus or a backup holding it); writing still works."""
    real = open

    def fake(p, mode="r", *a, **kw):
        if str(p) == str(path) and "r" in mode:
            raise PermissionError(13, "in use", str(p))
        return real(p, mode, *a, **kw)
    monkeypatch.setattr(settings_mod, "open", fake, raising=False)


def test_a_settings_file_that_cant_be_read_is_never_overwritten_and_migrates_later(tmp_path, monkeypatch):
    raw = {"settings_rev": 3, "power": "boost", "roots": [str(tmp_path)], "scope": "custom",
           "exclude": [str(tmp_path / "private")], "hotkey": "ctrl+alt+f"}
    cases = {"unreadable": json.dumps(raw).encode("utf-8"), "corrupt": b'{"power": "boost", "roots": [',
             "not a dict": b'["power", "boost"]'}
    for name, body in cases.items():
        d = tmp_path / name.replace(" ", "_")
        d.mkdir()
        path = d / "s.json"
        path.write_bytes(body)
        with monkeypatch.context() as m:
            if name == "unreadable":
                _unreadable(m, path)
            a, store, st = _api(d, str(path))
            assert st.settle_goal() is False, name                      # nothing saved over it
        assert path.read_bytes() == body, name                          # byte for byte
        assert store.meta("goal_migrated") is None, name                # tried again at the next start
        store.close()
    # the next start reads the file: it migrates as usual, with everything the user had
    d = tmp_path / "unreadable"
    a, store, st = _api(d, str(d / "s.json"))
    assert st.get("performance_goal") == "fast" and store.meta("goal_migrated") == "1"
    saved = json.loads((d / "s.json").read_text(encoding="utf-8"))
    assert saved["performance_goal"] == "fast" and saved["scope"] == "custom" and saved["hotkey"] == "ctrl+alt+f"
    assert saved["exclude"] == [str(tmp_path / "private")] and saved["roots"] == [str(tmp_path)]
    store.close()


def test_balanced_power_migrates_to_balanced_and_a_new_install_is_balanced(tmp_path):
    a, store, st = _api(tmp_path, _settings_file(tmp_path, power="balanced"))
    assert st.get("performance_goal") == "balanced" and store.meta("goal_migrated") == "1"
    store.close()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    a, store, st = _api(fresh, str(fresh / "s.json"))
    assert st.get("performance_goal") == "balanced" and store.meta("goal_migrated") == "1"
    store.close()


def test_power_compat_layer(tmp_path):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    assert set(st.update({"power": "boost"})) == {"power", "performance_goal"}
    assert st.get("performance_goal") == "fast"
    st.update({"performance_goal": "quiet"})
    assert st.get("power") == "balanced"                                # anything but fast reads as balanced
    st.update({"power": "balanced"})                                    # an older UI writing what it reads
    assert st.get("performance_goal") == "quiet"                        # ... changes nothing
    st.update({"power": "boost"})
    assert st.get("performance_goal") == "fast"
    st.update({"power": "balanced"})
    assert st.get("performance_goal") == "balanced"
    st.update({"performance_goal": "fast", "power": "balanced"})        # both at once: the goal decides
    assert (st.get("performance_goal"), st.get("power")) == ("fast", "boost")
    assert settings_mod.coerce("performance_goal", "turbo") == "balanced"
    # a settings-like dict without the new key (older callers, tests): the goal still reads from power
    assert settings_mod.goal({"power": "boost"}) == "fast" and settings_mod.goal({}) == "balanced"
    assert settings_mod.goal({"performance_goal": "quiet", "power": "boost"}) == "quiet"
    # a file that has both keys: the goal is the only setting that decides
    p = _settings_file(tmp_path, power="boost", performance_goal="quiet")
    assert settings_mod.Settings(p).get("power") == "balanced"


# ---------- fast ----------
def test_fast_ignores_manual_workers_and_uses_all_threads(monkeypatch):
    monkeypatch.setattr(indexer.os, "cpu_count", lambda: 16)
    p = indexer.plan(FakeSettings(performance_goal="fast", workers=3), [], ssd=True)
    assert (p["text_workers"], p["text_workers_idle"], p["model_threads"]) == (16, 16, 16)
    assert p["goal"] == "fast"
    assert indexer.plan(FakeSettings(performance_goal="balanced", workers=3), [], ssd=True)["text_workers"] == 3
    lim = g.op_limits(g.FULL, p, smp(free_mb=64000), g.Decision(g.FULL, ""),
                      FakeSettings(performance_goal="fast", workers=3))
    assert lim["readers"]["user"] == 16                                 # the manual 3 isn't used
    assert lim["photo"]["cpu"] == 16 and lim["photo"]["effective"] == 16    # #16's half-thread cap is lifted
    calm = g.op_limits(g.FULL, indexer.plan(FakeSettings(), [], ssd=True), smp(free_mb=64000),
                       g.Decision(g.FULL, ""), FakeSettings())
    assert calm["photo"]["cpu"] == 8


def test_fast_steps_down_under_pressure():
    assert brain(performance_goal="fast").decide(smp()).level == g.FULL
    assert brain(performance_goal="fast").decide(smp(cpu=90.0)).level == g.GENTLE        # others need the CPU
    assert brain(performance_goal="fast").decide(smp(free_mb=2500)).level == g.LIGHT     # memory getting tight
    assert brain(performance_goal="fast").decide(smp(free_mb=1000)).level == g.PAUSED    # low memory: paused
    assert brain(performance_goal="fast").decide(smp(hung=True)).level == g.PAUSED       # a frozen app: paused
    plan = {"cpu": 16, "walk_threads": 32, "text_workers": 16, "text_workers_idle": 16, "model_threads": 16}
    light = g.op_limits(g.LIGHT, plan, smp(free_mb=2500), g.Decision(g.LIGHT, ""), FakeSettings(performance_goal="fast"))
    assert light["readers"]["effective"] == 1 and light["photo"]["effective"] == 1


# ---------- quiet (A20) ----------
def test_quiet_steps_down_earlier():
    def run(goal, **kw):
        apps = FakeApps()
        b = brain(apps, performance_goal=goal)
        d = None
        for t in range(0, 40, 2):
            d = b.decide(smp(t, find_cpu=10.0, foreground="editor.exe", **kw))
        return d, apps
    d, apps = run("quiet", cpu=75.0)                    # others' CPU 65% (Find's own 10% doesn't count)
    assert d.level == g.LIGHT and "Quiet" in d.reason and not apps.lags
    d, apps = run("balanced", cpu=75.0)
    assert d.level == g.GENTLE and not apps.lags
    d, apps = run("quiet", thermal=93.0)               # Windows holds the processor at 93%
    assert d.level == g.LIGHT and not apps.lags
    assert run("balanced", thermal=93.0)[0].level == g.GENTLE
    d, apps = run("quiet", disk_ms=35.0)               # 35 ms a transfer: the walk slows, the level doesn't
    assert d.io_slow and d.level == g.GENTLE and not apps.lags
    d, _ = run("balanced", disk_ms=35.0)
    assert not d.io_slow
    d, _ = run("quiet", disk_busy=75.0)
    assert d.io_slow and d.level == g.GENTLE
    # a lag is still learned at the standard threshold only, whatever the goal
    d, apps = run("quiet", cpu=97.0)
    assert d.level == g.PAUSED and len(apps.lags) == 1


def test_back_at_quiet_the_cpu_rule_waits_its_full_on_for_again():
    b = brain(performance_goal="quiet")
    busy = dict(cpu=75.0, find_cpu=10.0)                 # others' CPU 65%
    for t in (0, 2):                                     # counting towards ON_FOR, not on yet
        assert b.decide(smp(t, **busy)).level == g.GENTLE
    b.settings.kw["performance_goal"] = "balanced"
    assert b.decide(smp(3, **busy)).level == g.GENTLE    # another goal: the half-counted wait is forgotten
    b.settings.kw["performance_goal"] = "quiet"
    assert b.decide(smp(4, **busy)).level == g.GENTLE    # not on at once (it would be, counted from t=0)
    assert b.decide(smp(6, **busy)).level == g.GENTLE
    assert b.decide(smp(8, **busy)).level == g.LIGHT     # ON_FOR (4 s) from t=4


def test_quiet_waits_twice_as_long_to_step_up_and_keeps_background_work_off_the_gpu():
    b = brain(performance_goal="quiet")
    assert b.decide(smp(0, battery_saver=True)).level == g.LIGHT
    t, lvl = 0, g.LIGHT
    while lvl != g.GENTLE and t < 400:
        t += 2
        lvl = b.decide(smp(t)).level
    b2 = brain(performance_goal="balanced")
    b2.decide(smp(0, battery_saver=True))
    t2, lvl = 0, g.LIGHT
    while lvl != g.GENTLE and t2 < 400:
        t2 += 2
        lvl = b2.decide(smp(t2)).level
    assert t - t2 >= g.LIMITS["STEP_UP_AFTER"] - 2
    assert brain(performance_goal="quiet").decide(smp()).gpu_background is False
    assert brain(performance_goal="balanced").decide(smp()).gpu_background is True
    # the user's override beats the goal (§8b rule 0)
    assert brain(performance_goal="quiet", gpu_background="on").decide(smp()).gpu_background is True
    assert brain(performance_goal="fast", gpu_background="off").decide(smp()).gpu_background is False


# ---------- overrides and safety limits (A19) ----------
def test_override_never_crosses_safety_limit():
    plan = {"cpu": 16, "walk_threads": 32, "text_workers": 14, "text_workers_idle": 15, "model_threads": 8}
    lim = g.op_limits(g.FULL, plan, smp(free_mb=2400), g.Decision(g.FULL, ""), FakeSettings(workers=64))
    assert lim["readers"]["effective"] == 3 and lim["readers"]["by"] == "memory"   # 1.5 GB stays for Windows
    # the graphics card forced on, under quiet: still not past the reserve (max(512 MB, 15% of free))
    on = FakeSettings(performance_goal="quiet", gpu_background="on")
    d = brain(gpu_background="on", performance_goal="quiet").decide(smp(gpu_mem={"free_mb": 1400}))
    assert d.gpu_background is True
    assert g.op_limits(g.GENTLE, plan, smp(gpu_mem={"free_mb": 1400}), d, on)["vision"]["gpu"] == 0
    assert g.op_limits(g.GENTLE, plan, smp(gpu_mem={"free_mb": 2000}), d, on)["vision"]["gpu"] == 1
    big = FakeSettings(gpu_reserve_min_mb=1500, gpu_background="on")
    assert g.op_limits(g.GENTLE, plan, smp(gpu_mem={"free_mb": 2000}), d, big)["vision"]["gpu"] == 0
    # ... nor past battery saver or a creative app in front
    d = brain(gpu_background="on").decide(smp(battery_saver=True))
    assert d.gpu is False
    # the reserve minimum can only raise the reserve
    assert settings_mod.coerce("gpu_reserve_min_mb", 100) == 512
    assert settings_mod.coerce("gpu_reserve_min_mb", 99999) == 4096
    assert g.gpu_reserve_mb(3072, FakeSettings()) == 512 and g.gpu_reserve_mb(10000, FakeSettings()) == 1500
    assert g.gpu_reserve_mb(3072, FakeSettings(gpu_reserve_min_mb=100)) == 512
    # pause rules and low memory hold whatever the goal and the overrides
    for kw in (dict(battery=True), dict(call=True), dict(presentation=True), dict(free_mb=1000)):
        d = brain(performance_goal="fast", gpu_background="on", workers=64, pause_on_battery=True,
                  pause_on_call=True).decide(smp(**kw))
        assert d.level == g.PAUSED, kw
    # a profile override narrows or redirects the classes; it isn't a resource
    classes = profile.classify({"cores": 8, "avx2": True, "ram_gb": 16, "ssd": True})
    eff = profile.effective(classes, FakeSettings(profile_override_cpu="efficiency", profile_override_gpu="balanced"))
    assert eff["cpu"] == "efficiency" and eff["gpu"] == {"onnx": "balanced", "llamacpp": "balanced"}
    assert eff["memory"] == classes["memory"] and "you chose" in eff["why"]["cpu"].lower()
    assert profile.effective(classes, FakeSettings())["cpu"] == classes["cpu"]


def test_graphics_card_off_beats_a_forced_directml_for_meaning():
    full = g.Decision(g.FULL, "")
    quiet = g.Decision(g.FULL, "", gpu_background=False)
    S = FakeSettings
    assert indexer.text_gpu(g.FULL, full, S(backend_text="directml", gpu_background="off")) is False
    assert indexer.text_gpu(g.FULL, full, S(backend_text="auto", gpu_background="off")) is False
    assert indexer.text_gpu(g.FULL, quiet, S(backend_text="directml")) is True       # an override beats the goal
    assert indexer.text_gpu(g.FULL, quiet, S(backend_text="auto")) is False          # quiet on auto: processor
    assert indexer.text_gpu(g.FULL, full, S(backend_text="auto")) is True
    assert indexer.text_gpu(g.FULL, full, S(backend_text="cpu", gpu_background="on")) is False
    assert indexer.text_gpu(g.GENTLE, full, S(backend_text="directml", gpu_background="on")) is False
    saver = g.Decision(g.FULL, "", gpu=False)                                         # battery saver / creative app
    assert indexer.text_gpu(g.FULL, saver, S(backend_text="directml", gpu_background="on")) is False
    # the Performance page says so
    from nobadfind import performance
    pc = {"backends": {"onnx": ["cpu", "directml"], "llamacpp": ["cpu"]}}
    rows = performance.state(S(backend_text="directml", gpu_background="off"), pc, {"cpu": 8}, "llama-cpu")["rows"]
    assert rows["backend_text"]["auto"] == "cpu" and "Off" in rows["backend_text"]["why"]
    assert rows["backend_text"]["note"].startswith("The graphics card for background work is Off, and Off wins")
    rows = performance.state(S(gpu_background="on", performance_goal="quiet"), pc, {"cpu": 8}, "llama-cpu")["rows"]
    assert rows["backend_text"]["auto"] == "directml" and rows["backend_text"]["note"] == ""


def test_reset_safe_defaults_resets_and_keeps(tmp_path):
    a, store, st = _api(tmp_path, str(tmp_path / "s.json"))
    overrides = {"performance_goal": "fast", "gpu_background": "off", "backend_text": "cpu",
                 "backend_photos": "cpu", "backend_talk": "cpu", "variant_siglip2-base": "fp32-vision",
                 "workers": 5, "profile_override_gpu": "compatibility", "profile_override_cpu": "efficiency",
                 "profile_override_storage": "efficiency", "profile_override_memory": "efficiency",
                 "gpu_reserve_min_mb": 2048}
    kept = {"text_model": "gte-small", "photo_model": "siglip2-base", "roots": [str(tmp_path)],
            "scope": "custom", "include_secrets": True, "search_history": False, "exclude": [str(tmp_path / "x")],
            "safety_net": False}
    st.update(dict(overrides, **kept))
    store.set_meta("vec_model", "gte-small")
    r = a.reset_safe_defaults()
    assert r["ok"] is True
    assert r["reset"] == ["performance_goal", "gpu_background", "backend_photos", "backend_text", "backend_talk",
                          "variant_siglip2-base", "workers", "profile_override_gpu", "profile_override_cpu",
                          "profile_override_storage", "profile_override_memory", "gpu_reserve_min_mb"]
    assert r["kept"] == ["index", "models", "privacy", "folders", "learned_apps"]
    for k in overrides:
        assert st.get(k) == DEFAULTS[k], k
    assert st.get("power") == "balanced"
    for k, v in kept.items():
        assert st.get(k) == v, k
    assert store.meta("vec_model") == "gte-small"
    assert "replan" in a._indexer.calls
    store.close()


def test_performance_state_says_what_auto_would_pick_and_why(tmp_path, monkeypatch):
    from nobadfind import hardware as hw
    monkeypatch.setattr(hw, "scan", lambda: {"cores": 8, "threads": 16, "avx2": True, "ram_gb": 16, "ssd": True,
                                             "gpus": [], "backends": {"onnx": ["cpu", "directml"],
                                                                      "llamacpp": ["cpu"]}})
    a, store, st = _api(tmp_path, str(tmp_path / "s.json"))
    r = a.performance_state()
    assert r["goal"] == "balanced"
    rows = r["rows"]
    assert set(rows) == {"gpu_background", "backend_photos", "backend_text", "backend_talk", "variant_siglip2-base",
                         "workers", "profile_override_gpu", "profile_override_cpu", "profile_override_storage",
                         "profile_override_memory", "gpu_reserve_min_mb"}
    for k, row in rows.items():
        assert row["why"] and "auto" in row and "value" in row, k
    assert rows["backend_text"]["options"] == ["auto", "cpu", "directml"]
    assert rows["profile_override_cpu"]["auto"] == "performance"
    assert rows["workers"]["note"] == ""
    # what auto would pick, not the number the user set (the plan holds that one)
    from nobadfind import performance
    monkeypatch.setattr(performance.os, "cpu_count", lambda: 16)
    st.update({"workers": 3})
    assert a.performance_state()["rows"]["workers"]["auto"] == 15
    plan_3 = {"cpu": 16, "text_workers": 3, "text_workers_idle": 3, "ssd": True}
    assert performance.state(st, {}, plan_3, "llama-cpu")["rows"]["workers"]["auto"] == 15
    hdd = performance.state(st, {}, dict(plan_3, ssd=False), "llama-cpu")["rows"]["workers"]
    assert hdd["auto"] == 2 and "spinning disk" in hdd["why"]
    st.update({"workers": 0})
    # overrides that nothing reads yet say so (UI text never claims more than is built)
    assert a.performance_state()["rows"]["profile_override_cpu"]["note"].startswith("Not used yet")
    st.update({"performance_goal": "quiet"})
    assert a.performance_state()["rows"]["gpu_background"]["auto"] == "off"
    st.update({"performance_goal": "fast", "workers": 4})
    w = a.performance_state()["rows"]["workers"]
    assert w["value"] == 4 and "Fast" in w["note"]
    assert settings_mod.coerce("backend_text", "cuda") == "auto"         # no CUDA build in this version
    st.update({"backend_talk": "vulkan"})                                # forced, not installed here: says so
    assert a.performance_state()["rows"]["backend_talk"]["note"] == (
        "Vulkan isn't available on this PC now, so talk about a photo uses the processor.")
    store.close()
