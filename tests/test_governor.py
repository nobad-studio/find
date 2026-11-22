import datetime

from nobadfind import governor as g
from nobadfind.governor import Brain, Sample


class FakeSettings:
    def __init__(self, **kw):
        self.kw = kw

    def get(self, key):
        return self.kw.get(key)


class FakeApps:
    def __init__(self, learned=None):
        self.learned = learned
        self.lags = []

    def start_level(self, exe):
        return self.learned

    def record_lag(self, exe, sample):
        self.lags.append((exe, sample))


def smp(t=0.0, **kw):
    base = dict(t=t, cpu=20.0, gpu=None, mem_load=40, free_mb=8000, find_cpu=0.0,
                foreground="", game=False, presentation=False, hung=False,
                battery=False, call=False, idle_s=0.0)
    base.update(kw)
    return Sample(**base)


def brain(apps=None, cpu_count=8, **settings):
    return Brain(FakeSettings(**settings), apps or FakeApps(), cpu_count=cpu_count)


GAME = dict(foreground="forzahorizon5.exe", game=True)


def test_game_with_headroom_is_light():
    d = brain().decide(smp(**GAME))
    assert d.level == g.LIGHT
    assert d.reason == "Light: forzahorizon5 is running, so NOBAD Find uses 1 worker"


def test_game_and_hot_cpu_for_10s_pauses():
    b = brain()
    for t in range(0, 10):  # 0..9 s hot: held for 9 s only
        assert b.decide(smp(t, cpu=92, **GAME)).level == g.LIGHT
    d = b.decide(smp(10, cpu=92, **GAME))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: the PC is busy (CPU 92%)"


def test_cool_sample_resets_hot_timer():
    b = brain()
    for t in range(0, 9):
        b.decide(smp(t, cpu=92, **GAME))
    b.decide(smp(9, cpu=30, **GAME))
    assert b.decide(smp(10, cpu=92, **GAME)).level == g.LIGHT
    assert b.decide(smp(19, cpu=92, **GAME)).level == g.LIGHT
    assert b.decide(smp(20, cpu=92, **GAME)).level == g.PAUSED


def test_presentation_always_pauses():
    d = brain().decide(smp(presentation=True, idle_s=999))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: presentation or quiet time"


def test_battery_and_call_follow_settings():
    on = brain(pause_on_battery=True, pause_on_call=True)
    assert on.decide(smp(battery=True)).reason == "Paused: on battery"
    assert on.decide(smp(1, call=True)).reason == "Paused: microphone or camera in use"
    off = brain(pause_on_battery=False, pause_on_call=False)
    assert off.decide(smp(battery=True, call=True)).level == g.GENTLE


def test_games_mode_always_and_off():
    d = brain(games_mode="always").decide(smp(**GAME))
    assert d.level == g.PAUSED
    d = brain(games_mode="off").decide(smp(idle_s=0, **GAME))
    assert d.level == g.GENTLE
    d = brain(games_mode="off").decide(smp(idle_s=200, **GAME))
    assert d.level == g.FULL


def test_unknown_games_mode_is_smart():
    assert brain(games_mode="bogus").decide(smp(**GAME)).level == g.LIGHT


def test_step_up_one_level_after_30s():
    b = brain()
    assert b.decide(smp(0, presentation=True)).level == g.PAUSED
    # conditions clear; user is using the PC, so GENTLE is allowed
    assert b.decide(smp(1)).level == g.PAUSED
    assert b.decide(smp(30)).level == g.PAUSED  # only 29 s allowed
    assert b.decide(smp(31)).level == g.LIGHT
    assert b.decide(smp(60)).level == g.LIGHT
    assert b.decide(smp(61)).level == g.GENTLE


def test_step_down_is_immediate():
    b = brain()
    b.decide(smp(0))
    assert b.decide(smp(1, presentation=True)).level == g.PAUSED


def test_away_with_headroom_is_full():
    d = brain().decide(smp(idle_s=300))
    assert d.level == g.FULL
    assert d.reason == "Full: you're away"
    d = brain().decide(smp(idle_s=300, cpu=60))
    assert d.level == g.GENTLE
    assert d.reason == "Gentle: you're using the PC"


def test_unknown_gpu_is_ignored():
    b = brain()
    for t in range(0, 40):
        d = b.decide(smp(t, cpu=30, gpu=None))
    assert d.level == g.GENTLE


def test_hot_gpu_pauses():
    b = brain()
    b.decide(smp(0, gpu=90))
    assert b.decide(smp(10, gpu=90)).level == g.PAUSED


def test_low_memory_pauses():
    d = brain().decide(smp(free_mb=900))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: low on memory (900 MB free)"


def test_hung_foreground_records_lag_once():
    apps = FakeApps()
    b = brain(apps)
    w = dict(foreground="game.exe", game=True, find_cpu=10.0)      # NOBAD Find is working
    d = b.decide(smp(0, hung=True, **w))
    assert d.level == g.PAUSED
    assert d.reason == "Paused: game isn't responding"
    b.decide(smp(1, hung=True, **w))
    assert len(apps.lags) == 1
    assert apps.lags[0][0] == "game.exe"
    b.decide(smp(2, **w))
    b.decide(smp(3, hung=True, **w))
    assert len(apps.lags) == 2


def test_no_lag_record_without_foreground():
    apps = FakeApps()
    brain(apps).decide(smp(0, free_mb=500))
    assert apps.lags == []


def test_learned_start_level_used():
    d = brain(FakeApps(learned=g.PAUSED)).decide(smp(**GAME))
    assert d.level == g.PAUSED
    assert "learned to make room for forzahorizon5" in d.reason


def test_user_pause_until():
    b = brain()
    b.pause_until = 1_000_000.0
    d = b.decide(smp(999_000.0, idle_s=999))
    hhmm = datetime.datetime.fromtimestamp(1_000_000.0).strftime("%H:%M")
    assert d.level == g.PAUSED
    assert d.reason == f"Paused: you asked for a break until {hhmm}"
    assert b.decide(smp(1_000_001.0)).level == g.PAUSED  # step-up delay still applies
    assert b.decide(smp(1_000_040.0)).level == g.LIGHT


def test_workers_for_levels():
    plan = {"text_workers_idle": 4, "text_workers": 2}
    assert g.workers_for(g.FULL, plan) == 4
    assert g.workers_for(g.GENTLE, plan) == 2
    assert g.workers_for(g.LIGHT, plan) == 1
    assert g.workers_for(g.PAUSED, plan) == 0


def test_hot_timer_is_continuous_across_other_pauses():
    apps = FakeApps()
    b = brain(apps)
    for t in range(0, 6):
        b.decide(smp(t, cpu=92, foreground="game.exe", game=True))
    for t in range(6, 126):
        b.decide(smp(t, cpu=20, presentation=True, foreground="game.exe", game=True))
    d = b.decide(smp(126, cpu=92, foreground="game.exe", game=True))
    assert d.level != g.PAUSED or "busy" not in d.reason
    assert apps.lags == []


def test_unknown_cpu_never_gives_full():
    assert brain().decide(smp(cpu=None, idle_s=300)).level == g.GENTLE


def test_lag_recorded_when_app_becomes_known_mid_lag():
    apps = FakeApps()
    b = brain(apps)
    b.decide(smp(0, free_mb=500, find_cpu=10.0))
    assert apps.lags == []
    b.decide(smp(1, free_mb=500, foreground="game.exe", game=True, find_cpu=10.0))
    assert [e for e, _ in apps.lags] == ["game.exe"]
    b.decide(smp(2, free_mb=500, foreground="game.exe", game=True, find_cpu=10.0))
    assert len(apps.lags) == 1


def test_finds_own_cpu_does_not_count_as_you_using_the_pc():
    """I-3: away, the PC at 85% of which NOBAD Find itself is 80%: Full holds (no flapping, no busy pause)."""
    apps = FakeApps()
    b = brain(apps)
    levels = {b.decide(smp(t, cpu=85.0, find_cpu=80.0, idle_s=300 + t, foreground="code.exe")).level
              for t in range(0, 62, 2)}
    assert levels == {g.FULL} and apps.lags == []


def test_busy_reason_shows_the_cpu_other_apps_use():
    b = brain()
    for t in range(0, 11):
        d = b.decide(smp(t, cpu=95.0, find_cpu=5.0))
    assert d.level == g.PAUSED and d.reason == "Paused: the PC is busy (CPU 90%)"


def test_no_lag_is_learned_while_find_is_not_working():
    """I-4: Find idle (window closed, nothing running): a hung app is not blamed on NOBAD Find."""
    apps = FakeApps()
    d = brain(apps).decide(smp(0, hung=True, foreground="word.exe", find_cpu=0.5))
    assert d.level == g.PAUSED and apps.lags == []            # still paused, just not learned


def test_no_lag_is_learned_about_finds_own_window():
    apps = FakeApps()
    b = brain(apps)
    d = b.decide(smp(0, hung=True, foreground="nobadfind.exe", foreground_is_self=True, find_cpu=40.0))
    assert d.level == g.PAUSED and apps.lags == []
    b.decide(smp(1, foreground="word.exe", find_cpu=40.0))
    b.decide(smp(2, hung=True, foreground="word.exe", find_cpu=40.0))
    assert [e for e, _ in apps.lags] == ["word.exe"]


def test_unknown_app_is_an_app_unless_it_is_a_game():
    """M-7: with no exe name, a non-game reason says "an app"; game reasons keep "a game"."""
    assert brain().decide(smp(hung=True)).reason == "Paused: an app isn't responding"
    assert brain(games_mode="always").decide(smp(game=True)).reason == "Paused: a game is running"
    assert brain().decide(smp(game=True)).reason.startswith("Light: a game is running")


def test_working_is_measured_in_cores_not_a_share_of_all_cpus():
    """Re-review: at Light (1 worker) on a 32-thread PC Find uses about 3% of all CPUs; that is one busy core, so
    a game that lags then is still learned. Half a core is the line."""
    apps = FakeApps()
    b = brain(apps, cpu_count=32)
    assert b.decide(smp(0, hung=True, find_cpu=3.2, **GAME)).level == g.PAUSED
    assert [e for e, _ in apps.lags] == ["forzahorizon5.exe"]
    idle = FakeApps()
    brain(idle, cpu_count=32).decide(smp(0, hung=True, find_cpu=0.5, **GAME))
    assert idle.lags == []


def test_fixed_level_for_measurements_wins_over_the_sensors():
    b = brain()
    b.fixed = g.LIGHT
    d = b.decide(smp(t=0, idle_s=999, cpu=1.0))
    assert d.level == g.LIGHT and "measurement" in d.reason
    b.fixed = g.FULL
    assert b.decide(smp(t=1, battery=True), ).level == g.FULL


# ---------- 2026-11-21: the combined state of Windows ----------
def run(b, t0, t1, step=2, **kw):
    """Decide every `step` seconds from t0 to t1 inclusive; the last Decision."""
    d = None
    for t in range(t0, t1 + 1, step):
        d = b.decide(smp(t, **kw))
    return d


def test_high_commit_lets_the_models_go_then_light_then_paused():
    b = brain()
    assert b.decide(smp(0, commit_pct=90.0)).release_models is False      # one sample isn't enough (ON_FOR)
    d = b.decide(smp(4, commit_pct=90.0))
    assert d.release_models is True and d.level == g.GENTLE               # step 1: the models go, same level
    assert b.decide(smp(6, commit_pct=90.0)).release_models is False      # once per episode
    assert run(b, 8, 22, commit_pct=90.0).level == g.GENTLE
    d = b.decide(smp(24, commit_pct=90.0))                                # 20 s after it turned on
    assert d.level == g.LIGHT
    assert d.reason == ("Light: Windows is close to the memory it can promise programs (commit 90%), "
                        "so NOBAD Find let go of its models and uses 1 worker")
    assert run(b, 26, 62, commit_pct=90.0).level == g.LIGHT
    d = b.decide(smp(64, commit_pct=91.0))                                # 60 s: still high
    assert d.level == g.PAUSED and "commit 91%" in d.reason


def test_commit_hysteresis_and_minimum_time():
    b = brain()
    run(b, 0, 24, commit_pct=90.0)                                        # on at 4, Light from 24
    assert b.decide(smp(26, commit_pct=82.0)).level == g.LIGHT            # between the lines: stays on
    assert run(b, 28, 36, commit_pct=70.0).level == g.LIGHT              # clear for 8 s only
    run(b, 38, 40, commit_pct=70.0)                                       # clear 12 s, on 36 s: off
    assert b.commit.on is False
    d = run(b, 42, 70, commit_pct=70.0)
    assert d.level == g.GENTLE                                            # then the usual 30 s step up


def test_commit_spikes_dont_flap():
    b = brain()
    for t in range(0, 120, 2):
        d = b.decide(smp(t, commit_pct=90.0 if t % 4 == 0 else 84.0))
        assert d.release_models is False and d.level == g.GENTLE


def test_unknown_commit_is_never_bad():
    d = run(brain(), 0, 120, commit_pct=None)
    assert d.level == g.GENTLE and d.release_models is False


def test_slow_disk_slows_the_walk_and_the_readers_not_the_level():
    b = brain()
    assert b.decide(smp(0, disk_ms=80.0)).io_slow is False
    d = b.decide(smp(4, disk_ms=80.0))
    assert d.io_slow is True and d.level == g.GENTLE
    assert d.reason == ("Gentle: you're using the PC; the disk is slow (80 ms a transfer), "
                        "so the file walk and the readers slow down")
    assert run(brain(), 0, 10, disk_busy=95.0, disk_ms=1.0).reason.endswith(
        "the disk is slow (busy 95% of the time), so the file walk and the readers slow down")
    assert run(b, 6, 30, disk_ms=5.0).io_slow is True                     # on for 26 s: the minimum is 30
    assert run(b, 32, 36, disk_ms=5.0).io_slow is False
    assert run(brain(), 0, 60, disk_ms=None, disk_busy=None).io_slow is False


def test_slow_disk_limits_walk_and_readers_but_not_photos():
    plan = {"cpu": 16, "walk_threads": 32, "text_workers": 8, "text_workers_idle": 15, "model_threads": 8}
    fine = g.op_limits(g.GENTLE, plan, smp(free_mb=12000), g.Decision(g.GENTLE, ""))
    slow = g.op_limits(g.GENTLE, plan, smp(free_mb=12000), g.Decision(g.GENTLE, "", io_slow=True))
    assert fine["walk"]["effective"] == 32 and slow["walk"]["effective"] == 8 and slow["walk"]["by"] == "governor"
    assert fine["readers"]["effective"] == 8 and slow["readers"]["effective"] == 4
    assert fine["photo"] == slow["photo"]


def test_battery_saver_is_light_without_the_graphics_card():
    b = brain()
    d = b.decide(smp(0, battery_saver=True, idle_s=999))
    assert d.level == g.LIGHT and d.gpu is False
    assert d.reason == "Light: battery saver is on, so NOBAD Find uses 1 worker and not the graphics card"
    assert b.decide(smp(20, battery_saver=False, idle_s=999)).gpu is False    # on 20 s: the minimum is 30
    assert run(b, 22, 40, battery_saver=False, idle_s=999).gpu is True
    assert run(brain(), 0, 40, battery_saver=None).gpu is True               # unknown: nothing changes


def test_thermal_pressure_is_one_level_down():
    b = brain()
    assert b.decide(smp(0, thermal=70.0)).level == g.GENTLE
    d = b.decide(smp(4, thermal=70.0))
    assert d.level == g.LIGHT
    assert d.reason == ("Light: Windows is holding the processor back to 70% of its speed to cool it, "
                        "so NOBAD Find works one level lower")
    assert run(brain(), 0, 4, thermal=70.0, idle_s=999).level == g.GENTLE  # Full -> Gentle
    assert run(brain(), 0, 60, thermal=100.0).level == g.GENTLE
    assert run(brain(), 0, 60, thermal=None).level == g.GENTLE
    assert run(b, 6, 60, thermal=98.0).level == g.LIGHT                      # not cool enough to clear (99)
    assert run(b, 62, 120, thermal=100.0).level == g.LIGHT                   # clear for 58 s: needs 60
    run(b, 122, 124, thermal=100.0)
    assert not b.thermal.on


def test_a_creative_app_in_front_is_light_without_the_graphics_card():
    b = brain()
    d = b.decide(smp(0, foreground="blender.exe", idle_s=999))
    assert d.level == g.LIGHT and d.gpu is False
    assert d.reason == "Light: blender is in front, so NOBAD Find uses 1 worker and leaves the graphics card to it"
    assert b.decide(smp(10, foreground="explorer.exe")).level == g.LIGHT      # minimum time in the state
    assert run(b, 12, 40, foreground="explorer.exe").gpu is True
    mine = brain(creative_apps=["myeditor.exe"])
    assert mine.decide(smp(0, foreground="myeditor.exe")).level == g.LIGHT
    assert brain(creative_apps=["myeditor.exe"]).decide(smp(0, foreground="blender.exe")).level == g.GENTLE
    assert brain(creative_apps=[]).decide(smp(0, foreground="blender.exe")).level == g.GENTLE
    own = brain(creative_apps=["nobadfind.exe"])
    assert own.decide(smp(0, foreground="nobadfind.exe", foreground_is_self=True)).gpu is True


def test_the_creative_apps_setting_is_checked():
    from nobadfind.const import CREATIVE_APPS, DEFAULTS
    from nobadfind.settings import coerce
    assert DEFAULTS["creative_apps"] == CREATIVE_APPS and "blender.exe" in CREATIVE_APPS
    assert coerce("creative_apps", ["Blender.EXE", " reaper.exe ", "C:\\x\\evil.exe", "notes.txt", 5, "blender.exe"]) \
        == ["blender.exe", "reaper.exe"]
    assert coerce("creative_apps", []) == []
    assert coerce("creative_apps", "blender.exe") == CREATIVE_APPS
    assert len(coerce("creative_apps", [f"app{i}.exe" for i in range(500)])) == 100


def test_a_game_still_wins_over_a_creative_app_rule():
    d = brain(games_mode="always").decide(smp(0, foreground="blender.exe", game=True))
    assert d.level == g.PAUSED and d.gpu is False


def test_the_old_rules_come_first():
    d = brain().decide(smp(0, presentation=True, battery_saver=True, foreground="blender.exe"))
    assert d.level == g.PAUSED and d.reason == "Paused: presentation or quiet time"
    d = brain().decide(smp(0, free_mb=900, battery_saver=True))
    assert d.reason == "Paused: low on memory (900 MB free)"


def test_limits_are_the_smallest_of_user_cpu_memory_and_governor():
    plan = {"cpu": 8, "walk_threads": 16, "text_workers": 6, "text_workers_idle": 7, "model_threads": 4}
    lim = g.op_limits(g.FULL, plan, smp(free_mb=16000), g.Decision(g.FULL, ""), FakeSettings(workers=3))
    assert lim["readers"] == {"user": 3, "cpu": 7, "memory": 3, "governor": 7, "effective": 3, "by": "user"}
    tight = g.op_limits(g.FULL, plan, smp(free_mb=2400), g.Decision(g.FULL, ""))
    assert tight["readers"]["effective"] == 3 and tight["readers"]["by"] == "memory"     # 900 MB spare / 300
    assert g.op_limits(g.PAUSED, plan, smp(), g.Decision(g.PAUSED, ""))["readers"]["effective"] == 0
    assert g.op_limits(g.LIGHT, plan, smp(), g.Decision(g.LIGHT, ""))["walk"]["effective"] == 4
    unknown = g.op_limits(g.FULL, plan, smp(free_mb=0), g.Decision(g.FULL, ""))
    assert unknown["readers"]["effective"] == 7                       # unknown memory doesn't limit
    assert g.op_limits(g.FULL, None, None, None)["walk"]["effective"] >= 1     # no plan yet: still sane


def test_vision_is_one_stream_and_only_with_the_graphics_card_free():
    plan = {"cpu": 8}
    ok = g.op_limits(g.GENTLE, plan, smp(free_mb=8000, gpu_mem={"free_mb": 4000}), g.Decision(g.GENTLE, ""))
    assert ok["vision"]["effective"] == 1
    busy = g.op_limits(g.GENTLE, plan, smp(free_mb=8000, gpu_mem={"free_mb": 500}), g.Decision(g.GENTLE, ""))
    assert busy["vision"]["effective"] == 0 and busy["vision"]["by"] == "gpu"
    saver = g.op_limits(g.LIGHT, plan, smp(free_mb=8000), g.Decision(g.LIGHT, "", gpu=False))
    assert saver["vision"]["effective"] == 0
    assert g.op_limits(g.GENTLE, plan, smp(free_mb=2000), g.Decision(g.GENTLE, ""))["vision"]["effective"] == 0
    off = g.op_limits(g.GENTLE, plan, smp(), g.Decision(g.GENTLE, ""), FakeSettings(photo_meaning=False))
    assert off["photo"]["effective"] == 0


def test_the_latch_needs_its_time_on_and_off():
    latch = g._Latch(on_for=4, off_for=10, hold=30)
    assert latch.update(0, True, False) is False and latch.update(3, True, False) is False and not latch.on
    assert latch.update(4, True, False) is True and latch.on
    latch.update(5, False, True)
    latch.update(20, False, True)
    assert latch.on                                   # clear for 15 s but on for only 16 s
    latch.update(34, False, True)
    assert not latch.on
