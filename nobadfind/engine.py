"""NOBAD Find's engine: the encrypted index, the indexer, the governor, the watchdog, the hotkeys, the tray icon and
the private pipe (nobadfind.rpc) the Flutter UI talks to (contract).

NobadFind.exe runs it (app.py) and starts the UI (nobad_find.exe, uilaunch) on the page asked for; with --background
(Start with Windows) or --engine (development, measurements) it starts without a window. The hotkeys and the tray
open the UI later: a `show` event when one is connected, else uilaunch starts it. The UI reports its window with
ui_shown / ui_hidden (or by its pipe closing), and indexing follows lifecycle's rules.

One engine per index:
- With the default data folder the lock is "Local\\NOBAD-Find": a second NobadFind.exe asks this one to show its
  window (one show event per page, winapi.SHOW_WHAT) and ends.
- With NOBAD_FIND_DATA_DIR set (a separate index, used for measurements) the engine takes a lock (and show events)
  of its own and can run next to the real one; the real one keeps the hotkeys then (this one logs that they're taken).
- Only one engine per user can serve the pipe; a second one exits with an error.
"""
import ctypes
import hashlib
import os
import threading

from . import embed, jobs, winapi
from .const import APP_NAME, APP_VER, DATA_DIR, DB_PATH, KEY_PATH, LOG_PATH, SETTINGS_PATH
from .log import init as init_log, log

DEFAULT_DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")


def _canon(path):
    """One spelling per folder: junctions, symbolic links and 8.3 short names resolved, case folded."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def lock_name(data_dir=DATA_DIR, default=DEFAULT_DATA_DIR):
    """The single-instance mutex: the app's own for the default index, a separate one for another data folder."""
    if _canon(data_dir) == _canon(default):
        return "Local\\NOBAD-Find"
    digest = hashlib.sha256(_canon(data_dir).encode("utf-8")).hexdigest()[:16]
    return "Local\\NOBAD-Find-engine-" + digest


def _single(name):
    if not winapi.WIN:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _single.handle = k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def here_finder(api, events, ui_pids, foreground=winapi.foreground_window, window_pid=winapi.window_pid,
                folder=winapi.foreground_folder, spawn=None):
    """The main hotkey: show the main window, and find "here" (the File Explorer folder in front) on a thread.
    Pressed while a NOBAD Find window is in front, "here" stays what it was. A newer press wins."""
    state = {"n": 0}
    spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True, name="here").start())

    def pressed():
        front = foreground()
        if front and window_pid(front) in ui_pids():
            events.show("main")
            return
        api.here = ""
        state["n"] += 1
        mine = state["n"]
        events.show("main")

        def find():
            path = folder(front) if front else ""
            if mine == state["n"]:
                api.here = path
                events.here(path)
        spawn(find)
    return pressed


MEASURE_LEVELS = ("full", "gentle", "light", "paused")


def measure_overrides(env, data_dir=DATA_DIR, default=DEFAULT_DATA_DIR, base=None):
    """Dev only (tools/measure.py): with a separate index (NOBAD_FIND_DATA_DIR), the engine may serve
    its own pipe (NOBAD_FIND_MEASURE_PIPE, letters/digits/dashes) so it runs next to another engine, and keep one
    work level (NOBAD_FIND_MEASURE_LEVEL). Ignored with the real index. {"level", "pipe"}, None = not asked."""
    out = {"level": None, "pipe": None}
    if _canon(data_dir) == _canon(default):
        return out
    level = env.get("NOBAD_FIND_MEASURE_LEVEL", "")
    if level in MEASURE_LEVELS:
        out["level"] = level
    tag = env.get("NOBAD_FIND_MEASURE_PIPE", "")
    if tag and len(tag) <= 32 and all(c.isascii() and (c.isalnum() or c == "-") for c in tag):
        if base is None:
            from .rpc.server import pipe_name
            base = pipe_name()
        out["pipe"] = f"{base}-measure-{tag}"
    return out


MAIN_TAKEN = "The hotkey is used by another app. Pick another one in Settings."
BAR_TAKEN = "The quick find bar shortcut is used by another app. Pick another one in Settings."
MAIN_RESERVED = "Windows keeps the hotkey for itself. Pick another one in Settings."
BAR_RESERVED = "Windows keeps the quick find bar shortcut for itself. Pick another one in Settings."
WHAT = {"hotkey": "to open NOBAD Find", "bar_hotkey": "for the quick find bar"}


def key_label(spec):
    """'win+shift+f' -> 'Win+Shift+F' for messages."""
    return "+".join(p.upper() if len(p) == 1 or (p[0] == "f" and p[1:].isdigit()) else p.capitalize()
                    for p in str(spec).split("+"))


def show_base(lock):
    """The show events' name for this lock: "Local\\NOBAD-Find-Show" (winapi.SHOW_EVENT) for the real index."""
    return lock + "-Show"


def worker_hooks(pieces):
    """What the watchdog and the governor reach through pieces, which fills up as the pieces are made. The governor
    starts first, so each hook is a no-op (or a safe default) until its piece exists."""
    def on(key, fn, default=None):
        def call():
            obj = pieces.get(key)
            return default if obj is None else fn(obj)
        return call
    return {"release": on("indexer", lambda i: i.release_models()),
            "recycle": on("indexer", lambda i: i.recycle_workers()),
            "release_idle": on("indexer", lambda i: i.release_idle_models()),
            "names": on("indexer", lambda i: i.worker_names(), {})}


def show_requests(base, show, stop, make=winapi.show_event, wait=winapi.wait_any, spawn=None):
    """A second start of NobadFind.exe (Start menu, desktop, --page / --bar) signals one of the show events:
    show(what) for it until stop is set. Returns True while it listens, None when no event could be made."""
    names, handles = [], []
    for what in winapi.SHOW_WHAT:
        h = make(what, base)
        if h:
            names.append(what)
            handles.append(h)
    if not handles:
        log("no show events: a second start can't bring the window up", "warn")
        return None

    def loop():
        while not stop.is_set():
            i = wait(handles, 500)
            if i is not None and not stop.is_set():
                try:
                    show(names[i])
                except Exception as e:
                    log(f"show request failed: {type(e).__name__}", "warn")
    spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True, name="show").start())
    return spawn(loop) or True


class Wiring:
    """What ties the Api to the indexer, the events and the hotkeys in the headless engine (no Windows needed, so
    tests build it with fakes).

    - Indexing starts idle, as app.py does when started in the background, unless "Keep indexing in the
      background" is on; the UI's first ui_shown starts it (lifecycle.Window).
    - ui_hidden or the UI's pipe closing follows lifecycle.after_hide.
    - Quit sends quitting, and stops the engine only once the reply is written (protocol.after_reply).
    - A hotkey another app holds becomes a notice."""

    def __init__(self, api, settings, indexer, events, stop, ui_pids, make_hotkey=None, dialog=None,
                 trim=winapi.trim_working_set, launcher=None):
        from . import lifecycle
        self.api, self.settings, self.indexer, self.events, self.stop = api, settings, indexer, events, stop
        self.ui_pids = ui_pids
        if launcher is None:
            from .uilaunch import Launcher

            def launcher(ev):
                return Launcher(ev, connected=lambda: bool(self.ui_pids()), note=ev.notice)
        self.ui = launcher(events)            # show(what): the show event, or start the UI on that page
        self.make_hotkey = make_hotkey
        self._timer = threading.Timer
        self._seen_ui = False             # a UI has connected or shown a window since the engine started
        self.keys = []                     # [main hotkey, quick find bar hotkey (if the bar is on)]
        self.key_state = {}                # hotkey / bar_hotkey -> ok | taken | reserved | invalid | off
        self.tray_ok = lambda: False       # the engine sets it: is the notification-area icon up?
        self._keys_lock = threading.Lock()
        self.life = lifecycle.Window(indexer, not settings.get("keep_background"), log, quitting=stop.is_set,
                                     trim=trim)
        api._folder_dialog = dialog if dialog is not None else winapi.pick_folder
        api._on_show = self._shown
        api._on_hide = lambda: lifecycle.after_hide(self.life, settings, self.reachable(), stop.is_set())
        api._on_hotkeys = self.rebind
        api._hotkey_state = self.hotkey_state
        api._hotkey_probe = self.probe
        api.quit = self._quit
        api._on_all_closed = self._all_closed

    CLOSE_GRACE_S = 3.0

    def _all_closed(self):
        """A window closed or was hidden. 0.8.5, maintainer's ask: closing NOBAD Find leaves nothing running, so
        once no UI shows any window (a hidden quick find bar doesn't count), the engine, its workers, the tray icon
        and that hidden bar quit too, unless "Keep running after closing the window" (stay_running) is on, which
        keeps the hotkeys and the icon as before. Checked again after a short grace, so going from the bar to the
        main window (Alt+Enter), or a window that is just starting, doesn't end anything."""
        self._seen_ui = True
        if self.stop.is_set():
            return
        if self.settings.get("stay_running"):
            self._first_close_note()
            return
        t = self._timer(self.CLOSE_GRACE_S, self._close_check)
        t.daemon = True
        t.start()

    def _first_close_note(self):
        """Once ever (bg_notice_seen): closing didn't quit, so say where NOBAD Find went and how to get it back."""
        if self.settings.get("bg_notice_seen") or self._anything_open():
            return
        say = self.balloon
        if say is None:
            return
        spec = self.settings.get("hotkey")
        how = (f"Press {key_label(spec)} to search, or click its icon here." if self.key_state.get("hotkey") == "ok"
               else "Click its icon here to search.")
        if say("NOBAD Find is still here",
               f"{how} Right-click the icon to quit, or change this in Settings > Performance."):
            self.settings.update({"bg_notice_seen": True})

    balloon = None          # the engine sets it: Tray.balloon of the notification-area icon (None without one)

    def _anything_open(self):
        showing = getattr(self.events, "showing", None)
        if showing is not None and any(showing(w) for w in ("main", "bar")):
            return True
        starting = getattr(self.ui, "starting", None)
        return bool(starting and starting())

    def _close_check(self):
        if self.settings.get("stay_running") or self.stop.is_set() or self._anything_open():
            return
        log("no NOBAD Find window is open: quitting (stay_running is off)")
        self.events.quitting()
        self.stop.set()

    def _shown(self):
        self._seen_ui = True
        from . import splash
        splash.close()                                     # the window is up: the start-up card goes
        done = getattr(self.ui, "started", None)        # the UI that was starting is here: no longer "starting"
        if done is not None:
            done(None)
        self.life.wanted(False)
        threading.Thread(target=self.indexer.warm_models, daemon=True, name="warm").start()

    def _quit(self):                                       # Quit over the pipe, and the watchdog's last resort
        from .rpc.protocol import after_reply
        self.events.quitting()
        after_reply(self.stop.set)
        return {"ok": True}

    PAUSE_S = 3600

    def show_request(self, what):
        """A second start asked for a window (show_requests): like the tray, "here" starts empty."""
        if what == "main":
            self.api.here = ""
        self.ui.show(what)

    def tray_action(self, action):
        """A tray menu item (tray.MENU) or a left click ("open")."""
        pages = {"open": "main", "bar": "bar", "settings": "settings", "index": "index"}
        if action in pages:
            self.ui.show(pages[action])
        elif action == "pause":
            self.api.pause_for(self.PAUSE_S)
        elif action == "resume":
            self.api.resume()
        elif action == "quit":
            self.events.quitting()
            self.stop.set()

    def reachable(self):
        """Can a hidden NOBAD Find be brought back? Its main hotkey works, or its notification-area icon is up."""
        return bool(self.keys and self.keys[0].ok) or bool(self.tray_ok())

    def _bind(self, which, fallback):
        """Register one hotkey from the settings. Returns (hotkey, state). With fallback, a default another app
        holds on this PC moves to the next free combination in hotkey.FALLBACKS, saved, and a notice says so."""
        from . import hotkey
        from .const import DEFAULTS
        make = self.make_hotkey
        if make is None:
            make = hotkey.Hotkey
        hk_id = 1 if which == "hotkey" else 2
        if which == "hotkey":
            cb = here_finder(self.api, self.ui, self.ui_pids)
        else:
            def cb():
                self.ui.show("bar")
        spec = self.settings.get(which)
        hk = make(spec, cb, hk_id=hk_id)
        if hk.start():
            return hk, "ok"
        state = "reserved" if hotkey.reserved(spec) else "taken" if hotkey.parse(spec) else "invalid"
        if not fallback or spec != DEFAULTS[which]:
            return hk, state
        other = hotkey.normal(self.settings.get("bar_hotkey" if which == "hotkey" else "hotkey"))
        for alt in hotkey.FALLBACKS[which]:
            if hotkey.normal(alt) in (hotkey.normal(spec), other):
                continue
            h2 = make(alt, cb, hk_id=hk_id)
            if h2.start():
                self.settings.update({which: alt})
                log(f"engine: {spec} is taken here, {which} moved to {alt}")
                self.events.notice(f"{key_label(spec)} is used by another app on this PC, so NOBAD Find uses "
                                   f"{key_label(alt)} {WHAT[which]}. You can change it in Settings.")
                return h2, "ok"
        return hk, state

    def _bind_all(self, fallback):
        """(Re)register both hotkeys from the settings; the old ones are let go first. Returns key_state."""
        with self._keys_lock:
            for hk in self.keys:
                try:
                    hk.stop()
                except Exception as e:
                    log(f"hotkey stop failed: {type(e).__name__}", "warn")
            self.keys.clear()
            state = {}
            for which in ("hotkey", "bar_hotkey"):
                if which == "bar_hotkey" and not self.settings.get("bar"):
                    state[which] = "off"
                    continue
                hk, st = self._bind(which, fallback)
                self.keys.append(hk)
                state[which] = st
                if st != "ok":
                    log(f"engine: hotkey {hk.spec} not available ({st})", "warn")
            self.key_state = state
            return dict(state)

    def rebind(self):
        """Settings changed a hotkey or the bar switch: let the old combinations go and take the new ones now,
        no restart. Returns hotkey_state() so Settings can say at once whether each one works."""
        self._bind_all(fallback=False)
        return self.hotkey_state()

    def hotkey_state(self):
        return {w: {"spec": self.settings.get(w), "state": self.key_state.get(w, "off")}
                for w in ("hotkey", "bar_hotkey")}

    def probe(self, which, spec):
        """Would spec work for which? ok | taken | reserved | invalid | same (the other NOBAD Find hotkey)."""
        from . import hotkey
        n = hotkey.normal(spec)
        if n is None or hotkey.parse(n) is None:
            return "invalid"
        other = "bar_hotkey" if which == "hotkey" else "hotkey"
        if n == hotkey.normal(self.settings.get(other)) and (other == "hotkey" or self.settings.get("bar")):
            return "same"
        if n == hotkey.normal(self.settings.get(which)) and self.key_state.get(which) == "ok":
            return "ok"                                      # it's ours already
        if hotkey.reserved(n):
            return "reserved"
        return (self.probe_fn or hotkey.probe)(n)

    probe_fn = None

    def start(self):
        """Indexing (only with background indexing on) and the hotkeys. Returns the hotkeys."""
        if not self.life.want_idle:
            self.indexer.start()
        else:
            log("engine: indexing starts when the UI shows its window")
        state = self._bind_all(fallback=True)
        for which in ("hotkey", "bar_hotkey"):
            st = state.get(which)
            if st in ("taken", "invalid"):
                self.events.notice(BAR_TAKEN if which == "bar_hotkey" else MAIN_TAKEN)
            elif st == "reserved":
                self.events.notice(BAR_RESERVED if which == "bar_hotkey" else MAIN_RESERVED)
        threading.Thread(target=self._watch_closed, daemon=True, name="closed-watch").start()
        return self.keys

    WATCH_S = 15.0

    def _watch_closed(self):
        """Backs up _all_closed for windows that end hidden without saying so (a quick find bar that never got
        the focus, a UI that hung up mid-way): once any UI has connected, a look every WATCH_S seconds quits when
        no window is open. Never before a UI connected, so a background start (autostart) keeps running."""
        while not self.stop.wait(self.WATCH_S):
            self._seen_ui = self._seen_ui or bool(self.ui_pids())
            if self._seen_ui and not self.settings.get("stay_running"):
                self._close_check()


def start_tray(settings, api, governor, wiring):
    """The notification-area icon (setting "tray"), or None."""
    if not settings.get("tray"):
        return None
    import time
    from . import tray
    icon = tray.Tray(wiring.tray_action, tip=lambda: tray.tooltip(api.status_brief()),
                     paused=lambda: governor.brain.pause_until > time.time())
    if not icon.start():
        log("tray icon not available", "warn")
        return None
    return icon


def main(stop=None):
    """`NobadFind.exe --engine` / `python -m nobadfind --engine`: no window until a UI connects or a hotkey asks for
    one. Run until `stop` (a threading.Event) is set or the process is ended. Returns the exit code."""
    if winapi.is_admin():
        print("NOBAD Find runs as your normal account. Start it without 'Run as administrator'.")
        return 1
    lock = lock_name()
    if not _single(lock):
        print("NOBAD Find is already running with this index. Quit it first.")
        return 1
    return run(stop, lock=lock)


def run(stop=None, open_ui=None, lock=None):
    """The engine, once the caller holds the single-instance lock (main, app.main). open_ui: the window to start
    the UI on ("main", "settings", "index", "bar"), or None to start without one. Returns the exit code."""
    lock = lock or lock_name()
    os.makedirs(DATA_DIR, exist_ok=True)
    init_log(LOG_PATH)
    jobs.setup()                    # nothing the engine starts can outlive it
    log(f"{APP_NAME} {APP_VER} engine starting")
    from . import uilaunch
    first_ui = uilaunch.start_now(open_ui) if open_ui else None     # first, so the window is up while we load
    from .activity import Activity
    from .api import Api
    from .appmemory import AppMemory
    from .governor import Governor
    from .indexer import Indexer
    from .rpc import Rpc
    from .settings import Settings
    from .store import Store
    from .watchdog import Watchdog

    settings = Settings(SETTINGS_PATH)
    store = Store(DB_PATH, KEY_PATH)
    if not store.encrypted:
        log("SQLCipher missing: the index is NOT encrypted", "warn")
    vindex = embed.VectorIndex()
    activity = Activity()
    pieces = {}
    hooks = worker_hooks(pieces)
    watchdog = Watchdog(activity, **{k: hooks[k] for k in ("release", "recycle", "names")})
    apps = AppMemory(store)
    governor = Governor(settings, apps, activity, watchdog=watchdog, release_idle=hooks["release_idle"])
    measure = measure_overrides(os.environ)
    if measure["level"]:
        governor.brain.fixed = measure["level"]
        log(f"engine: level fixed at {measure['level']} for a measurement", "warn")
    governor.start()
    indexer = Indexer(store, settings, vindex, governor=governor, activity=activity)
    pieces["indexer"] = indexer
    from .turbo import Turbo
    turbo = Turbo(settings, store, indexer)         # the optional elevated NTFS reader; off unless turned on
    indexer.turbo = turbo
    stop = stop or threading.Event()
    api = Api(store, settings, indexer, vindex)
    api._governor, api._activity, api._apps = governor, activity, apps
    api._turbo = turbo
    rpc = Rpc(api, name=measure["pipe"], activity=activity)
    turbo._push = rpc.events.turbo
    from .update import Updater
    updater = Updater(settings)
    updater.on_change = rpc.events.update
    api._updater = updater
    from .launcher import Launcher
    launcher = Launcher(DATA_DIR)
    api._launcher = launcher
    wiring = Wiring(api, settings, indexer, rpc.events, stop, rpc.ui_pids)
    if first_ui is not None:
        wiring.ui.started(first_ui)             # a hotkey right now doesn't start a second one
    if not rpc.start():
        print("The NOBAD Find pipe is in use: another engine is running for this user.")
        governor.stop()
        return 1
    keys = wiring.start()
    show_requests(show_base(lock), wiring.show_request, stop)
    tray_box = {"icon": start_tray(settings, api, governor, wiring)}

    def on_tray(on):                                      # Settings: the icon comes and goes at once
        if on and tray_box["icon"] is None:
            tray_box["icon"] = start_tray(settings, api, governor, wiring)
        elif not on and tray_box["icon"] is not None:
            tray_box["icon"].stop()
            tray_box["icon"] = None
    api._on_tray = on_tray
    wiring.tray_ok = lambda: tray_box["icon"] is not None
    wiring.balloon = lambda title, text: bool(tray_box["icon"] and tray_box["icon"].balloon(title, text))
    log(f"engine ready (pid {os.getpid()})")
    print(f"NOBAD Find engine ready (pid {os.getpid()}). Ctrl+C stops it.", flush=True)
    tip, n = None, 0
    try:
        while not stop.wait(0.5):
            n += 1
            if n % 120 == 60 and updater.due():               # a minute after start, then every minute's look
                updater.check_in_background()
            if n % 120 == 20:                                 # the Start list: at start, then every few hours
                launcher.refresh_in_background()
            icon = tray_box["icon"]
            if icon is not None and n % 10 == 0:          # the tooltip follows the level and the count (5 s)
                now = icon.tip()
                if now != tip:
                    tip = now
                    icon.update()
    except KeyboardInterrupt:
        pass
    log("engine stopping")
    if tray_box["icon"] is not None:
        tray_box["icon"].stop()
    for hk in keys:
        hk.stop()
    rpc.stop()
    turbo.stop()                    # the helper ends with the engine (it also watches the engine's process)
    indexer.stop()
    governor.stop()
    indexer.join(5)                 # database writes are committed first
    log("engine stopped")
    return 0
