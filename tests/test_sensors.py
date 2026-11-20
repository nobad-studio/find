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
