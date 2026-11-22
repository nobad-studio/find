"""Settings: a small JSON file, every value checked against DEFAULTS before it is used or saved."""
import json
import os
import re
import threading

from .const import DEFAULTS

_HOTKEY = re.compile(r"^(?:(?:ctrl|alt|shift|win)\+){1,3}(?:[a-z0-9]|space|f(?:[1-9]|1[0-2]))$")
WSEARCH_STARTS = ("", "auto", "delayed-auto", "demand", "disabled")
SCOPES = ("whole_pc", "my_files", "custom")
# At most this many folders in roots / exclude. Forget adds one path each time, so it is large (security review
# 2026-11-22, M4: at 200, a newly forgotten file was silently dropped and came back). Api.forget refuses with a
# message when the list is full; a longer list here keeps the newest entries (the end), never the oldest.
MAX_PATHS = 5000


def _paths(v):
    if not isinstance(v, list):
        return []
    out = []
    for p in v[-MAX_PATHS * 4:]:
        if isinstance(p, str) and 2 < len(p) < 1024 and os.path.isabs(p) and "\x00" not in p:
            out.append(os.path.normpath(p))
    return list(dict.fromkeys(out))[-MAX_PATHS:]


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
    if key == "power":
        return value if value in ("balanced", "boost") else d
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


FORGOTTEN_FILE = "forgotten.dat"


def _protect(data):
    from .winapi import dpapi_protect
    return dpapi_protect(data)


def _unprotect(data):
    from .winapi import dpapi_unprotect
    return dpapi_unprotect(data)


# Said (Api.forget) while forgotten entries are kept only in memory: the protected file couldn't be read or written
FORGOT_NOTE = ("Forgotten for now, but NOBAD Find couldn't save its protected list of forgotten files, so this one "
               "may come back after a restart. It tries again at the next change.")


class Settings:
    """The settings file, plus the files and folders Forget added to `exclude` (fix round 1, I5): those are kept
    apart in FORGOTTEN_FILE next to it, protected with DPAPI for this Windows account, never in settings.json.
    In memory `exclude` holds both (the walk, the turbo filter and the Never index list see one list); _save
    splits them again. When the protected file can't be read (it is never overwritten then) or written (DPAPI, an
    antivirus lock: once in the save, then FORGOT_TRIES - 1 times more on a thread that waits without the lock),
    new entries are kept in memory only, never in plain text, and every later save tries again (`note` says so; 1.1.0, review minors (a) and (c)). Entries that were in settings.json
    before they were kept apart stay there until the protected file holds them."""

    FORGOT_TRIES = 3
    FORGOT_WAIT_S = 0.1

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULTS)
        self._forgot = set()
        self._forgot_read = False                       # until the protected file is read, _save leaves it alone
        self._forgot_saved = True                       # the protected file holds every forgotten entry
        self._plain = set()                             # exclude entries read from settings.json
        self.note = ""                                  # FORGOT_NOTE while some are kept in memory only
        self._retry_thread = None                       # _retry_later
        self._fpath = os.path.join(os.path.dirname(path), FORGOTTEN_FILE)
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
                self._plain = set(self.data["exclude"])
                self._migrate()
        except (OSError, ValueError):
            pass
        self._load_forgotten()

    # ---------- what Forget added (DPAPI-protected, apart from settings.json) ----------
    def _load_forgotten(self):
        try:
            with open(self._fpath, "rb") as f:
                got = json.loads(_unprotect(f.read()).decode("utf-8"))
        except FileNotFoundError:
            self._forgot_read = True
            return
        except (OSError, ValueError, UnicodeDecodeError):
            if not self.note:
                from .log import log
                log("the forgotten list couldn't be read; it is left as it is", "warn")
            return                                      # never overwritten: another account's or a broken copy
        self._forgot_read = True
        paths = _paths(got if isinstance(got, list) else [])
        self._forgot |= set(paths)                      # (read again later: what was forgotten meanwhile stays)
        ex = list(self.data.get("exclude") or [])
        self.data["exclude"] = _paths(ex + [p for p in paths if p not in ex])

    def forgotten(self):
        """The Never index entries Forget added (they also are in get("exclude"))."""
        with self._lock:
            return [e for e in self.data.get("exclude") or [] if e in self._forgot]

    def forget(self, path):
        """Add path to exclude as a forgotten entry and save, all under the lock (two windows forgetting at once
        both stay). "ok", "full" (MAX_PATHS entries) or "known" (already there). Raises OSError when it can't be
        saved; nothing changed then."""
        path = os.path.normpath(path)
        with self._lock:
            ex = list(self.data.get("exclude") or [])
            if path in ex:
                return "known"
            if len(ex) >= MAX_PATHS:
                return "full"
            old, old_forgot = dict(self.data), set(self._forgot)
            self.data["exclude"] = ex + [path]
            self._forgot.add(path)
            try:
                self._save()
            except Exception:
                self.data, self._forgot = old, old_forgot
                raise
        return "ok"

    def mark_forgotten(self, paths):
        """One-time move (fix round 1, I5): entries of exclude that Forget added before they were kept apart leave
        settings.json for the protected file. Returns how many moved."""
        with self._lock:
            ex = set(self.data.get("exclude") or [])
            new = {os.path.normpath(p) for p in paths if isinstance(p, str)} & ex - self._forgot
            if not new and self.forgotten_saved():
                return 0
            old_forgot = set(self._forgot)
            self._forgot |= new
            try:
                self._save()                             # (an earlier move that wasn't saved is tried again)
            except Exception:
                self._forgot = old_forgot
                raise
        return len(new)

    def forgotten_saved(self):
        """True when the protected file holds every forgotten entry: none is only in memory or still in
        settings.json (Api._migrate_forgotten is done only then)."""
        return self._forgot_read and self._forgot_saved and not (self._forgot & self._plain)

    def retry_forgotten(self):
        """Save again if some forgotten entries are kept only in memory (the protected file couldn't be read or
        written). True when they are all protected now."""
        with self._lock:
            if self.forgotten_saved():
                return True
            try:
                self._save()
            except OSError:
                pass
            return self.forgotten_saved()

    def _write_forgotten(self, paths):
        """True when the protected file holds exactly paths (or is gone because there are none)."""
        if not paths:
            try:
                os.remove(self._fpath)
            except FileNotFoundError:
                pass
            return True
        try:
            blob = _protect(json.dumps(paths).encode("utf-8"))
        except (OSError, AttributeError, NameError):
            return False
        tmp = self._fpath + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, self._fpath)
        return True

    def _write_forgotten_once(self, paths):
        """_write_forgotten without raising: False when it didn't work (DPAPI, an antivirus or backup tool holding
        the file). The caller keeps the entries in memory, never in settings.json, and _retry_later tries again."""
        try:
            if self._write_forgotten(paths):
                return True
        except OSError:
            pass
        try:
            os.remove(self._fpath + ".tmp")
        except OSError:
            pass
        return False

    def _retry_later(self):
        """Try the protected list again FORGOT_TRIES - 1 times, waiting FORGOT_WAIT_S, 2x, ... in between, on a
        thread that waits WITHOUT the settings lock (fix round 1, M3: a locked file never makes a save slow). One
        such thread at a time; a save after it gave up starts another."""
        if self._retry_thread is not None and self._retry_thread.is_alive():
            return
        import time

        def run():
            for i in range(self.FORGOT_TRIES - 1):
                time.sleep(self.FORGOT_WAIT_S * (i + 1))
                if self.retry_forgotten():
                    return
        self._retry_thread = threading.Thread(target=run, daemon=True, name="forgotten-retry")
        self._retry_thread.start()

    def _migrate(self):
        """One-time changes to saved settings, each run once (settings_rev). Saved if anything ran."""
        rev = self.data.get("settings_rev", 0)
        if rev >= 3:
            return
        if rev >= 2:
            self._migrate_3()
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
        self._migrate_3()

    def _migrate_3(self):
        """0.9.3 (maintainer, 2026-11-20): the shortcut opens the search bar when the window isn't open (like
        Spotlight), so the bar is on again."""
        self.data["bar"] = True
        self.data["settings_rev"] = 3
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
        if not self._forgot_read:
            self._load_forgotten()                      # unreadable before: maybe it can be read now (never overwritten)
        ex = list(self.data.get("exclude") or [])
        self._forgot &= set(ex)                         # taken out of Never index: no longer forgotten
        self._plain &= set(ex)
        forgot = [e for e in ex if e in self._forgot]
        plain = dict(self.data)
        # the protected file first: a crash in between leaves both copies, never none
        self._forgot_saved = self._forgot_read and self._write_forgotten_once(forgot)
        if self._forgot_saved:
            plain["exclude"] = [e for e in ex if e not in self._forgot]
            self._plain -= self._forgot
            self.note = ""
        else:                                           # in memory only; what settings.json already had stays there
            plain["exclude"] = [e for e in ex if e not in self._forgot or e in self._plain]
            if not self.note:
                from .log import log
                log("the forgotten list couldn't be saved protected; new entries are kept in memory", "warn")
            self.note = FORGOT_NOTE
            self._retry_later()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(plain, f, indent=1)
        os.replace(tmp, self.path)
