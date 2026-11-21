"""The engine's tray icon: the menu, the tooltip and what a click does (the Win32 loop itself is tray.Tray)."""
import os

from nobadfind import const, settings, tray


def test_menu_has_the_items_and_pause_follows_the_state():
    items = [label for _id, label in tray.menu(paused=False) if label]
    assert items == ["Open NOBAD Find", "Pause for 1 hour", "Settings", "Index", "Quit NOBAD Find"]   # 0.9.1: no bar
    bar = [label for _id, label in tray.menu(paused=False, bar=True) if label]
    assert bar == ["Open NOBAD Find", "Quick find bar", "Pause for 1 hour", "Settings", "Index", "Quit NOBAD Find"]
    labels = dict(tray.menu(paused=True))
    assert tray.CMD["resume"] in labels and labels[tray.CMD["resume"]] == "Resume"
    assert tray.CMD["pause"] not in labels


def test_tooltip_shows_the_level_and_the_files():
    assert tray.tooltip({"level": "gentle", "files": 12345, "paused": ""}) == "NOBAD Find: Gentle, 12,345 files"
    assert tray.tooltip({"level": "paused", "files": 3, "paused": "on battery"}) == "NOBAD Find: Paused (on battery), 3 files"
    assert len(tray.tooltip({"level": "full", "files": 1, "paused": "x" * 400})) < 128     # Windows' limit


def test_clicks_and_commands_become_actions():
    got = []
    t = tray.Tray(got.append, tip=lambda: "x", paused=lambda: False)
    t._on_click(tray.WM_LBUTTONUP)
    t._on_command(tray.CMD["settings"])
    t._on_command(tray.CMD["quit"])
    t._on_command(9999)                                   # not ours: ignored
    assert got == ["open", "settings", "quit"]


def test_a_failing_left_click_is_logged_with_its_reason(monkeypatch):
    """A left click used to raise into the window procedure; now it is caught and logged like a menu item."""
    logged = []
    monkeypatch.setattr(tray, "log", lambda text, level="info": logged.append((level, text)))

    def boom(action):
        raise RuntimeError("pipe gone")
    tray.Tray(boom, tip=lambda: "x", paused=lambda: False)._on_click(tray.WM_LBUTTONUP)
    assert logged == [("warn", "tray action open failed: RuntimeError: pipe gone")]


def test_the_engine_routes_the_bars_alt_enter_through_its_launcher(tmp_path):
    import threading
    from nobadfind import engine
    from nobadfind.api import Api
    from nobadfind.rpc.events import Events
    st = settings.Settings(str(tmp_path / "s.json"))
    ix = type("Ix", (), {"set_idle": lambda self, v: None, "warm_models": lambda self: None})()
    api = Api(None, st, ix, None)
    ev = Events(lambda: [], lambda c: None, api)
    w = engine.Wiring(api, st, ix, ev, threading.Event(), ui_pids=lambda: set(), dialog=lambda: "x",
                      trim=lambda: None)
    assert ev.open_window == w.ui.show and w.ui.can_show == ev.can_show


def test_tray_setting_defaults_on(tmp_path):
    assert const.DEFAULTS["tray"] is True
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"tray": "yes"})                            # not a bool: refused
    assert st.get("tray") is True


def test_the_icon_file_is_there():
    assert os.path.isfile(tray.icon_path()) or tray.icon_path() == ""
