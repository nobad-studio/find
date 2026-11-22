import time

import pytest

from nobadfind import winapi

win_only = pytest.mark.skipif(not winapi.WIN, reason="Windows only")


@win_only
def test_cpu_sampler_gives_a_percent():
    s = winapi.CpuSampler()
    s.percent()
    time.sleep(0.2)
    x = s.percent()
    assert x is not None and 0 <= x <= 100


@win_only
def test_memory_status_in_range():
    load, free = winapi.memory_status()
    assert 0 <= load <= 100
    assert free > 0


@win_only
def test_gpu_sampler_is_percent_or_none():
    s = winapi.GpuSampler()
    s.percent()
    time.sleep(0.3)
    x = s.percent()
    assert x is None or 0 <= x <= 100


@win_only
def test_foreground_exe_is_lowercase_name():
    r = winapi.foreground_exe()
    assert r == r.lower()
    assert "\\" not in r


@win_only
def test_foreground_hung_is_false_for_a_normal_desktop():
    assert winapi.foreground_hung() is False


def test_sensors_are_safe_off_windows(monkeypatch):
    monkeypatch.setattr(winapi, "WIN", False)
    assert winapi.CpuSampler().percent() is None
    assert winapi.GpuSampler().percent() is None
    assert winapi.memory_status() == (0, 0)
    assert winapi.foreground_exe() == ""
    assert winapi.foreground_hung() is False
    assert winapi.presentation_mode() is False
    assert winapi.fullscreen_game() is False


def test_a_stuck_full_screen_flag_isnt_a_game(monkeypatch):
    """0.9.1: Windows' "full-screen Direct3D" state can stay set with File Explorer in front; that held NOBAD Find
    at one worker all day. A game counts only when the window in front really fills its screen."""
    from nobadfind import winapi
    monkeypatch.setattr(winapi, "_notification_state", lambda: 3)
    monkeypatch.setattr(winapi, "foreground_covers_screen", lambda: False)
    assert winapi.fullscreen_game() is False and winapi.busy_fullscreen() is False
    monkeypatch.setattr(winapi, "foreground_covers_screen", lambda: True)
    assert winapi.fullscreen_game() is True
    monkeypatch.setattr(winapi, "_notification_state", lambda: 5)          # accepts notifications: no game
    assert winapi.fullscreen_game() is False


# ---------- 2026-11-21 sensors: each one fails to None (unknown), never to "bad" ----------
def test_new_sensors_are_none_off_windows(monkeypatch):
    monkeypatch.setattr(winapi, "WIN", False)
    assert winapi.commit_status() == (None, None)
    assert winapi.battery_saver() is None
    assert winapi.DiskSampler().read(["C:\\"]) == (None, None)
    assert winapi.ThermalSampler().read() is None
    assert winapi.GpuMemorySampler().read() is None
    assert winapi.PdhArray(["\\Nothing(*)\\At all"]).read() is None


class _Fake:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


@win_only
def test_pdh_that_cant_open_fails_to_none(monkeypatch):
    def boom():
        raise OSError("no pdh")
    monkeypatch.setattr(winapi, "_pdh_dll", boom)
    assert winapi.PdhArray([winapi._PDH_DISK_IDLE]).read() is None
    assert winapi.DiskSampler().read() == (None, None)
    assert winapi.ThermalSampler().read() is None
    assert winapi.GpuMemorySampler().read() is None
    assert winapi.GpuSampler().percent() is None


@win_only
def test_an_unknown_counter_path_fails_to_none():
    assert winapi.PdhArray(["\\No Such Object(*)\\No Such Counter"]).read() is None


@win_only
def test_commit_status_fails_to_none(monkeypatch):
    def boom(name, **k):
        raise OSError("no psapi")
    monkeypatch.setattr(winapi.ctypes, "WinDLL", boom)
    assert winapi.commit_status() == (None, None)


@win_only
def test_commit_status_is_a_percent_and_mb():
    pct, free = winapi.commit_status()
    assert 0 < pct <= 100 and free >= 0


@win_only
def test_battery_saver_fails_to_none(monkeypatch):
    class K:
        @staticmethod
        def GetSystemPowerStatus(p):
            return 0
    monkeypatch.setattr(winapi, "k32", K())
    assert winapi.battery_saver() is None
    monkeypatch.undo()
    assert winapi.battery_saver() in (True, False)


def test_disk_sampler_picks_the_indexed_drives_disk(monkeypatch):
    monkeypatch.setattr(winapi, "WIN", True)
    d = winapi.DiskSampler.__new__(winapi.DiskSampler)
    d._pdh = _Fake({winapi._PDH_DISK_IDLE: {"0 C: E:": 40.0, "1 D:": 95.0, "_Total": 70.0},
                    winapi._PDH_DISK_SEC: {"0 C: E:": 0.080, "1 D:": 0.002, "_Total": 0.04}})
    assert d.read(["C:\\"]) == (60.0, 80.0)
    assert d.read(["d:\\"]) == (5.0, 2.0)
    assert d.read([]) == (60.0, 80.0)                    # no drive known: the worst disk, never _Total
    assert d.read(["Z:\\"]) == (60.0, 80.0)
    d._pdh = _Fake(None)
    assert d.read(["C:\\"]) == (None, None)
    d._pdh = _Fake({winapi._PDH_DISK_IDLE: {"_Total": 1.0}})
    assert d.read(["C:\\"]) == (None, None)


def test_thermal_sampler_reads_the_passive_limit(monkeypatch):
    monkeypatch.setattr(winapi, "WIN", True)
    t = winapi.ThermalSampler.__new__(winapi.ThermalSampler)
    t._pdh = _Fake({winapi._PDH_PASSIVE: {"\\_TZ.THRM": 100.0, "\\_TZ.CPUZ": 72.0}})
    assert t.read() == 72.0
    t._pdh = _Fake({winapi._PDH_PASSIVE: {"\\_TZ.THRM": 100.0}, winapi._PDH_THROTTLE: {"\\_TZ.THRM": 1.0}})
    assert t.read() == 99.0
    t._pdh = _Fake({winapi._PDH_THROTTLE: {"\\_TZ.THRM": 0.0}})
    assert t.read() is None                              # no passive limit: unknown
    t._pdh = _Fake(None)
    assert t.read() is None


def test_gpu_memory_sampler_and_the_budget(monkeypatch):
    from nobadfind import hardware
    monkeypatch.setattr(winapi, "WIN", True)
    m = winapi.GpuMemorySampler.__new__(winapi.GpuMemorySampler)
    m._pdh = _Fake({winapi._PDH_GPU_DEDICATED: {"luid_0x00000000_0x0000DD85_phys_0": 0.0,
                                                "luid_0x00000000_0x0000AA11_phys_0": 2048 * 1048576.0},
                    winapi._PDH_GPU_SHARED: {"luid_0x00000000_0x0000DD85_phys_0": 700 * 1048576.0,
                                             "garbage": 5.0}})
    used = m.read()
    assert used == {"0x00000000_0x0000dd85": {"dedicated_mb": 0, "shared_mb": 700},
                    "0x00000000_0x0000aa11": {"dedicated_mb": 2048, "shared_mb": 0}}
    iris = {"luid": "0x00000000_0x0000dd85", "dedicated_mb": 128, "shared_mb": 8038, "integrated": True}
    assert hardware.gpu_memory_free(iris, used) == {"kind": "shared", "free_mb": 7338, "used_mb": 700,
                                                     "budget_mb": 8038}      # Intel iGPU: shared memory only
    rtx = {"luid": "0x00000000_0x0000aa11", "dedicated_mb": 8192, "shared_mb": 8000, "integrated": False}
    assert hardware.gpu_memory_free(rtx, used)["free_mb"] == 6144
    assert hardware.gpu_memory_free(None, used) is None
    assert hardware.gpu_memory_free(iris, None) is None
    assert hardware.gpu_memory_free(dict(iris, luid="0x1_0x2"), used) is None
    m._pdh = _Fake(None)
    assert m.read() is None


def test_adapter_memory_fails_to_none(monkeypatch):
    from nobadfind import hardware
    monkeypatch.setattr(hardware, "_mem_cache", None)
    monkeypatch.setattr(hardware, "adapters", lambda full=False: [])
    assert hardware.adapter_memory() is None
