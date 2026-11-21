"""Start the Flutter UI when a window is asked for (a hotkey, the tray) and no UI is connected to the pipe.

The UI is started outside Find's job (winapi.start_outside_job: a normal breakaway, an argument list, as the same
normal user; the engine never runs elevated), so closing the UI and quitting the engine stay independent. It gets the
page to open: --page search|settings|index, or --bar for the quick find bar.

Where the UI is: next to the engine exe in the installed app (nobad_find.exe); from source, NOBAD_FIND_UI_EXE or the
Flutter release build in ui_flutter.
"""
import os
import sys
import time

from .log import log

UI_NAME = "nobad_find.exe"
DEV_BUILD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui_flutter", "build",
                         "windows", "x64", "runner", "Release", UI_NAME)
PAGES = {"main": "search", "search": "search", "settings": "settings", "index": "index"}
STARTING = 15.0                 # seconds a UI being started has to connect before another start is tried
NO_UI = "NOBAD Find's window isn't installed. Reinstall NOBAD Find to get it back."


def ui_exe():
    """The UI's exe, or None when there is none."""
    if getattr(sys, "frozen", False):
        p = os.path.join(os.path.dirname(sys.executable), UI_NAME)
        return p if os.path.isfile(p) else None
    env = os.environ.get("NOBAD_FIND_UI_EXE", "")
    if env and os.path.isfile(env):
        return env
    return DEV_BUILD if os.path.isfile(DEV_BUILD) else None


def argv_for(exe, what):
    return [exe, "--bar"] if what == "bar" else [exe, "--page", PAGES.get(what, "search")]


def start_now(what, exe=ui_exe, start=None, clock=time.monotonic):
    """Start the UI on that page without waiting for the engine (NobadFind.exe's first start: the window comes up
    while the engine loads, and connects when the pipe is ready). The start time, or None if it didn't start."""
    from . import winapi
    path = exe()
    if not path:
        log("no UI to start (nobad_find.exe not found)", "warn")
        return None
    try:
        (start or winapi.start_outside_job)(argv_for(path, what))
    except OSError as e:
        log(f"could not start the UI (error {e.winerror or e.errno})", "warn")
        return None
    log(f"started the UI ({PAGES.get(what, what)})")
    return clock()


def window_for(what):
    """The UI process a page lives in: the bar has its own (--bar), every other page is in the main window."""
    return "bar" if what == "bar" else "main"


class Launcher:
    """show(what): the `show` event when a UI that has that window is connected, else start one on that page (once
    per STARTING).

    The main window and the quick find bar are separate UI processes, and each acts only on its own show events.
    Before this, any connected UI counted: with the main window closed (its process ends) and the bar's process
    still running hidden, the tray's "Open NOBAD Find" sent a show only the bar heard, and nothing opened. can_show
    (rpc.Events.can_show) says whether a UI with that window is connected."""

    def __init__(self, events, connected, exe=ui_exe, start=None, clock=time.monotonic, note=None, can_show=None):
        from . import winapi
        self.events, self.connected, self.exe, self.clock = events, connected, exe, clock
        if can_show is None:
            can_show = getattr(events, "can_show", None)
        self.can_show = can_show if callable(can_show) else (lambda window: connected())
        self.start = start or winapi.start_outside_job
        self.note = note or (lambda text: None)
        self._started_at = {}                   # "main" / "bar" -> when that UI was started
        self._pending_text = None               # words for a main window that is starting (the bar's Alt+Enter)
        self._told = False

    def _starting(self, window, now):
        at = self._started_at.get(window)
        return at is not None and now - at < STARTING and not self.can_show(window)

    def starting(self):
        """A UI was started less than STARTING seconds ago and its window isn't connected yet."""
        now = self.clock()
        return any(self._starting(w, now) for w in ("main", "bar"))

    def started(self, at, what="main"):
        """A UI was started at `at` (start_now) on `what`: within STARTING, show() waits for it instead of starting
        another. None: the main window that was starting has shown its window (Wiring._shown); words the bar
        handed over while it started are given to it now."""
        window = window_for(what)
        if at is not None:
            self._started_at[window] = at
            return
        self._started_at.pop(window, None)
        text, self._pending_text = self._pending_text, None
        if text and window == "main":
            self.events.show("main", text)

    def here(self, path):
        return self.events.here(path)

    def show(self, what, text=None):
        window = window_for(what)
        if self.can_show(window):
            self._started_at.pop(window, None)
            sent = self.events.show(what, text)
            if sent != 0:                       # a count from rpc.Events; None from fakes
                return sent
            # every UI with that window failed to take the event (its pipe broke as it was ending): start one
            log(f"no NOBAD Find window took the show event ({what}): starting the UI", "warn")
        now = self.clock()
        if self._starting(window, now):
            if text and window == "main":
                self._pending_text = text
            log(f"the UI ({PAGES.get(what, what)}) was started {now - self._started_at[window]:.0f} s ago and "
                "hasn't connected yet: waiting for it")
            return None                         # one is starting already; it opens on the page it was given
        exe = self.exe()
        if not exe:
            if not self._told:
                self._told = True
                log("no UI to start (nobad_find.exe not found)", "warn")
                self.note(NO_UI)
            return None
        try:
            self.start(argv_for(exe, what))
            self._started_at[window] = now
            self._pending_text = text if window == "main" and text else None
            log(f"started the UI ({PAGES.get(what, what)})")
        except OSError as e:
            log(f"could not start the UI (error {e.winerror or e.errno})", "warn")
        return None
