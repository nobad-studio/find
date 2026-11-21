"""The engine starts the Flutter UI when a hotkey or the tray asks for a window and no UI is connected."""
import os

from nobadfind import uilaunch


class Events:
    def __init__(self):
        self.shown = []

    def show(self, what, text=None):
        self.shown.append(what)


def test_ui_exe_from_the_env_then_the_dev_build(tmp_path, monkeypatch):
    exe = tmp_path / "nobad_find.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(uilaunch.sys, "frozen", False, raising=False)
    monkeypatch.setenv("NOBAD_FIND_UI_EXE", str(exe))
    assert uilaunch.ui_exe() == str(exe)
    monkeypatch.setenv("NOBAD_FIND_UI_EXE", str(tmp_path / "missing.exe"))
    dev = uilaunch.DEV_BUILD
    assert uilaunch.ui_exe() == (dev if os.path.isfile(dev) else None)
    assert dev.endswith(os.path.join("ui_flutter", "build", "windows", "x64", "runner", "Release", "nobad_find.exe"))


def test_frozen_engine_uses_the_ui_next_to_it(tmp_path, monkeypatch):
    engine = tmp_path / "NobadFind.exe"
    (tmp_path / "nobad_find.exe").write_bytes(b"MZ")
    monkeypatch.setattr(uilaunch.sys, "frozen", True, raising=False)
    monkeypatch.setattr(uilaunch.sys, "executable", str(engine))
    monkeypatch.delenv("NOBAD_FIND_UI_EXE", raising=False)
    assert uilaunch.ui_exe() == str(tmp_path / "nobad_find.exe")


def test_a_window_request_with_no_ui_starts_it_on_that_page():
    started, ev = [], Events()
    clock = [100.0]
    ui = uilaunch.Launcher(ev, connected=lambda: False, exe=lambda: r"C:\ui\nobad_find.exe",
                           start=started.append, clock=lambda: clock[0])
    ui.show("main")
    assert started == [[r"C:\ui\nobad_find.exe", "--page", "search"]] and ev.shown == []
    ui.show("settings")                                     # still starting: not a second copy
    assert len(started) == 1
    clock[0] += 20
    ui.show("bar")
    assert started[-1] == [r"C:\ui\nobad_find.exe", "--bar"]
    clock[0] += 20
    ui.show("index")
    assert started[-1][-2:] == ["--page", "index"]


def test_a_connected_ui_just_gets_the_show_event():
    started, ev = [], Events()
    ui = uilaunch.Launcher(ev, connected=lambda: True, exe=lambda: "x.exe", start=started.append)
    ui.show("settings")
    assert ev.shown == ["settings"] and started == []


def test_no_ui_installed_says_so_once():
    notes, ev = [], Events()
    ui = uilaunch.Launcher(ev, connected=lambda: False, exe=lambda: None, start=lambda a: None, note=notes.append)
    ui.show("main")
    ui.show("main")
    assert len(notes) == 1 and ev.shown == []


# ----- the tray's "Open NOBAD Find" did nothing (0.9.3 bug report) -----
class Conn:
    """A connected UI process as rpc.Events sees it (FakeConn in test_rpc.py)."""

    def __init__(self, subscribed, ok=True):
        self.events, self.shown, self.sent, self.ok, self.alive = set(subscribed), set(), [], ok, True

    def send(self, obj):
        self.sent.append(obj)
        return self.ok


MAIN_SUBS = ["status", "level", "activity", "download", "notice", "show", "here", "quitting", "models", "turbo",
             "update"]                                  # EngineEvent.mainWindow (ui_flutter/lib/engine/events.dart)
BAR_SUBS = ["show", "quitting"]                         # EngineEvent.bar


def _wired(clients, clock=None):
    from nobadfind.rpc.events import Events as RpcEvents
    ev = RpcEvents(lambda: list(clients), lambda c: clients.remove(c), api=None)
    started = []
    ui = uilaunch.Launcher(ev, connected=lambda: bool(clients), exe=lambda: "nobad_find.exe",
                           start=started.append, clock=clock or (lambda: 100.0))
    return ev, ui, started


def test_open_with_only_the_hidden_bar_connected_starts_the_main_window():
    """The user's case: the bar was used (log: "started the UI (bar)"), the main window was closed (its process
    ends), the bar's process stays hidden. "Open NOBAD Find" sent `show main` to the bar, which ignores it."""
    bar = Conn(BAR_SUBS)
    ev, ui, started = _wired([bar])
    assert ev.can_show("bar") and not ev.can_show("main")
    ui.show("main")
    assert started == [["nobad_find.exe", "--page", "search"]]
    assert bar.sent == []                               # nothing the bar would have ignored
    ui.show("settings")                                 # the tray's Settings too: same main window process
    assert len(started) == 1                            # it is starting: no second copy


def test_the_bar_with_only_the_main_window_connected_starts_the_bar():
    main = Conn(MAIN_SUBS)
    ev, ui, started = _wired([main])
    ui.show("bar")
    assert started == [["nobad_find.exe", "--bar"]] and main.sent == []


def test_a_hidden_main_window_still_gets_its_show_event():
    """Esc hides the main window but keeps its process: it gets the event and comes to the front."""
    main, bar = Conn(MAIN_SUBS), Conn(BAR_SUBS)
    ev, ui, started = _wired([main, bar])
    ui.show("main")
    assert started == [] and [m["params"]["what"] for m in main.sent] == ["main"]


def test_a_main_window_whose_pipe_broke_is_started_again():
    """A UI that is ending (pipe already broken) can't take the event: start one (the runner's own mutex brings
    an existing main window up instead of opening a second)."""
    clients = [Conn(MAIN_SUBS, ok=False)]
    ev, ui, started = _wired(clients)
    ui.show("main")
    assert started == [["nobad_find.exe", "--page", "search"]] and clients == []


def test_the_bars_alt_enter_starts_a_closed_main_window_with_its_words():
    from nobadfind.rpc import handlers, protocol
    bar = Conn(BAR_SUBS)
    clients = [bar]
    ev, ui, started = _wired(clients)
    ev.open_window = ui.show
    m = handlers.methods(type("A", (), {})(), ev)
    protocol.handle_line('{"jsonrpc":"2.0","id":1,"method":"to_main","params":{"text":"tax 2025"}}', m, bar)
    assert started == [["nobad_find.exe", "--page", "search"]]
    main = Conn(MAIN_SUBS)
    clients.append(main)
    ui.started(None)                                    # its ui_shown (Wiring._shown): the words follow
    assert [x["params"] for x in main.sent] == [{"what": "main", "text": "tax 2025"}]


def test_a_starting_bar_does_not_hold_back_the_main_window():
    clock = [100.0]
    ev, ui, started = _wired([], clock=lambda: clock[0])
    ui.started(99.0, "bar")                             # NobadFind.exe --bar just started the bar
    ui.show("main")
    assert started == [["nobad_find.exe", "--page", "search"]]
    assert ui.starting()


def test_window_of_follows_subscriptions_and_reports():
    from nobadfind.rpc.events import window_of
    assert window_of(Conn(MAIN_SUBS)) == "main" and window_of(Conn(BAR_SUBS)) == "bar"
    assert window_of(Conn([])) is None
    c = Conn([])
    c.shown.add("bar")
    assert window_of(c) == "bar"
