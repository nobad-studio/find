"""In-app updates (0.9.0, maintainer decision 2026-11-20): NOBAD Find looks for a newer release of itself, and on
the user's Install downloads that release's installer and runs it, which closes NOBAD Find, installs over it and
starts it again.

The connections, all HTTPS, only to GitHub, and only for nobad-studio/find:
  - api.github.com: the latest release (once a day while "Check for updates automatically" is on, and on Check now);
  - github.com and its download host: the installer and its .sha256 file, only after the user chose Install.
Nothing about the PC or its files is sent: a plain GET with a User-Agent.

The installer isn't code-signed yet, so what is checked is: HTTPS, the release's own asset names, the exact size
GitHub lists, and the SHA-256 against both the release's .sha256 file and the digest GitHub computed for the
upload. It runs only when all of them agree. The installer starts outside NOBAD Find's job (it must outlive the
engine it closes), with fixed arguments, never a shell string.
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.request

from . import notify
from .const import APP_VER, DATA_DIR
from .log import log

REPO = "nobad-studio/find"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD = f"https://github.com/{REPO}/releases/download/"
EVERY_S = 24 * 3600
TAG = re.compile(r"^find-v(\d+)\.(\d+)\.(\d+)$")
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
MAX_INSTALLER = 400 * 1024 * 1024
PROGRESS_EVERY = 0.25           # seconds between download progress events (at most 4 a second)
SPEED_WINDOW = 3.0              # seconds of samples the download speed is measured over


def version_tuple(v):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _get(url, raw=False, timeout=30, opener=None):
    req = urllib.request.Request(url, headers={"User-Agent": "NOBAD-Find", "Accept": "application/vnd.github+json"})
    with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
        if not r.geturl().startswith("https://"):
            raise IOError("the update check left HTTPS")
        data = r.read(4 * 1024 * 1024)
    return data.decode("utf-8") if raw else json.loads(data)


def read_release(rel):
    """The parts of a GitHub release this needs, checked; None when it isn't a usable NOBAD Find release."""
    if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
        return None
    m = TAG.match(str(rel.get("tag_name") or ""))
    if not m:
        return None
    ver = ".".join(m.groups())
    exe = f"NobadFind-Setup-{ver}.exe"
    assets = {a.get("name"): a for a in rel.get("assets") or () if isinstance(a, dict)}
    a, sha = assets.get(exe), assets.get(exe + ".sha256")
    if not a or not sha:
        return None
    url = str(a.get("browser_download_url") or "")
    sha_url = str(sha.get("browser_download_url") or "")
    want = f"{DOWNLOAD}find-v{ver}/{exe}"
    if url != want or sha_url != want + ".sha256":
        return None                          # only this repository's own release asset, never a link elsewhere
    size = a.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_INSTALLER:
        return None
    digest = str(a.get("digest") or "").removeprefix("sha256:").lower()
    return {"version": ver, "url": url, "sha_url": sha_url, "size": size, "digest": digest,
            "notes_url": str(rel.get("html_url") or ""), "name": exe}


class Updater:
    """state: idle | checking | uptodate | available | downloading | verifying | ready | installing | error.

    downloading: got of size bytes have arrived, bps is the speed measured over the last few seconds (0 until
    known); an update event goes out at most every PROGRESS_EVERY seconds while bytes arrive. verifying: all
    bytes are in and the size and SHA-256 are being checked (again just before the installer runs)."""

    def __init__(self, settings, data_dir=DATA_DIR, get=None, start=None, clock=time.time, current=APP_VER,
                 mono=time.monotonic):
        self.settings = settings
        self.dir = os.path.join(data_dir, "updates")
        self._get = get or _get
        self._start = start
        self._clock = clock
        self.current = current
        self.state, self.error, self.release = "idle", "", None
        self.got = 0
        self.bps = 0
        self._mono = mono
        self._samples = []                       # (monotonic time, bytes) while downloading, for the speed
        self._sent_at = None                     # when the last progress event went out
        self.checked_at = 0.0
        self._lock = threading.Lock()
        self._busy = None
        self.on_change = None                    # called after each state change (the engine pushes an event)

    def snapshot(self):
        r = self.release or {}
        return {"state": self.state, "current": self.current, "latest": r.get("version", ""),
                "size": int(r.get("size") or 0), "got": int(self.got), "bps": int(self.bps),
                "notes_url": r.get("notes_url", ""), "error": self.error, "auto": bool(self.settings.get("update_check")),
                "checked_at": int(self.checked_at)}

    def _set(self, state, error=""):
        self.state, self.error = state, error
        self._emit()

    def _emit(self):
        cb = self.on_change
        if cb is not None:
            try:
                cb(self.snapshot())
            except Exception:
                pass

    # ---------- check ----------
    def due(self):
        return bool(self.settings.get("update_check")) and self._clock() - self.checked_at >= EVERY_S \
            and self.state not in ("downloading", "verifying", "ready", "installing")

    def check(self):
        """Ask GitHub for the latest release. Never raises; the state says what came of it."""
        with self._lock:
            if self.state in ("checking", "downloading", "verifying", "installing"):
                return self.snapshot()
            self._set("checking")
        try:
            rel = read_release(self._get(LATEST))
            self.checked_at = self._clock()
            if rel is None:
                self.release = None
                self._set("uptodate")
            elif version_tuple(rel["version"]) > version_tuple(self.current):
                self.release = rel
                ready = self._installer_ready(rel)
                self._set("ready" if ready else "available")
                log(f"update: NOBAD Find {rel['version']} is available (this is {self.current})")
                notify.post("update_available", f"NOBAD Find {rel['version']} is available",
                            f"You have {self.current}. Update downloads it from GitHub, checks it and installs it.",
                            "info", action="update", key=f"update:{rel['version']}", once=True)
            else:
                self.release = rel
                self._set("uptodate")
        except Exception as e:
            self.checked_at = self._clock()
            log(f"update check failed: {type(e).__name__}", "warn")
            self._set("error", "Couldn't reach GitHub to check for updates. Try again later.")
        return self.snapshot()

    def check_in_background(self):
        if self._busy is not None and self._busy.is_alive():
            return False
        self._busy = threading.Thread(target=self.check, daemon=True, name="update-check")
        self._busy.start()
        return True

    # ---------- download and install ----------
    def _path(self, rel):
        return os.path.join(self.dir, rel["name"])

    def _installer_ready(self, rel):
        p = self._path(rel)
        return os.path.isfile(p) and os.path.getsize(p) == rel["size"] and _sha256(p) == self._want_sha(rel, cached=True)

    _sha_cache = None

    def _want_sha(self, rel, cached=False):
        if cached and self._sha_cache and self._sha_cache[0] == rel["version"]:
            return self._sha_cache[1]
        text = self._get(rel["sha_url"], raw=True)
        sha = (text.split() or [""])[0].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise IOError("the release's .sha256 file isn't a SHA-256")
        if rel["digest"] and rel["digest"] != sha:
            raise IOError("the .sha256 file and GitHub's digest disagree")
        self._sha_cache = (rel["version"], sha)
        return sha

    def _progress(self, got):
        """Bytes arrived (the download thread): the speed over the last SPEED_WINDOW seconds, and an update event
        at most every PROGRESS_EVERY seconds. The last byte moves the state on to verifying at once."""
        size = int((self.release or {}).get("size") or 0)
        self.got = got
        now = self._mono()
        if size and got >= size:
            self.bps = 0
            self._set("verifying")
            return
        if self._sent_at is not None and now - self._sent_at < PROGRESS_EVERY:
            return
        self._sent_at = now
        self._samples.append((now, got))
        while len(self._samples) > 2 and now - self._samples[1][0] >= SPEED_WINDOW:
            self._samples.pop(0)
        t0, g0 = self._samples[0]
        self.bps = int((got - g0) / (now - t0)) if now > t0 and got >= g0 else 0
        self._emit()

    def download(self, fetch=None, then_install=False):
        """The installer of the release found by check, into <data>/updates, checked. True when it's ready.
        then_install: the state stays verifying (install() comes next) instead of passing through ready."""
        rel = self.release
        if rel is None or version_tuple(rel["version"]) <= version_tuple(self.current):
            self._set("error", "There is no newer version to install.")
            return False
        try:
            self.got, self.bps, self._samples, self._sent_at = 0, 0, [], None
            self._set("downloading")
            sha = self._want_sha(rel)
            os.makedirs(self.dir, exist_ok=True)
            for f in os.listdir(self.dir):                 # older downloads go
                if f != rel["name"]:
                    try:
                        os.remove(os.path.join(self.dir, f))
                    except OSError:
                        pass
            dest = self._path(rel)

            def progress(_name, got, _size):
                self._progress(got)
            (fetch or _fetch)(rel["url"], dest, rel["size"], sha, rel["name"], progress)
            self.got, self.bps = rel["size"], 0
            log(f"update: NOBAD Find {rel['version']} downloaded and checked")
            if then_install:
                if self.state != "verifying":
                    self._set("verifying")
                return True
            self._set("ready")
            return True
        except Exception as e:
            log(f"update download failed: {type(e).__name__}: {e}", "warn")
            self.bps = 0
            self._set("error", "The update didn't download completely or didn't match its checksum. Try again.")
            return False

    def install(self):
        """Run the checked installer silently, outside NOBAD Find's job. It closes NOBAD Find, installs over it
        and starts it again. True when it started."""
        rel = self.release
        if self.state not in ("ready", "verifying") or rel is None:
            return False
        p = self._path(rel)
        try:
            if self.state != "verifying":
                self._set("verifying")
            if os.path.getsize(p) != rel["size"] or _sha256(p) != self._want_sha(rel, cached=True):
                raise IOError("the downloaded installer changed")
            self._set("installing")
            start = self._start
            if start is None:
                from .winapi import start_outside_job as start
            start([p, *SILENT, f"/LOG={os.path.join(self.dir, 'install.log')}"])
            log(f"update: installing NOBAD Find {rel['version']}")
            return True
        except Exception as e:
            log(f"update install failed to start: {type(e).__name__}", "warn")
            self._set("error", "The installer didn't start. Download it again, or install it from the website.")
            return False


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _fetch(url, dest, size, sha, name, progress):
    from .embed import _fetch_verified
    _fetch_verified(url, dest, size, sha, name, progress=progress)
