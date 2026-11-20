"""Global hotkeys (default Win+Shift+F for the window, Ctrl+Shift+Space for the quick find bar).

Each Hotkey is RegisterHotKey on its own thread with a message loop. Windows keeps some combinations for itself
(RESERVED): those never work for another app, so they are refused with a reason instead of failing quietly.
probe() tells whether a combination is free right now by registering it for a moment and letting it go.
"""
import ctypes
import threading
from ctypes import wintypes

from . import winapi
from .log import log

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
ORDER = ("win", "ctrl", "alt", "shift")

# Combinations Windows itself uses (a press goes to Windows, never to an app that registered it).
RESERVED = {
    "win+shift+space": "Windows uses it to switch keyboard layouts",
    "win+space": "Windows uses it to switch keyboard layouts",
    "alt+space": "Windows uses it for the window menu",
    "win+shift+s": "Windows uses it for the Snipping Tool",
    "win+l": "Windows uses it to lock the PC",
    "ctrl+alt+delete": "Windows uses it for the security screen",
}
for _d in "0123456789":
    RESERVED.setdefault(f"win+{_d}", "Windows uses Win+number for the taskbar")
    RESERVED.setdefault(f"win+shift+{_d}", "Windows uses Win+Shift+number for the taskbar")
    RESERVED.setdefault(f"win+ctrl+{_d}", "Windows uses Ctrl+Win+number for the taskbar")
    RESERVED.setdefault(f"win+alt+{_d}", "Windows uses Alt+Win+number for the taskbar")

# Tried in order when the default is taken on this PC (never when the user picked a combination).
FALLBACKS = {
    "hotkey": ("win+shift+f", "ctrl+alt+f", "win+alt+f", "ctrl+alt+shift+f"),
    "bar_hotkey": ("ctrl+shift+space", "alt+shift+space", "ctrl+alt+g", "win+alt+g"),
}


def normal(spec):
    """'Shift+Win+F' -> 'win+shift+f': lower case, modifiers in ORDER (Win, Ctrl, Alt, Shift), or None."""
    if not isinstance(spec, str):
        return None
    parts = [p for p in spec.lower().replace(" ", "").split("+") if p]
    if len(parts) < 2:
        return None
    mods, key = parts[:-1], parts[-1]
    if any(m not in MODS for m in mods) or len(set(mods)) != len(mods):
        return None
    return "+".join([m for m in ORDER if m in mods] + [key])


def parse(spec):
    """'win+shift+space' -> (modifiers, virtual key) or None."""
    parts = spec.lower().split("+")
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            return None
        mods |= MODS[p]
    key = parts[-1]
    if key == "space":
        vk = 0x20
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x6F + int(key[1:])
    else:
        return None
    return (mods | MOD_NOREPEAT, vk) if mods else None


def reserved(spec):
    """Why Windows keeps this combination, or "" (spec in any order of modifiers)."""
    n = normal(spec) or ""
    for k, why in RESERVED.items():
        if normal(k) == n:
            return why
    return ""


def _user32():
    return ctypes.windll.user32


def probe(spec, timeout=1.0):
    """Is spec free right now? 'ok', 'taken' (another app has it), 'reserved' (Windows keeps it) or 'invalid'.
    Registers it on a short-lived thread (RegisterHotKey belongs to the thread that calls it) and lets it go."""
    parsed = parse(spec) if isinstance(spec, str) else None
    if not parsed:
        return "invalid"
    if reserved(spec):
        return "reserved"
    if not winapi.WIN:
        return "ok"
    box = {}

    def go():
        user32 = _user32()
        box["ok"] = bool(user32.RegisterHotKey(None, 0x7F00, parsed[0], parsed[1]))
        if box["ok"]:
            user32.UnregisterHotKey(None, 0x7F00)

    t = threading.Thread(target=go, daemon=True, name="hotkey-probe")
    t.start()
    t.join(timeout)
    return "ok" if box.get("ok") else "taken"


class Hotkey:
    def __init__(self, spec, callback, hk_id: int = 1):
        self.spec = spec
        self.callback = callback
        self.hk_id = hk_id                  # one per hotkey (the main window uses 1, the quick find bar 2)
        self.ok = False
        self._tid = None
        self._thread = None

    def start(self):
        parsed = parse(self.spec)
        if not winapi.WIN or not parsed or reserved(self.spec):
            return False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(parsed, ready), daemon=True, name="hotkey")
        self._thread.start()
        ready.wait(2)
        return self.ok

    def stop(self, wait=2.0):
        """Let the combination go. Waits for the thread so the same combination can be registered again at once."""
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(wait)
        self.ok = False

    def _loop(self, parsed, ready):
        user32 = _user32()
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, self.hk_id, parsed[0], parsed[1]))
        ready.set()
        if not self.ok:
            log(f"hotkey {self.spec} is taken by another app", "warn")
            return
        log(f"hotkey {self.spec} ready")
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception as e:
                        log(f"hotkey action failed: {type(e).__name__}", "warn")
        finally:
            user32.UnregisterHotKey(None, self.hk_id)
