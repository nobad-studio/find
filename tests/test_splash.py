"""0.9.0: the start-up card shows the moment NobadFind.exe starts a window, and goes when the window is up."""
import sys
import time

import pytest

from nobadfind import splash


def test_only_starts_that_open_the_main_window_get_one(monkeypatch):
    monkeypatch.delenv("NOBAD_FIND_NO_SPLASH", raising=False)
    if sys.platform != "win32":
        assert splash.wanted(["NobadFind.exe"]) is False
        return
    assert splash.wanted(["NobadFind.exe"]) is True
    assert splash.wanted(["NobadFind.exe", "--page", "settings"]) is True
    for flag in ("--background", "--engine", "--bar", "--uninstall", "--wsearch=demand", "--version"):
        assert splash.wanted(["NobadFind.exe", flag]) is False, flag
    monkeypatch.setenv("NOBAD_FIND_NO_SPLASH", "1")
    assert splash.wanted(["NobadFind.exe"]) is False


@pytest.mark.skipif(sys.platform != "win32", reason="a Win32 window")
def test_it_shows_and_goes(monkeypatch):
    monkeypatch.delenv("NOBAD_FIND_NO_SPLASH", raising=False)
    s = splash.show(["NobadFind.exe"])
    assert s is not None and s.hwnd
    assert splash.show(["NobadFind.exe"]) is s                 # one at a time
    splash.close()
    deadline = time.time() + 3
    while s.hwnd and time.time() < deadline:
        time.sleep(0.02)
    assert s.hwnd is None
    splash.close()                                              # again: nothing happens


def test_the_window_showing_closes_it(tmp_path, monkeypatch):
    from tests.test_engine import make
    closed = []
    monkeypatch.setattr(splash, "close", lambda: closed.append(1))
    w, api, ix, ev, conn, stop = make(tmp_path)
    w.start()
    api.ui_shown()
    assert closed
