"""The engine's side of the optional turbo index (the elevated reader is ntfs.py; the privacy reasoning is there;
the one-time setup, paths and DACLs are in turbosvc.py).

Maintainer decision 2026-11-21: administrator rights are asked for ONCE, when the user turns turbo on.
- `turbo_set {on: true}` -> Turbo.turn_on: if the helper isn't set up for this account and this NobadFind.exe, or
  its files differ from the ones this version ships (HelperSetup.status), Windows asks once (`NobadFindTurbo.exe
  --turbo install`, elevated); saying no leaves the setting off. Then, with no prompt, the engine starts the service
  with its own rights, connects to the service's pipe as the client, checks the server is the service's process
  (PipeLink.start) and sends the scope.
- With the setting on, the indexer starts it once per engine run (ensure) when indexing starts, WITHOUT a prompt.
  If the helper needs an update (a new NOBAD Find was installed) or was removed, the normal walk is used and the
  state says "Turbo needs your OK once to update its helper" until the user OKs it (`turbo_helper {action:
  "update"}`). The protected copy is never updated without that prompt.
- `turbo_set {on: false}` and `turbo_helper {action: "remove"}`: the link closes (the service ends with it) and
  Windows asks once to remove the service and its folder (`--turbo remove`). Saying no turns turbo off anyway and
  leaves the helper installed ("Remove" stays offered). `--uninstall` does the same (remove_on_uninstall).
- Indexer._scan_names calls scan(): each NTFS drive in the scope is read by the helper (or caught up from the saved
  journal place when the scope hasn't changed), the rows go through the engine's own rules (Walker.excluded, the
  same check live changes get) before they reach the index. Drives the helper didn't cover are walked as before.
- Changes from the journal go to Indexer._on_changes (the indexer looks at each path again as the normal user).
  A lost journal (reset, wrapped) means a full read again (Indexer.rescan). A helper that ends is reported and the
  folder notifications (watcher.py) carry on alone.
- State in the contract's turbo_state shape; every change is pushed as the `turbo` event.
- From source this is development only: without NOBAD_FIND_DEV_TURBO=1 the engine shows no permission prompt and
  says why (DEV_ONLY). With it, the old per-run elevated helper (`--turbo serve`, one prompt per run) is used, as a
  pipe server the engine connects to; a service is never set up from source (ntfs.py docstring). The installed exe
  is unaffected.
"""
import ctypes
import hashlib
import json
import os
import threading
import time
from ctypes import wintypes

from . import notify, ntfs, turbosvc, winapi
from .kinds import kind_of
from .log import log
from .walker import Walker

CONNECT_TIMEOUT = 60             # seconds from the permission prompt being answered to the helper's pipe (source)
SERVICE_START_S = 20             # seconds for the service to run and serve its pipe
SAVE_USN_EVERY = 30              # seconds between saves of the journal place while following
HELLO_WAIT = 10                  # seconds a scan waits for the helper to list its drives
QUIET_S = 120                   # a drive whose helper sends nothing this long is walked instead (0.9.1)
FULL_EVERY = 24 * 3600           # a catch-up can't see folders deleted while the engine was off: read it all daily

DECLINED = ("Windows didn't get permission (the prompt was closed or answered No). NOBAD Find keeps using its "
            "normal folder walk.")
UNAVAILABLE = "The turbo index needs an NTFS drive in what you index; none was found, so the normal walk is used."
ENDED = "The turbo helper stopped; NOBAD Find went back to its normal folder walk and change notifications."
NEEDS_UPDATE = ("Turbo needs your OK once to update its helper. Until then NOBAD Find uses its normal folder walk.")
NOT_SET_UP = ("Turbo's helper isn't set up any more. Turn turbo off and on again (Windows asks once). Until then "
              "NOBAD Find uses its normal folder walk.")
KEPT = ("Turbo is off. Its helper is still installed because Windows didn't get permission to remove it; use "
        "Remove when you want it gone.")
SETUP_FAILED = {
    -1: "This NOBAD Find has no turbo helper (NobadFindTurbo.exe is missing). Installing NOBAD Find again fixes it.",
    3: "Windows didn't give the turbo helper administrator rights; nothing was changed.",
    4: "The turbo helper refused to set itself up (its folder or the account didn't check out); nothing was used.",
    7: "The turbo helper is only set up from NOBAD Find's installed app.",
    8: "The turbo helper's files changed while they were copied, so they weren't used. Try again.",
    9: "Another program already has a Windows service named NOBADFindTurbo, so turbo can't set up its own.",
}
SETUP_OTHER = "The turbo helper couldn't be set up (error {code}); NOBAD Find keeps using its normal folder walk."
HELPER_ACTIONS = ("update", "remove")


class Declined(Exception):
    """The user said no at the UAC prompt."""


class SetupFailed(Exception):
    """The elevated install/remove step ran and refused or failed (its exit code)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code

    @property
    def sentence(self):
        return SETUP_FAILED.get(self.code) or SETUP_OTHER.format(code=self.code)


class HelperSetup:
    """The protected copy and its service as seen from the engine (normal user rights; asking for the elevated
    install/remove step is the only thing that prompts). kind: "service" (the installed app) or "dev" (from
    source: the old per-run helper, nothing is ever installed)."""

    TTL = 30.0

    def __init__(self, scm=None, elevate=None, frozen=None, clock=time.monotonic):
        import sys
        self.kind = "service" if (getattr(sys, "frozen", False) if frozen is None else frozen) else "dev"
        self.scm = scm or turbosvc.Scm()
        self._elevate = elevate or winapi.run_elevated
        self._clock = clock
        self._own = None
        self._cached = None

    def helper_exe(self):
        return os.path.join(turbosvc.user_helper_dir(), turbosvc.EXE)

    def own_manifest(self):
        """The manifest hash of the helper files this NOBAD Find ships (computed once per engine run: the
        installer ends the engine before it replaces them)."""
        if self._own is None:
            try:
                self._own = turbosvc.manifest_hash(turbosvc.manifest(turbosvc.user_helper_dir()))
            except (OSError, ValueError) as e:
                log(f"turbo: the helper's own files can't be read: {type(e).__name__}", "warn")
                return None
        return self._own

    def forget(self):
        self._cached = None

    def status(self):
        """(turbosvc.INSTALLED / NEEDS_UPDATE / NOT_INSTALLED, why)."""
        if self.kind != "service":
            return turbosvc.NOT_INSTALLED, ""
        now = self._clock()
        if self._cached is not None and now - self._cached[0] < self.TTL:
            return self._cached[1]
        try:
            root = turbosvc.protected_root()
            rec = turbosvc.read_record(root)
            try:
                cfg = self.scm.config()
            except PermissionError:                  # this account may not even query it: another account's
                r = (turbosvc.NOT_INSTALLED, turbosvc.OTHER_ACCOUNT)
                self._cached = (now, r)
                return r
            from .rpc import server as srv
            r = turbosvc.helper_status(rec, cfg.command if cfg else None, self.own_manifest(), srv.user_sid(),
                                       ntfs.own_image(), turbosvc.service_command(root))
        except (OSError, ValueError) as e:
            log(f"turbo: helper state unknown: {type(e).__name__}", "warn")
            r = (turbosvc.NOT_INSTALLED, "")
        self._cached = (now, r)
        return r

    def _run(self, word):
        self.forget()
        code = self._elevate([self.helper_exe(), "--turbo", word])
        self.forget()
        if code is None:
            raise Declined()
        if code != 0:
            raise SetupFailed(code)

    def install(self):
        if self.kind != "service":
            raise DevOnly("a service is never set up from source")
        if not os.path.isfile(self.helper_exe()):
            raise SetupFailed(-1)
        self._run("install")

    def remove(self):
        if self.kind == "service":
            self._run("remove")


def remove_on_uninstall(setup=None):
    """--uninstall: if turbo's helper is set up for THIS account (its record names this user, or a service this user
    may query is there), Windows asks once to remove it. Another account's helper is left alone (this user can't
    even query its service). True when nothing of this account's is left."""
    setup = setup or HelperSetup()
    if setup.kind != "service":
        return True
    try:
        cfg = setup.scm.config()
    except PermissionError:
        return True                                   # another account's service: not ours to remove
    except OSError:
        cfg = None
    try:
        rec = turbosvc.read_record(turbosvc.protected_root())
    except (OSError, ValueError):
        rec = None
    if cfg is None and rec is None:
        return True
    if rec is not None:
        from .rpc import server as srv
        try:
            if rec.user_sid != srv.user_sid():
                return True                           # set up for another account on this PC
        except OSError:
            return False
    try:
        setup.remove()
    except (Declined, SetupFailed, OSError):
        return False
    return True


class DevOnly(PermissionError):
    """From source without NOBAD_FIND_DEV_TURBO=1 (ntfs.py docstring): no permission prompt is shown."""


DEV_ONLY = ("The turbo index runs from NOBAD Find's installed app. From source it is for development only: set "
            "NOBAD_FIND_DEV_TURBO=1 (see nobadfind/ntfs.py).")


def drive_of(path):
    d = os.path.splitdrive(path)[0]
    return d.upper() + "\\" if len(d) == 2 and d[1] == ":" else ""


class Turbo:
    def __init__(self, settings, store, indexer, push=None, launch=None, ntfs_drive=None, drives=None,
                 clock=time.time, setup=None):
        self.settings, self.store, self.indexer = settings, store, indexer
        self._push = push
        self.setup = setup or HelperSetup()
        self._launch = launch or self._launch_helper
        self._ntfs = ntfs_drive or ntfs.is_ntfs_fixed
        self._drives = drives or winapi.drives
        self._clock = clock
        self._lock = threading.Lock()              # one turn_on / turn_off at a time
        self._mlock = threading.Lock()             # state touched by the helper's messages
        self._link = None
        self._helper_volumes = set()
        self._hello = threading.Event()            # the helper said which drives it can read
        self._vols = {}                            # drive -> {files, usn_ok, last_scan}
        self._waiting = {}                         # drive -> {"ev", "on_rows", "gen", "check", "result"}
        self._asked = False
        self._ntfs_cache = {}
        self.error = ""
        self._saved_at = 0.0

    # ----- state -----
    def running(self):
        link = self._link
        return link is not None and getattr(link, "alive", True)

    def helper_pid(self):
        """The running helper's process id (the Index page's Processes), 0 when there is none."""
        link = self._link
        return int(getattr(link, "pid", 0) or 0) if link is not None and getattr(link, "alive", True) else 0

    def _is_ntfs(self, d):
        if d not in self._ntfs_cache:
            try:
                self._ntfs_cache[d] = bool(self._ntfs(d))
            except Exception:
                self._ntfs_cache[d] = False
        return self._ntfs_cache[d]

    def state(self):
        fixed = [d["root"].upper() for d in self._drives() if d.get("type") == "fixed"]
        vols = []
        with self._mlock:
            for d in fixed:
                v = self._vols.get(d, {})
                vols.append({"drive": d, "ntfs": self._is_ntfs(d), "files": int(v.get("files", 0)),
                             "usn_ok": bool(v.get("usn_ok")) and self.running(), "last_scan": v.get("last_scan")})
        return {"available": any(v["ntfs"] for v in vols), "enabled": bool(self.settings.get("turbo")),
                "running": self.running(), "volumes": vols, "error": self.error,
                "helper": self.setup.status()[0]}

    def _changed(self):
        if self._push is not None:
            try:
                self._push(self.state())
            except Exception as e:
                log(f"turbo event failed: {type(e).__name__}", "warn")

    def follows(self, path):
        """True if the change journal covers this path now (a watcher overflow needs no rescan there)."""
        d = drive_of(path)
        with self._mlock:
            return self.running() and bool(self._vols.get(d, {}).get("usn_ok"))

    # ----- on and off -----
    def ensure(self):
        """With the setting on: start the helper once per engine run. The installed app never prompts here (a
        helper that needs an update waits for the user's OK); from source (dev) the per-run prompt."""
        if not self.settings.get("turbo") or self.running() or self._asked:
            return
        self.turn_on(keep_on_failure=True)

    def _set_up(self, keep_on_failure, force=False):
        """The installed app: the helper must be set up and current. On the user's action (not keep_on_failure)
        Windows asks once; at engine start never. Returns None when it is ready, else the failure answer."""
        if self.setup.kind != "service":
            return None
        st, why = self.setup.status()
        if st == turbosvc.INSTALLED and not force:
            return None
        if keep_on_failure:
            self.error = NEEDS_UPDATE if st == turbosvc.NEEDS_UPDATE else (
                why + " Turn turbo off and on again to set it up for you (Windows asks once)."
                if why == turbosvc.OTHER_ACCOUNT else NOT_SET_UP)
            if why:
                log(f"turbo: {why}")
            if st == turbosvc.NEEDS_UPDATE:
                notify.post("turbo_needs_ok", "Turbo needs your OK",
                            "The turbo index helper changed with this version of NOBAD Find. Until you OK the "
                            "update (Windows asks once), NOBAD Find uses its normal folder walk.", "warning",
                            action="open_turbo", key="turbo-needs-ok", every=86400)
            return self._failed(True)
        try:
            self.setup.install()
        except Declined:
            self.error = DECLINED
            return self._failed(False)
        except SetupFailed as e:
            log(f"turbo setup failed: exit {e.code}", "warn")
            self.error = e.sentence
            return self._failed(False)
        except (OSError, DevOnly) as e:
            log(f"turbo setup didn't run: {type(e).__name__}", "warn")
            self.error = SETUP_OTHER.format(code=getattr(e, "winerror", 0) or 0)
            return self._failed(False)
        if self.setup.status()[0] != turbosvc.INSTALLED:
            self.error = "Turbo's helper was set up but doesn't match this NOBAD Find; the normal walk is used."
            return self._failed(False)
        return None

    def turn_on(self, keep_on_failure=False, force_setup=False):
        with self._lock:
            self._asked = True
            if self.running() and not force_setup:
                return {"ok": True, "error": ""}
            if not self.state()["available"]:
                self.error = UNAVAILABLE
                return self._failed(keep_on_failure)
            if force_setup:
                self._close_link()
            failed = self._set_up(keep_on_failure, force=force_setup)
            if failed is not None:
                return failed
            self._hello.clear()
            try:
                link = self._launch()
            except Declined:
                self.error = DECLINED
                return self._failed(keep_on_failure)
            except DevOnly:
                self.error = DEV_ONLY
                return self._failed(keep_on_failure)
            except (OSError, PermissionError, TimeoutError) as e:
                log(f"turbo helper didn't start: {type(e).__name__} {getattr(e, 'winerror', '') or ''}", "warn")
                self.error = "The turbo helper didn't start; NOBAD Find keeps using its normal folder walk."
                return self._failed(keep_on_failure)
            self._link = link
            self.error = ""
            self.settings.update({"turbo": True})
            try:
                link.send(self._config(self.indexer.roots()))
            except OSError:
                self.link_closed()
                return {"ok": False, "error": self.error}
            log("turbo helper running")
        self._changed()
        return {"ok": True, "error": ""}

    def _failed(self, keep_on):
        if not keep_on:
            self.settings.update({"turbo": False})
        log(f"turbo: {self.error}", "warn")
        self._changed()
        return {"ok": False, "error": self.error}

    def turn_off(self):
        """Off: the link closes (the helper ends), then Windows asks once to remove the helper. No there keeps it
        installed (and says so); turbo is off either way."""
        with self._lock:
            self._close_link()
            self.settings.update({"turbo": False})
            self.error = ""
            self._release_waiters()
            if self.setup.kind == "service" and self.setup.status()[0] != turbosvc.NOT_INSTALLED:
                try:
                    self.setup.remove()
                except Declined:
                    self.error = KEPT
                except (SetupFailed, OSError) as e:
                    log(f"turbo remove failed: {getattr(e, 'code', type(e).__name__)}", "warn")
                    self.error = KEPT
        self._changed()
        return {"ok": True, "error": self.error}

    def helper_action(self, action):
        """`turbo_helper`: "update" (Windows asks once; then turbo starts if it is on) or "remove" (= turn_off)."""
        if action not in HELPER_ACTIONS:
            raise ValueError(action)
        if action == "remove":
            return self.turn_off()
        if self.setup.kind != "service":
            self.error = DEV_ONLY
            self._changed()
            return {"ok": False, "error": DEV_ONLY}
        if self.settings.get("turbo"):
            return self.turn_on(force_setup=True)
        with self._lock:                                   # turbo is off: only bring the helper up to date
            failed = self._set_up(False, force=True)
        if failed is not None:
            return failed
        self.error = ""
        self._changed()
        return {"ok": True, "error": ""}

    def _close_link(self):
        link, self._link = self._link, None
        if link is not None:
            try:
                link.send({"t": "stop"})
            except OSError:
                pass
            link.close()

    def stop(self):
        """The engine is ending: the helper goes with it (and would on its own when the pipe closes)."""
        self._close_link()

    def link_closed(self):
        """The helper's pipe ended without turn_off."""
        if self._link is None:
            return
        self._link = None
        self.error = ENDED
        log("turbo helper ended", "warn")
        self._release_waiters()
        self._changed()

    def _release_waiters(self):
        with self._mlock:
            for w in self._waiting.values():
                w["ev"].set()

    # ----- the scope it may send -----
    def _config(self, roots):
        get = self.settings.get
        return {"t": "config", "roots": [r for r in roots if drive_of(r)], "exclude": list(get("exclude") or []),
                "include_system": bool(get("include_system")), "include_caches": bool(get("include_caches")),
                "include_secrets": bool(get("include_secrets")), "secret_app_files": bool(get("secret_app_files"))}

    @staticmethod
    def _key(cfg):
        return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:16]

    def _saved(self):
        try:
            v = json.loads(self.store.meta("turbo", "{}") or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}

    # ----- reading drives -----
    def scan(self, roots, gen, on_rows, stop):
        """Read every NTFS drive in roots with the helper. Returns (drives read in full, drives caught up from the
        journal); the caller walks the rest. on_rows gets rows ready for Store.upsert_files."""
        full, caught = set(), set()
        link = self._link
        if not self.running():
            if self.settings.get("turbo"):
                log("turbo: on, but its helper isn't running; the normal folder walk reads the drives")
            return full, caught
        cfg = self._config(roots)
        key = self._key(cfg)
        try:
            link.send(cfg)
        except OSError:
            self.link_closed()
            return full, caught
        if not self._hello.wait(HELLO_WAIT):
            log(f"turbo: the helper didn't answer in {HELLO_WAIT:g} s; the normal folder walk reads the drives", "warn")
            return full, caught
        rules = self.indexer.rules()
        check = _Checker(Walker(roots, exclude=cfg["exclude"], rules=rules), rules)
        saved = self._saved()
        asked = {drive_of(r) for r in roots}
        want = sorted(asked & self._helper_volumes)
        if not want:
            log(f"turbo: nothing to read (drives {sorted(asked)}, the helper's NTFS volumes {sorted(self._helper_volumes)})")
        for d in want:
            prev = saved.get(d) if isinstance(saved.get(d), dict) else None
            fresh = prev and self._clock() - float(prev.get("full_at") or 0) < FULL_EVERY
            since = {"journal": prev["journal"], "usn": prev["usn"]} if fresh and prev.get("key") == key and all(
                isinstance(prev.get(k), int) for k in ("journal", "usn")) else None
            w = {"ev": threading.Event(), "on_rows": on_rows, "gen": gen, "check": check, "result": None, "files": 0}
            with self._mlock:
                self._waiting[d] = w
            log(f"turbo: reading {d} ({'changes since the last read' if since else 'all of it'})")
            try:
                link.send({"t": "scan", "drive": d, "since": since})
            except OSError:
                self.link_closed()
            # 0.9.1: never wait forever. Each batch of rows restarts the clock; a helper that goes quiet for
            # QUIET_S leaves that drive to the normal folder walk (it used to freeze the whole indexer).
            w["heard"] = self._clock()
            while not w["ev"].wait(0.5):
                if stop.is_set() or not self.running():
                    break
                if self._clock() - w["heard"] > QUIET_S:
                    log(f"turbo: {d} sent nothing for {QUIET_S} s ({w['files']} entries so far); "
                        "the normal folder walk reads it", "warn")
                    self.error = f"Turbo stopped answering for {d}; that drive uses the normal folder walk."
                    break
            with self._mlock:
                self._waiting.pop(d, None)
            r = w["result"]
            if r is None:
                if not stop.is_set():
                    log(f"turbo: {d} not read; the normal folder walk reads it")
                continue
            (full if r["full"] else caught).add(d)
            full_at = self._clock() if r["full"] else float((prev or {}).get("full_at") or 0)
            saved[d] = {"journal": r["journal"], "usn": r["usn"], "key": key, "full_at": full_at}
            self.store.set_meta("turbo", json.dumps(saved))
            with self._mlock:
                v = self._vols.setdefault(d, {})
                v.update(usn_ok=bool(r["usn_ok"]), last_scan=self._clock())
                if r["full"]:
                    v["files"] = w["files"]
            log(f"turbo: {d} {'read' if r['full'] else 'caught up'} ({w['files']} entries)")
            self._changed()
        return full, caught

    def forget_place(self):
        """A rescan was asked for (settings, Rescan): read everything again instead of catching up."""
        self.store.set_meta("turbo", "{}")

    # ----- the helper's messages -----
    def on_message(self, msg):
        try:
            self._on_message(msg)
        except Exception as e:                         # a malformed message is ignored, never fatal
            log(f"turbo message ignored: {type(e).__name__}", "warn")

    def _on_message(self, msg):
        t = msg.get("t")
        d = msg.get("drive")
        if t != "hello" and not (isinstance(d, str) and ntfs.DRIVE_RE.match(d)):
            return
        if t == "hello":
            vols = msg.get("volumes")
            if isinstance(vols, list):
                self._helper_volumes = {v["drive"].upper() for v in vols if isinstance(v, dict) and isinstance(
                    v.get("drive"), str) and ntfs.DRIVE_RE.match(v["drive"])}
            self._hello.set()
        elif t == "rows":
            with self._mlock:
                w = self._waiting.get(d)
            rows = msg.get("rows")
            if w is None or not isinstance(rows, list):
                return
            out = [r for r in (w["check"].row(x, d, w["gen"]) for x in rows) if r is not None]
            w["files"] += len(out)
            w["heard"] = self._clock()
            with self._mlock:
                self._vols.setdefault(d, {})["files"] = w["files"]     # progress shows while it reads
            if out:
                w["on_rows"](out)
        elif t == "scanned":
            with self._mlock:
                w = self._waiting.get(d)
            if w is None:
                return
            j, u = msg.get("journal"), msg.get("usn")
            if not (isinstance(j, int) and isinstance(u, int)):
                return
            w["result"] = {"full": bool(msg.get("full")), "journal": j, "usn": u, "usn_ok": bool(msg.get("usn_ok"))}
            w["ev"].set()
        elif t == "failed":
            with self._mlock:
                w = self._waiting.get(d)
                self._vols.setdefault(d, {})["usn_ok"] = False
            self.error = f"Turbo couldn't read {d}; that drive uses the normal folder walk."
            log(f"turbo: {d} failed ({str(msg.get('error'))[:80]})", "warn")
            if w is not None:
                w["ev"].set()
            self._changed()
        elif t == "changes":
            paths = msg.get("paths")
            if not isinstance(paths, list):
                return
            ok = {p for p in paths if isinstance(p, str) and 3 <= len(p) < 32768 and drive_of(p) == d.upper()
                  and os.path.isabs(p) and "\x00" not in p}
            if ok:
                self.indexer._on_changes(d, ok)
        elif t == "usn":
            j, u = msg.get("journal"), msg.get("usn")
            now = self._clock()
            if isinstance(j, int) and isinstance(u, int) and now - self._saved_at >= SAVE_USN_EVERY:
                saved = self._saved()
                if isinstance(saved.get(d), dict) and saved[d].get("journal") == j:
                    saved[d]["usn"] = u
                    self.store.set_meta("turbo", json.dumps(saved))
                    self._saved_at = now
        elif t == "journal":
            with self._mlock:
                self._vols.setdefault(d, {})["usn_ok"] = False
            log(f"turbo: change journal of {d} lost; reading it again", "warn")
            self.forget_place()
            self.indexer.rescan()
            self._changed()

    # ----- the real helper (Windows) -----
    def _launch_helper(self):
        return PipeLink.start(self)


class _Checker:
    """The engine's own rules on every row the helper sends (it already dropped what it must; this is the engine
    not trusting a more privileged process to have the same idea of the scope)."""

    def __init__(self, walker, rules):
        self.w, self.rules = walker, rules
        self._dirs = {}

    def _dir_ok(self, d):
        ok = self._dirs.get(d)
        if ok is None:
            ok = self._dirs[d] = not self.w.excluded(d)
        return ok

    def row(self, x, drive, gen):
        if not (isinstance(x, list) and len(x) == 5):
            return None
        path, is_dir, size, mtime, ctime = x
        if not (isinstance(path, str) and 3 < len(path) < 32768 and "\x00" not in path and os.path.isabs(path)
                and drive_of(path) == drive.upper() and is_dir in (0, 1)):
            return None
        if not (size is None or (isinstance(size, int) and not isinstance(size, bool) and size >= 0)):
            return None
        if not all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)) for v in (mtime, ctime)):
            return None
        parent, name = os.path.split(path)
        if not name or not self._dir_ok(parent):
            return None
        if is_dir:
            if self.w.excluded(path):
                return None
            return (path, name, parent, "", "folder", 0, mtime, ctime, gen)
        if self.rules.skip_file(name):
            return None
        return (path, name, parent, os.path.splitext(name)[1].lower(), kind_of(name), size, mtime, ctime, gen)


# ---------- the pipe to the helper (Windows) ----------
_W = {}


def _win():
    if not _W:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
        for name, res, args in (("GetProcessId", D, [H]),
                                ("GetNamedPipeClientSessionId", B, [H, ctypes.POINTER(D)]),
                                ("GetNamedPipeClientProcessId", B, [H, ctypes.POINTER(D)]),
                                ("ProcessIdToSessionId", B, [D, ctypes.POINTER(D)]),
                                ("GetCurrentProcessId", D, []),
                                ("WaitForMultipleObjects", D, [D, ctypes.POINTER(H), B, D]),
                                ("CloseHandle", B, [H]),
                                ("AssignProcessToJobObject", B, [H, H])):
            f = getattr(k, name)
            f.restype, f.argtypes = res, args
        _W["k"] = k
    return _W["k"]


def helper_argv():
    """The elevated helper's command line: the exe with a fixed word, or (from source) the same Python, isolated
    (-I: no user site-packages, no current folder on the path) with the package folder given explicitly."""
    import sys
    if getattr(sys, "frozen", False):
        return [sys.executable, "--turbo", "serve"]
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = (f"import sys; sys.path.insert(0, {pkg_parent!r}); import runpy; "
            "runpy.run_module('nobadfind', run_name='__main__', alter_sys=True)")
    return [sys.executable, "-I", "-c", code, "--turbo", "serve"]


def dev_allowed():
    """The exe always; from source only with NOBAD_FIND_DEV_TURBO=1 (the prompt would name python.exe, and the
    elevated interpreter would import from the user-writable source tree)."""
    import sys
    return bool(getattr(sys, "frozen", False)) or os.environ.get(ntfs.DEV_ENV) == "1"


def start_elevated(argv):
    """ShellExecuteEx "runas" (the UAC prompt), not waiting: the helper's process handle. Raises Declined."""
    sei = winapi._SEI()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x40 | 0x400                       # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI
    sei.lpVerb = "runas"
    sei.lpFile = argv[0]
    import subprocess
    import sys
    sei.lpParameters = subprocess.list2cmdline(argv[1:])
    sei.lpDirectory = None if getattr(sys, "frozen", False) else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    sei.nShow = 0
    if not winapi.shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error() or ctypes.GetLastError()
        if err == 1223:                            # ERROR_CANCELLED: No at the prompt
            raise Declined()
        raise OSError(err, "runas")
    if not sei.hProcess:
        raise OSError(0, "no process handle")
    return sei.hProcess


class PipeLink:
    """The engine's end (the CLIENT since 2026-11-21): the service's pipe, or from source the per-run elevated
    helper's. send() writes a line; the reader thread hands each message to turbo.on_message and calls
    turbo.link_closed() when the pipe ends."""

    def __init__(self, turbo, pipe, proc, pid):
        self.turbo, self.pipe, self.proc = turbo, pipe, proc
        self.alive = True
        self.pid = pid                       # the helper's process id (the service's, or the elevated helper's)
        threading.Thread(target=self._read, daemon=True, name="turbo-pipe").start()

    @classmethod
    def start(cls, turbo, timeout=CONNECT_TIMEOUT):
        if turbo.setup.kind == "service":
            h, proc, pid = cls._connect_service(turbo.setup.scm)
        else:
            h, proc, pid = cls._connect_dev(timeout)
        pipe = ntfs._Pipe(h)
        link = cls(turbo, pipe, proc, pid)
        try:
            link.send({"t": "hi", "protocol": ntfs.PROTOCOL})
        except OSError:
            link.close()
            raise
        return link

    @staticmethod
    def _connect_service(scm, wait_s=SERVICE_START_S):
        """Start the service with the user's own rights (no prompt), then open its pipe and check its server is the
        service's own process in session 0, and the service runs the protected copy."""
        from .rpc import server as srv
        root = turbosvc.protected_root()
        cfg = scm.config()
        if cfg is None or os.path.normcase(cfg.command.strip()) != os.path.normcase(turbosvc.service_command(root)):
            raise PermissionError("the turbo service isn't the protected copy")
        scm.start()
        began = time.monotonic()
        pid = 0
        while time.monotonic() - began < wait_s:
            st = scm.status()
            if st is None:
                raise OSError(0, "the turbo service is gone")
            if st[0] == turbosvc.RUNNING and st[1]:
                pid = st[1]
                break
            if st[0] == turbosvc.STOPPED and time.monotonic() - began > 2:
                raise OSError(0, "the turbo service stopped")
            time.sleep(0.1)
        if not pid:
            raise TimeoutError("the turbo service didn't start")

        def alive():
            s = scm.status()
            return bool(s) and s[0] == turbosvc.RUNNING and s[1] == pid
        h = turbosvc.open_client_pipe(turbosvc.service_pipe_name(srv.user_sid()), wait_s, alive)
        if not ntfs.server_ok(h, pid, 0):
            _win().CloseHandle(h)
            raise PermissionError("the turbo pipe isn't served by the turbo service")
        return h, None, pid

    @staticmethod
    def _connect_dev(timeout):
        """From source (NOBAD_FIND_DEV_TURBO=1): the per-run elevated helper (one prompt) serves the pipe; its
        server must be the process ShellExecuteEx started, in this session."""
        if not dev_allowed():
            raise DevOnly("from source without NOBAD_FIND_DEV_TURBO=1")
        from .rpc import server as srv
        w = _win()
        sid = srv.user_sid()
        proc = start_elevated(helper_argv())
        pid = w.GetProcessId(proc)
        from . import jobs
        if jobs.OUTER is not None and getattr(jobs.OUTER, "handle", None):
            if not w.AssignProcessToJobObject(jobs.OUTER.handle, proc):     # Windows may refuse for an elevated
                log("turbo helper is outside the job; it ends on its own with the engine")
        try:
            h = turbosvc.open_client_pipe(ntfs.pipe_name(sid, os.getpid()), timeout,
                                          lambda: ntfs._k32().WaitForSingleObject(proc, 0) != 0)
        except OSError:
            w.CloseHandle(proc)
            raise TimeoutError("the helper didn't serve its pipe")
        mine = wintypes.DWORD()
        w.ProcessIdToSessionId(w.GetCurrentProcessId(), ctypes.byref(mine))
        if not ntfs.server_ok(h, pid, mine.value):
            w.CloseHandle(h)
            w.CloseHandle(proc)
            raise PermissionError("the pipe isn't served by the helper NOBAD Find started")
        return h, proc, pid

    def send(self, msg):
        if not self.alive:
            raise OSError(0, "turbo pipe closed")
        try:
            self.pipe.send(msg)
        except OSError:
            self.alive = False
            raise

    def close(self):
        self.alive = False
        self.pipe.close()

    def _read(self):
        lines = ntfs.Lines()
        try:
            while self.alive:
                data = self.pipe.read()
                if not data:
                    break
                for msg in lines.feed(data):
                    self.turbo.on_message(msg)
        except ValueError:
            log("turbo helper sent a message that isn't one; closing", "warn")
        except Exception as e:
            log(f"turbo pipe ended: {type(e).__name__}", "warn")
        finally:
            was = self.alive
            self.alive = False
            self.pipe.close()
            if self.proc:
                _win().CloseHandle(self.proc)
                self.proc = None
            if was:
                self.turbo.link_closed()
