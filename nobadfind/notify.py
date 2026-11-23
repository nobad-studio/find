"""Notifications: crashes, restarted workers, model fallbacks, internal errors, suggestions, updates (maintainer
request 2026-11-21). One place any part of the engine posts to: `post(kind, title, body, severity, ...)`.

- Every notification is kept in memory and in a small history (at most CAP) INSIDE the encrypted index (store.py,
  table notifications), never in a plain file. "Clear" in the window's notification panel deletes them; wiping
  the index deletes them too.
- No file paths or file contents in the text: anything that looks like a path is replaced before it is kept, and
  a file name (`detail`) is only kept and shown while the setting notify_show_names is on (off by default).
  Windows toasts show on the lock screen and in the Action Center, so this matters.
- The same `key` at most once per KEY_EVERY seconds (or its own `every`); at most TOASTS_PER_HOUR Windows toasts an
  hour, the rest stay in the window only.
- Windows toasts ("Windows push") are local only: the WinRT ToastNotificationManager with the Start menu
  shortcut's AppUserModelID (packaging/installer.iss), nothing over the network. If Windows refuses the toast (no
  shortcut when run from source), the tray icon's balloon says it instead. Settings: notify_toasts (on),
  notify_level (the lowest severity that gets a toast; warning), notify_quiet (no toast while a game, a call or
  a presentation is on: the governor's own detection) and notify_show_names (off).
- Posting never raises and never blocks on Windows or the index: the toast and the index write run on a
  background thread.
"""
import os
import re
import threading
import time
import traceback
from collections import deque
from xml.sax.saxutils import escape

from .log import log

KINDS = ("worker_crashed", "worker_restarted", "model_fallback", "model_released_memory", "internal_error",
         "suggestion", "update_available", "turbo_needs_ok", "indexing_paused_reason")
SEVERITIES = ("info", "warning", "error")
# What a notification's one button does, and its label. The UI maps the id to a page; nothing else is accepted.
ACTIONS = {"open_indexing": "Open Indexing", "open_performance": "Open Performance", "open_models": "Open Models",
           "open_turbo": "Open What to index", "update": "Update"}
AUMID = "NOBAD.Find"          # the Start menu shortcut's AppUserModelID (packaging/installer.iss)
CAP = 100                     # notifications kept in the index
KEY_EVERY = 600               # the same key at most once per 10 minutes
TOASTS_PER_HOUR = 5
LONG_PAUSE = 1800             # a pause that isn't the user's own, this long, is worth a word (governor.py)
MAX_TITLE, MAX_BODY, MAX_DETAIL = 80, 300, 120

CENTER = None                 # the engine's Center (engine.run); None: posting does nothing (tests, tools)

# Where a path starts: a drive (C:\ or C:/), a UNC or device path (\\server, \\?\), or //server/
_PATH_START = re.compile(r"(?<![A-Za-z0-9:])(?:[A-Za-z]:[\\/]|\\\\|//(?=[^\s/]))")
# The next word still belongs to the path: it has a separator, or it ends in an extension ("secret plans.docx")
_PATH_GOES_ON = re.compile(r"[\\/]|\.[A-Za-z0-9]{1,8}[).,;:\]]*$")


def post(kind, title, body, severity="info", action=None, key=None, detail="", every=None, once=False):
    """Post to the engine's Center, if there is one. Never raises."""
    c = CENTER
    if c is None:
        return None
    try:
        return c.post(kind, title, body, severity, action=action, key=key, detail=detail, every=every, once=once)
    except Exception as e:
        log(f"notification failed: {type(e).__name__}", "warn")
        return None


def scrub(text, limit):
    """One line, no paths, at most `limit` characters."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    out, pos = [], 0
    for m in _PATH_START.finditer(t):
        if m.start() < pos:
            continue
        end = t.find(" ", m.start())
        end = len(t) if end < 0 else end
        while end < len(t):
            nxt = t.find(" ", end + 1)
            stop = len(t) if nxt < 0 else nxt
            if not _PATH_GOES_ON.search(t[end + 1:stop]):
                break
            end = stop
        tail = re.search(r"[.,;:)\]]*$", t[m.start():end]).group()     # the sentence's own punctuation stays
        out.append(t[pos:m.start()] + "a file" + tail)
        pos = end
    out.append(t[pos:])
    return "".join(out)[:limit].strip()


def file_name(detail):
    """Only the last part of a path, as plain text."""
    d = str(detail or "").replace("/", "\\").rstrip("\\").rsplit("\\", 1)[-1]
    return re.sub(r"\s+", " ", d).strip()[:MAX_DETAIL]


class Center:
    """settings: .get; store: the index (or None: memory only); toast(title, body) -> bool shows a Windows toast;
    quiet() -> True while a game, a call or a presentation is on; run(fn): where slow work runs (a thread)."""

    def __init__(self, settings, store=None, toast=None, quiet=lambda: False, clock=time.time, run=None):
        self.settings, self.store = settings, store
        self._toast = toast
        self._quiet = quiet
        self.clock = clock
        self._run = run or _background
        self._items = deque(maxlen=CAP)           # newest last
        self._next = 1
        self._keys = {}                           # key -> when last posted
        self._toasted = deque()                   # when each toast in the last hour went out
        self._lock = threading.Lock()
        self._listeners = []

    def listen(self, fn):
        """fn(item, unread) for each new notification, on the posting thread."""
        self._listeners.append(fn)

    def load(self):
        """The kept history, from the index (at engine start)."""
        if self.store is None:
            return
        try:
            rows = self.store.q("SELECT id, t, kind, severity, title, body, detail, action, read, key "
                                "FROM notifications ORDER BY id DESC LIMIT ?", (CAP,))
        except Exception as e:
            log(f"notifications not loaded: {type(e).__name__}", "warn")
            return
        with self._lock:
            self._items.clear()
            for r in reversed(rows):
                self._items.append({"id": r[0], "t": float(r[1]), "kind": r[2], "severity": r[3], "title": r[4],
                                    "body": r[5], "detail": r[6] or "", "action": r[7] or "", "read": bool(r[8]),
                                    "key": r[9] or ""})
            self._next = max([i["id"] for i in self._items] + [0]) + 1

    # ---------- posting ----------
    def post(self, kind, title, body, severity="info", action=None, key=None, detail="", every=None, once=False):
        """Keep one notification and maybe show it as a Windows toast. Returns the item as listed, or None when
        it was refused or a duplicate."""
        if kind not in KINDS or severity not in SEVERITIES:
            log(f"notification refused: {kind!r} {severity!r}", "warn")
            return None
        title, body = scrub(title, MAX_TITLE), scrub(body, MAX_BODY)
        if not title:
            return None
        names = bool(self.settings.get("notify_show_names"))
        detail = file_name(detail) if names else ""
        act = action if action in ACTIONS else ""
        now = self.clock()
        with self._lock:
            k = str(key or "")
            if k:
                gap = KEY_EVERY if every is None else every
                last = self._keys.get(k)
                if last is not None and now - last < gap:
                    return None
                if once and any(i.get("key") == k for i in self._items):
                    return None
                self._keys[k] = now
            item = {"id": self._next, "t": now, "kind": kind, "severity": severity, "title": title, "body": body,
                    "detail": detail, "action": act, "read": False, "key": k}
            self._next += 1
            self._items.append(item)
            unread = sum(1 for i in self._items if not i["read"])
            toast = self._wants_toast(severity, now)
        shown = self._shape(item)
        log(f"notification: {kind} ({severity})")
        self._later(lambda: self._keep(item))
        if toast:
            text = body + (f" ({detail})" if detail else "")
            self._later(lambda: self._show(title, text))
        for fn in list(self._listeners):
            try:
                fn(dict(shown), unread)
            except Exception as e:
                log(f"notification listener failed: {type(e).__name__}", "warn")
        return shown

    def _wants_toast(self, severity, now):
        """Under the lock: a Windows toast for this one? Counts it if so."""
        s = self.settings
        if not s.get("notify_toasts") or self._toast is None:
            return False
        level = s.get("notify_level") if s.get("notify_level") in SEVERITIES else "warning"
        if SEVERITIES.index(severity) < SEVERITIES.index(level):
            return False
        try:
            if s.get("notify_quiet") is not False and self._quiet():
                return False                    # a game, a call or a presentation: in the window only
        except Exception:
            pass
        while self._toasted and now - self._toasted[0] >= 3600:
            self._toasted.popleft()
        if len(self._toasted) >= TOASTS_PER_HOUR:
            return False
        self._toasted.append(now)
        return True

    def _later(self, fn):
        try:
            self._run(fn)
        except Exception as e:
            log(f"notification work failed: {type(e).__name__}", "warn")

    def _show(self, title, text):
        try:
            self._toast(title, text)
        except Exception as e:
            log(f"toast failed: {type(e).__name__}", "warn")

    def _keep(self, item):
        if self.store is None:
            return
        try:
            with self.store.wlock:
                self.store.db.execute(
                    "INSERT OR REPLACE INTO notifications(id, t, kind, severity, title, body, detail, action, read, "
                    "key) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (item["id"], item["t"], item["kind"], item["severity"], item["title"], item["body"],
                     item["detail"], item["action"], int(item["read"]), item["key"]))
                self.store.db.execute("DELETE FROM notifications WHERE id NOT IN (SELECT id FROM notifications "
                                      "ORDER BY id DESC LIMIT ?)", (CAP,))
                self.store.db.commit()
        except Exception as e:
            log(f"notification not kept: {type(e).__name__}", "warn")

    # ---------- the window's panel ----------
    def _shape(self, item):
        names = bool(self.settings.get("notify_show_names"))
        a = item["action"]
        return {"id": item["id"], "t": item["t"], "kind": item["kind"], "severity": item["severity"],
                "title": item["title"], "body": item["body"], "detail": item["detail"] if names else "",
                "action": {"id": a, "label": ACTIONS[a]} if a in ACTIONS else None, "read": item["read"]}

    def unread(self):
        with self._lock:
            return sum(1 for i in self._items if not i["read"])

    def list(self):
        with self._lock:
            items = list(self._items)[::-1]
        return {"items": [self._shape(i) for i in items], "unread": sum(1 for i in items if not i["read"])}

    def read(self, ids=None, all=False):
        with self._lock:
            want = None if all else {i for i in (ids or ()) if isinstance(i, int)}
            changed = [i for i in self._items if not i["read"] and (want is None or i["id"] in want)]
            for i in changed:
                i["read"] = True
        if changed:
            done = [i["id"] for i in changed]
            self._later(lambda: self._write("UPDATE notifications SET read = 1 WHERE id IN (%s)"
                                            % ",".join("?" * len(done)), done))
        return {"ok": True, "error": "", "unread": self.unread()}

    def clear(self):
        with self._lock:
            self._items.clear()
        self._later(lambda: self._write("DELETE FROM notifications"))
        return {"ok": True, "error": ""}

    def forget_names(self):
        """notify_show_names went off: the file names kept so far go too."""
        with self._lock:
            for i in self._items:
                i["detail"] = ""
        self._later(lambda: self._write("UPDATE notifications SET detail = '' WHERE detail != ''"))

    def _write(self, sql, args=()):
        if self.store is None:
            return
        try:
            with self.store.wlock:
                self.store.db.execute(sql, args)
                self.store.db.commit()
        except Exception as e:
            log(f"notifications not changed: {type(e).__name__}", "warn")


_queue_lock = threading.Lock()
_queue = deque()
_worker = None


def _background(fn):
    """One daemon thread runs the slow parts (toasts, index writes) in order."""
    global _worker
    with _queue_lock:
        _queue.append(fn)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, daemon=True, name="notify")
            _worker.start()


def _drain():
    global _worker
    while True:
        with _queue_lock:
            if not _queue:
                _worker = None
                return
            fn = _queue.popleft()
        try:
            fn()
        except Exception as e:
            log(f"notification work failed: {type(e).__name__}", "warn")


# ---------- Windows toasts (local only) ----------
def toast_xml(title, body):
    q = {'"': "&quot;", "'": "&apos;"}
    return ("<toast><visual><binding template=\"ToastGeneric\">"
            f"<text>{escape(title, q)}</text><text>{escape(body, q)}</text>"
            "</binding></visual></toast>")


def _winrt_toast(title, body):
    """Windows.UI.Notifications through the pinned winrt packages. Raises when Windows refuses (no shortcut with
    AUMID, notifications off for the app, an older Windows)."""
    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
    doc = XmlDocument()
    doc.load_xml(toast_xml(title, body))
    ToastNotificationManager.create_toast_notifier_with_id(AUMID).show(ToastNotification(doc))
    return True


def windows_toast(balloon=None):
    """toast(title, body): a Windows toast, else the tray icon's balloon (Shell_NotifyIcon), else nothing."""
    def show(title, body):
        try:
            if _winrt_toast(title, body):
                return True
        except Exception as e:
            log(f"Windows toast unavailable ({type(e).__name__}); using the tray balloon", "warn")
        if balloon is not None:
            return bool(balloon(title, body))
        return False
    return show


# ---------- unhandled errors in engine threads ----------
_old_hook = None


def install_thread_hook():
    """An exception nothing caught in one of the engine's threads: logged, and posted as internal_error (the
    exception's type and the thread's name only: its message may name a file)."""
    global _old_hook
    if _old_hook is None:
        _old_hook = threading.excepthook
    threading.excepthook = _thread_failed


def uninstall_thread_hook():
    global _old_hook
    if _old_hook is not None:
        threading.excepthook = _old_hook
        _old_hook = None


def _thread_failed(args):
    try:
        if args.exc_type is SystemExit:
            return
        name = re.sub(r"[^A-Za-z0-9 _.-]", "", getattr(args.thread, "name", "") or "")[:40] or "background"
        kind = getattr(args.exc_type, "__name__", "Error")
        where = traceback.extract_tb(args.exc_traceback)[-1:] if args.exc_traceback else []
        at = f" at {os.path.basename(where[0].filename)}:{where[0].lineno}" if where else ""
        log(f"thread {name} stopped: {kind}{at}", "error")
        post("internal_error", "Part of NOBAD Find stopped",
             f"The {name} thread stopped after an internal error ({kind}). The rest keeps running; restarting "
             "NOBAD Find starts it again.", "error", key=f"thread:{name}:{kind}")
    except Exception:
        pass
