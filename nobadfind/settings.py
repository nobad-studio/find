"""Settings: a small JSON file, every value checked against DEFAULTS before it is used or saved."""
import json
import os
import re
import threading

from .const import DEFAULTS

_HOTKEY = re.compile(r"^(?:(?:ctrl|alt|shift|win)\+){1,3}(?:[a-z0-9]|space|f(?:[1-9]|1[0-2]))$")
WSEARCH_STARTS = ("", "auto", "delayed-auto", "demand", "disabled")
SCOPES = ("whole_pc", "my_files", "custom")


def _paths(v):
    if not isinstance(v, list):
        return []
    out = []
    for p in v[:200]:
        if isinstance(p, str) and 2 < len(p) < 1024 and os.path.isabs(p) and "\x00" not in p:
            out.append(os.path.normpath(p))
    return list(dict.fromkeys(out))


def coerce(key, value):
    """Return a safe value for key, or the default if value doesn't fit."""
    d = DEFAULTS[key]
    if key in ("roots", "exclude"):
        return _paths(value)
    if key == "content_max_mb":
        try:
            return max(1, min(500, int(value)))
        except (TypeError, ValueError, OverflowError):     # OverflowError: int(float("inf"))
            return d
    if key == "workers":
        try:
            return max(0, min(64, int(value)))
        except (TypeError, ValueError, OverflowError):
            return d
    if key in ("hotkey", "bar_hotkey"):
        v = str(value).lower().replace(" ", "")
        if v == "":
            return ""                                   # cleared (0.9.1): no shortcut; the Start menu and the icon open it
        return v if _HOTKEY.match(v) else d
    if key in ("text_model", "photo_model"):
        from . import models
        return value if isinstance(value, str) and value in models.ids(key[:-6]) else d
    if key == "language_focus":
        return value if value in ("", "english", "multilingual", "hindi") else d
    if key == "games_mode":
        return value if value in ("smart", "always", "off") else d
    if key == "settings_rev":
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000 else d
    if key == "wsearch_prev":
        return value if value in WSEARCH_STARTS else d
    if key == "theme":
        return value if value in ("dark", "light") else d
    if key == "scope":
        return value if value in SCOPES else d
    if isinstance(d, bool):
        return value if isinstance(value, bool) else d
    return d


class Settings:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k in DEFAULTS:
                    if k in raw:
                        self.data[k] = coerce(k, raw[k])
                if raw.get("pause_fullscreen") is False and "games_mode" not in raw:
                    self.data["games_mode"] = "off"
                if "scope" not in raw:          # before scopes: a folder list meant exactly those folders
                    self.data["scope"] = "custom" if self.data["roots"] else "whole_pc"
                rev = raw.get("settings_rev") if isinstance(raw.get("settings_rev"), int) else 0
                self.data["settings_rev"] = rev
                self._migrate()
        except (OSError, ValueError):
            pass

    def _migrate(self):
        """One-time changes to saved settings, each run once (settings_rev). Saved if anything ran."""
        rev = self.data.get("settings_rev", 0)
        if rev >= 2:
            return
        if rev >= 1:
            self._migrate_2()
            return
        from . import hotkey
        # 0.9.0: closing the window keeps NOBAD Find in the notification area (maintainer, 2026-11-20), so the
        # hotkeys work after closing. The old defaults were taken on many PCs (Win+Shift+Space is Windows'
        # keyboard-layout switch); a combination Windows keeps for itself never worked, so it goes too.
        self.data["stay_running"] = True
        if self.data.get("hotkey") == "win+shift+space" or hotkey.reserved(self.data.get("hotkey", "")):
            self.data["hotkey"] = DEFAULTS["hotkey"]
        if self.data.get("bar_hotkey") == "ctrl+alt+space" or hotkey.reserved(self.data.get("bar_hotkey", "")):
            self.data["bar_hotkey"] = DEFAULTS["bar_hotkey"]
        self.data["settings_rev"] = 1
        self._migrate_2()

    def _migrate_2(self):
        """0.9.1 (maintainer, 2026-11-20): one NOBAD Find window with everything: the quick find bar goes off."""
        self.data["bar"] = False
        self.data["settings_rev"] = 2
        try:
            self._save()
        except OSError:
            pass                                    # read-only folder: the same changes run at the next start

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def all(self):
        return dict(self.data)

    def update(self, changes):
        """Apply known keys only; returns the keys that changed. All or nothing: every value is checked first,
        then they are applied and saved together."""
        new = {k: coerce(k, v) for k, v in (changes or {}).items() if k in DEFAULTS}
        with self._lock:
            changed = [k for k, v in new.items() if v != self.data.get(k)]
            if changed:
                old = dict(self.data)
                self.data.update({k: new[k] for k in changed})
                try:
                    self._save()
                except Exception:
                    self.data = old                      # not saved: not changed
                    raise
        return changed

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)
