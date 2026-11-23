"""Browser data, the reader (1.2.0, opt-in; browser spec 2026-11-22 §2-§3).

Setting browser_data (const.DEFAULTS, OFF by default): "history" reads the browsers' history, bookmarks and
downloads; "history_logins" also saved logins' site and user name. Chrome, Edge, Brave, Vivaldi, Opera and Firefox,
each profile of the signed-in user its own source (`profiles`: only this user's LOCALAPPDATA / APPDATA).

What is read, and what never is:
- History: Chromium `History` (urls: url, title, visit_count, last_visit_time), Firefox `places.sqlite`
  (moz_places). Bookmarks: Chromium `Bookmarks` (JSON), Firefox moz_bookmarks (title, url, folder). Downloads:
  Chromium `History` (downloads: target_path, tab_url, end_time).
- Saved logins: Chromium `Login Data` (logins: origin_url, username_value only), Firefox `logins.json` (hostname
  only: its user names are encrypted and are not decrypted). Password values are never selected, decrypted,
  stored, logged or shown; `Login Data` is read in memory (`_memory_db`), not copied to disk.
- Never page contents, cookies or session data. Only http(s) addresses are kept (no javascript: bookmarklets).

How it is read safely:
- Never kill or close a browser, and never ask it to close: nothing here ends or signals a process.
- Copy, don't lock (`snapshot`): the file and its -wal and -shm are opened with CreateFileW(GENERIC_READ,
  FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE) and copied into <data>\\tmp\\browser-<random> (ACL: this
  user only); the copy's WAL is folded into it, then it is opened with sqlite3 `?mode=ro&immutable=1`, read, closed
  and deleted at once, also on error (`wipe_tmp` clears what a crash left, at engine start and when turned off).
- A file the browser holds exclusively (sharing or lock violation) raises Locked; `Schedule` retries at 1, 5 and 30
  minutes, then gives up with a note until the file changes.
- Only the expected tables and columns are read: an unknown layout is skipped with a note (UnknownSchema), never
  guessed. Everything read is untrusted (the UI: esc(); FTS: store.fts_quote).
- `read_profile` runs in a text-reader worker process (indexer.Indexer._read_browsers: the WORKERS job, low
  priority), never in the engine; the rows go into the encrypted index (store.browser_items).
- Freshness: a profile is read again when its files' time changes, at most every FRESH_S per profile.
"""
import configparser
import contextlib
import ctypes
import json
import ntpath
import os
import secrets
import shutil
import sqlite3
import urllib.parse
import urllib.request

from .log import log

GENERIC_READ = 0x80000000
SHARE_ALL = 0x7                    # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE: the browser keeps working
OPEN_EXISTING = 3
LOCK_ERRORS = (32, 33)             # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
MISSING_ERRORS = (2, 3)            # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND
RETRY_S = (60, 300, 1800)          # a locked file: tried again after 1, 5 and 30 minutes, then given up until it changes
FRESH_S = 600                      # a profile is read at most every 10 minutes
TMP_PREFIX = "browser-"
MAX_ROWS = 20000                   # per kind and profile, newest first
MAX_FILE = 64 * 1024 * 1024        # Bookmarks / logins.json / Login Data read in memory: larger ones are skipped
MAX_TITLE, MAX_URL = 500, 2048
KINDS = ("history", "bookmark", "download", "login")
MODE_KINDS = {"off": (), "history": ("history", "bookmark", "download"), "history_logins": KINDS}

# (browser, environment folder, the user-data folder in it); Opera's folder is its one profile
CHROMIUM = (("Chrome", "LOCALAPPDATA", ("Google", "Chrome", "User Data")),
            ("Edge", "LOCALAPPDATA", ("Microsoft", "Edge", "User Data")),
            ("Brave", "LOCALAPPDATA", ("BraveSoftware", "Brave-Browser", "User Data")),
            ("Vivaldi", "LOCALAPPDATA", ("Vivaldi", "User Data")),
            ("Opera", "APPDATA", ("Opera Software", "Opera Stable")))
FIREFOX = ("Firefox", "APPDATA", ("Mozilla", "Firefox"))
CHROMIUM_FILES = ("History", "Bookmarks", "Login Data", "Login Data For Account")
FIREFOX_FILES = ("places.sqlite", "logins.json")
FIREFOX_ROOTS = {"menu": "Bookmarks menu", "toolbar": "Bookmarks toolbar", "unfiled": "Other bookmarks",
                 "mobile": "Mobile bookmarks"}


class Locked(OSError):
    """The browser holds the file so that it can't be opened even with full sharing: try again later."""


class UnknownSchema(Exception):
    """The file's tables or columns aren't the ones this version knows: skipped, not guessed."""


def allowed(mode, kind):
    """Whether the setting value mode lets rows of kind into the index."""
    return kind in MODE_KINDS.get(mode, ())


# ---------- the profiles ----------
def _chromium_names(root):
    """{profile folder: the name the user gave it} from Local State (missing or odd: {})."""
    try:
        with open(os.path.join(root, "Local State"), "rb") as f:
            data = json.loads(f.read(MAX_FILE).decode("utf-8", "replace"))
        cache = data["profile"]["info_cache"]
        return {k: str(v.get("name") or k)[:80] for k, v in cache.items() if isinstance(v, dict)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _firefox_names(base):
    """{normcased profile folder: its name} from profiles.ini (relative paths only)."""
    out = {}
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cp.read(os.path.join(base, "profiles.ini"), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeError):
        return out
    for sec in cp.sections():
        path, name = cp.get(sec, "Path", fallback=""), cp.get(sec, "Name", fallback="")
        if path and name and cp.get(sec, "IsRelative", fallback="1") == "1":
            out[os.path.normcase(os.path.normpath(os.path.join(base, path)))] = name[:80]
    return out


def _mtime(folder, files):
    t = 0.0
    for f in files:
        for tail in ("", "-wal"):
            try:
                t = max(t, os.stat(os.path.join(folder, f + tail)).st_mtime)
            except OSError:
                pass
    return t


def profiles(env=None):
    """Every browser profile of this user: [{browser, profile, engine, dir, mtime}]. env: the environment to take
    LOCALAPPDATA / APPDATA from (tests give a made-up one); no folder known, no profiles."""
    env = os.environ if env is None else env
    found = []
    for browser, var, parts in CHROMIUM:
        base = env.get(var)
        root = os.path.join(base, *parts) if base else ""
        if not root or not os.path.isdir(root):
            continue
        if browser == "Opera":
            dirs = [(root, "Default")]
        else:
            names = _chromium_names(root)
            try:
                subs = sorted(os.listdir(root))
            except OSError:
                subs = []
            dirs = [(os.path.join(root, d), names.get(d, d)) for d in subs
                    if (d == "Default" or d.startswith("Profile ")) and os.path.isdir(os.path.join(root, d))]
        for d, label in dirs:
            if any(os.path.exists(os.path.join(d, f)) for f in CHROMIUM_FILES):
                found.append({"browser": browser, "profile": label, "engine": "chromium", "dir": d,
                              "mtime": _mtime(d, CHROMIUM_FILES)})
    browser, var, parts = FIREFOX
    base = os.path.join(env[var], *parts) if env.get(var) else ""
    if base and os.path.isdir(os.path.join(base, "Profiles")):
        names = _firefox_names(base)
        root = os.path.join(base, "Profiles")
        try:
            subs = sorted(os.listdir(root))
        except OSError:
            subs = []
        for sub in subs:
            d = os.path.join(root, sub)
            if os.path.isdir(d) and any(os.path.exists(os.path.join(d, f)) for f in FIREFOX_FILES):
                label = names.get(os.path.normcase(os.path.normpath(d))) or sub.split(".", 1)[-1]
                found.append({"browser": browser, "profile": label, "engine": "firefox", "dir": d,
                              "mtime": _mtime(d, FIREFOX_FILES)})
    seen = {}
    for p in found:                    # two profiles with one name: the folder tells them apart
        k = (p["browser"], p["profile"])
        seen[k] = seen.get(k, 0) + 1
    for p in found:
        if seen[(p["browser"], p["profile"])] > 1:
            p["profile"] = f"{p['profile']} ({os.path.basename(p['dir'])})"
    return found


# ---------- copy, don't lock ----------
_k32 = []


def _kernel32():
    if not _k32:
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = w.HANDLE
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CreateDirectoryW.restype = w.BOOL
        k.CreateDirectoryW.argtypes = [w.LPCWSTR, ctypes.c_void_p]
        k.LocalFree.argtypes = [ctypes.c_void_p]
        _k32.append(k)
    return _k32[0]


def _open_shared(path):
    """path for reading, sharing read, write and delete with whoever holds it (the browser keeps writing it)."""
    if os.name != "nt":
        return open(path, "rb")
    import msvcrt
    k = _kernel32()
    h = k.CreateFileW(path, GENERIC_READ, SHARE_ALL, None, OPEN_EXISTING, 0x80, None)
    if h is None or h == ctypes.c_void_p(-1).value:
        err = ctypes.get_last_error()
        if err in LOCK_ERRORS:
            raise Locked(err, "in use by the browser")
        if err in MISSING_ERRORS:
            raise FileNotFoundError(err, "not there")
        raise OSError(err, "can't be opened")
    try:
        fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError:
        k.CloseHandle(h)
        raise
    return os.fdopen(fd, "rb")


def copy_shared(src, dst):
    with _open_shared(src) as f, open(dst, "xb") as out:
        shutil.copyfileobj(f, out, 1024 * 1024)


def _user_sid():
    from .rpc.server import user_sid
    return user_sid()


def _private_dir(root):
    """A new <root>\\browser-<random> folder only this user can open (inherited by what's copied into it)."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, TMP_PREFIX + secrets.token_hex(8))
    if os.name == "nt":
        try:
            k = _kernel32()
            adv = ctypes.WinDLL("advapi32", use_last_error=True)
            sd = ctypes.c_void_p()
            if adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    f"D:P(A;OICI;FA;;;{_user_sid()})", 1, ctypes.byref(sd), None):
                class SA(ctypes.Structure):
                    _fields_ = [("n", ctypes.c_uint32), ("sd", ctypes.c_void_p), ("inherit", ctypes.c_int)]
                sa = SA(ctypes.sizeof(SA), sd, 0)
                try:
                    if k.CreateDirectoryW(path, ctypes.byref(sa)):
                        return path
                finally:
                    k.LocalFree(sd)
        except (OSError, AttributeError):
            pass
    os.mkdir(path)                  # inside the data folder, which is this user's already
    return path


def wipe_tmp(data_dir):
    """Delete every browser-* copy left in <data>\\tmp (a crash mid-read; engine start, and turning it off)."""
    root = os.path.join(data_dir, "tmp")
    try:
        names = os.listdir(root)
    except OSError:
        return
    for n in names:
        if n.startswith(TMP_PREFIX):
            shutil.rmtree(os.path.join(root, n), ignore_errors=True)


def _uri(path):
    return "file:" + urllib.request.pathname2url(path) + "?mode=ro&immutable=1"


@contextlib.contextmanager
def snapshot(db_path, data_dir):
    """A read-only connection to a copy of the SQLite database db_path (with its -wal and -shm), made in
    <data_dir>\\tmp\\browser-<random> and deleted when the block ends, also on error. Raises Locked when the browser
    holds a file so it can't be read, FileNotFoundError when there is none."""
    folder = _private_dir(os.path.join(data_dir, "tmp"))
    conn = None
    try:
        dst = os.path.join(folder, os.path.basename(db_path))
        copy_shared(db_path, dst)
        for tail in ("-wal", "-shm"):
            if os.path.exists(db_path + tail):
                try:
                    copy_shared(db_path + tail, dst + tail)
                except FileNotFoundError:
                    pass                    # checkpointed away a moment ago: the main file has it
        if os.path.exists(dst + "-wal") and os.path.getsize(dst + "-wal") > 0:
            # immutable=1 never looks at a -wal: fold the copied one into the copy first (it is ours alone)
            c = sqlite3.connect(dst)
            try:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                c.close()
        conn = sqlite3.connect(_uri(dst), uri=True)
        yield conn
    finally:
        if conn is not None:
            conn.close()
        shutil.rmtree(folder, ignore_errors=True)


def _read_small(path):
    with _open_shared(path) as f:
        data = f.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise UnknownSchema("too big")
    return data


@contextlib.contextmanager
def _memory_db(path, data_dir):
    """A read-only connection to the database path loaded into memory (Login Data: its password_value blobs are
    never written to disk by NOBAD Find, not even as a temporary copy). Only the main file: a -wal the browser hasn't
    folded in yet is not read (Chromium keeps Login Data out of WAL mode; logins saved since its last checkpoint
    come at the next read after it). data_dir: unused, the same call as `snapshot`."""
    data = bytearray(_read_small(path))
    if data[:16] == b"SQLite format 3\x00" and len(data) >= 20:
        data[18] = data[19] = 1         # a WAL-mode header read as a plain one (memory has no -wal)
    c = sqlite3.connect(":memory:")
    try:
        c.deserialize(bytes(data))
        del data
        c.execute("PRAGMA query_only=1")
        yield c
    finally:
        c.close()


# ---------- what is read ----------
def _web(url):
    """url when it is an http(s) address (and the host), else None."""
    if not isinstance(url, str) or len(url) > MAX_URL:
        return None
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if u.scheme.lower() not in ("http", "https"):
        return None
    try:
        host = (u.hostname or "")[:255]
    except ValueError:
        return None
    return (url, host) if host else None


def _text(t):
    return t[:MAX_TITLE] if isinstance(t, str) else ""


def _webkit(t):
    """Chromium time (microseconds since 1601) as unix seconds; 0 or odd: None."""
    try:
        t = int(t)
    except (TypeError, ValueError):
        return None
    return t / 1e6 - 11644473600 if t > 0 else None


def _unix_us(t):
    try:
        t = int(t)
    except (TypeError, ValueError):
        return None
    return t / 1e6 if t > 0 else None


def _columns(c, table):
    return {r[1] for r in c.execute(f"PRAGMA table_info({table})")}    # table: a name from this file only


def _need(c, table, cols):
    have = _columns(c, table)
    if not set(cols) <= have:
        raise UnknownSchema(table)
    return have


def _chromium_history(c, notes, what):
    have = _need(c, "urls", ("url", "title", "visit_count", "last_visit_time"))
    where = " WHERE hidden = 0" if "hidden" in have else ""
    hist = []
    for url, title, visits, at in c.execute(
            f"SELECT url, title, visit_count, last_visit_time FROM urls{where} ORDER BY last_visit_time DESC "
            "LIMIT ?", (MAX_ROWS,)):
        w = _web(url)
        if w:
            hist.append(("history", _text(title), w[0], w[1], _webkit(at), int(visits or 0), ""))
    out = {"history": hist}
    try:
        _need(c, "downloads", ("target_path", "tab_url", "end_time"))
    except UnknownSchema:
        notes.append(f"{what}: its downloads list has a layout this version doesn't know, so it was not read")
        return out
    downs = []
    for path, tab, at in c.execute("SELECT target_path, tab_url, end_time FROM downloads ORDER BY end_time DESC "
                                   "LIMIT ?", (MAX_ROWS,)):
        if not isinstance(path, str) or not path or len(path) > MAX_URL:
            continue
        w = _web(tab)
        downs.append(("download", _text(ntpath.basename(path)), path, w[1] if w else "", _webkit(at), 0, ""))
    out["download"] = downs
    return out


def _chromium_bookmarks(raw):
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        roots = data["roots"]
        if not isinstance(roots, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise UnknownSchema("Bookmarks") from None
    out = []

    def walk(node, folder, depth):
        if not isinstance(node, dict) or depth > 40 or len(out) >= MAX_ROWS:
            return
        if node.get("type") == "url":
            w = _web(node.get("url"))
            if w:
                out.append(("bookmark", _text(node.get("name")), w[0], w[1], _webkit(node.get("date_added")), 0,
                            folder[:MAX_TITLE]))
            return
        name = _text(node.get("name"))
        sub = f"{folder}/{name}" if folder and name else (name or folder)
        for child in node.get("children") or ():
            walk(child, sub, depth + 1)
    for key in ("bookmark_bar", "other", "synced"):
        if key in roots:
            walk(roots[key], "", 0)
    return {"bookmark": out}


def _chromium_logins(c):
    have = _need(c, "logins", ("origin_url", "username_value"))
    at = "date_last_used" if "date_last_used" in have else ("date_created" if "date_created" in have else "0")
    out = []
    # only these columns: the password column is never named in a query
    for origin, user, t in c.execute(f"SELECT origin_url, username_value, {at} FROM logins LIMIT ?", (MAX_ROWS,)):
        w = _web(origin)
        if w:
            out.append(("login", _text(user), w[0], w[1], _webkit(t), 0, ""))
    return out


def _firefox_places(c, notes, what):
    _need(c, "moz_places", ("url", "title", "visit_count", "last_visit_date", "hidden"))
    hist = []
    for url, title, visits, at in c.execute(
            "SELECT url, title, visit_count, last_visit_date FROM moz_places WHERE hidden = 0 AND last_visit_date "
            "IS NOT NULL ORDER BY last_visit_date DESC LIMIT ?", (MAX_ROWS,)):
        w = _web(url)
        if w:
            hist.append(("history", _text(title), w[0], w[1], _unix_us(at), int(visits or 0), ""))
    out = {"history": hist}
    try:
        _need(c, "moz_bookmarks", ("type", "fk", "parent", "title", "dateAdded"))
    except UnknownSchema:
        notes.append(f"{what}: its bookmarks have a layout this version doesn't know, so they were not read")
        return out
    folders = {i: (p, t) for i, p, t in c.execute("SELECT id, parent, title FROM moz_bookmarks WHERE type = 2")}

    def path(i):
        parts = []
        for _ in range(40):
            if i not in folders or folders[i][0] not in folders:
                break                      # not a folder, or the root itself (not one the user sees)
            parent, title = folders[i]
            top = folders[parent][0] not in folders          # right under the root: menu, toolbar...
            parts.append(FIREFOX_ROOTS.get(title, _text(title)) if top else _text(title))
            i = parent
        return "/".join(reversed([t for t in parts if t]))
    marks = []
    for parent, btitle, at, url, ptitle in c.execute(
            "SELECT b.parent, b.title, b.dateAdded, p.url, p.title FROM moz_bookmarks b JOIN moz_places p "
            "ON p.id = b.fk WHERE b.type = 1 LIMIT ?", (MAX_ROWS,)):
        w = _web(url)
        if w:
            marks.append(("bookmark", _text(btitle or ptitle), w[0], w[1], _unix_us(at), 0, path(parent)[:MAX_TITLE]))
    out["bookmark"] = marks
    return out


def _firefox_logins(raw):
    """Site only: Firefox encrypts the user names too, and nothing here decrypts."""
    try:
        logins = json.loads(raw.decode("utf-8", "replace"))["logins"]
        if not isinstance(logins, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise UnknownSchema("logins.json") from None
    out = []
    for e in logins[:MAX_ROWS]:
        if isinstance(e, dict):
            w = _web(e.get("hostname"))
            if w:
                t = e.get("timeLastUsed")
                out.append(("login", "", w[0], w[1], t / 1000 if isinstance(t, (int, float)) and t > 0 else None,
                            0, ""))
    return out


def _sources(job):
    """[(file names, the kinds they give, reader(paths, notes) -> {kind: rows})] for the job's profile."""
    d, data, what = job["dir"], job["data_dir"], f"{job['browser']} ({job['profile']})"

    def one(name, fn):
        def run(notes):
            with snapshot(os.path.join(d, name), data) as c:
                return fn(c, notes, f"{what} {name}")
        return run

    def logins_chromium(notes):
        rows, any_file = [], False
        for name in ("Login Data", "Login Data For Account"):
            try:
                with _memory_db(os.path.join(d, name), data) as c:
                    rows += _chromium_logins(c)
                any_file = True
            except FileNotFoundError:
                pass
        if not any_file:
            raise FileNotFoundError("Login Data")
        return {"login": rows}
    if job["engine"] == "chromium":
        src = [("History", ("history", "download"), one("History", _chromium_history)),
               ("Bookmarks", ("bookmark",),
                lambda notes: _chromium_bookmarks(_read_small(os.path.join(d, "Bookmarks"))))]
        if job.get("logins"):
            src.append(("Login Data", ("login",), logins_chromium))
    else:
        src = [("places.sqlite", ("history", "bookmark"), one("places.sqlite", _firefox_places))]
        if job.get("logins"):
            src.append(("logins.json", ("login",),
                        lambda notes: {"login": _firefox_logins(_read_small(os.path.join(d, "logins.json")))}))
    return src, what


def _read_sources(job):
    src, what = _sources(job)
    out = {"browser": job["browser"], "profile": job["profile"], "kinds": {}, "notes": [], "locked": []}
    for name, kinds, run in src:
        try:
            out["kinds"].update(run(out["notes"]))
        except FileNotFoundError:
            out["kinds"].update({k: [] for k in kinds})       # the file is gone: so are its rows
        except Locked:
            out["locked"].append(name)                        # what it had stays; Schedule tries again
        except UnknownSchema:
            out["notes"].append(f"{what}: {name} has a layout this version doesn't know, so it was not read")
        except (sqlite3.Error, OSError, ValueError, MemoryError) as e:
            out["notes"].append(f"{what}: {name} couldn't be read ({type(e).__name__})")
    return out


def read_profile(job):
    """One profile's items, in a worker process: {browser, profile, kinds: {kind: [(kind, title, url, host, at,
    visits, folder)]}, notes, locked: [file names in use]}. job: a `profiles` entry plus data_dir and logins (the
    setting is history_logins). A kind that's missing wasn't read (locked, unknown layout): keep what it had."""
    return _read_sources(job)


# ---------- when to read ----------
class Schedule:
    """When each profile is read (in the engine; the reads themselves in a worker): once at first, then when its
    files' time changed and FRESH_S has passed since the last read; a locked file after RETRY_S, then given up
    with a note until the files change. state(): what Settings can show (last read, counts, last error)."""

    def __init__(self):
        self._s = {}

    @staticmethod
    def _key(p):
        return (p["browser"], p["profile"])

    def _get(self, p):
        return self._s.setdefault(self._key(p), {"mtime": None, "read_at": None, "fails": 0, "next_at": None,
                                                 "error": "", "counts": {}})

    def due(self, profs, now):
        out = []
        for p in profs:
            st = self._s.get(self._key(p))
            if st is None:
                out.append(p)
            elif st["next_at"] is not None:
                if now >= st["next_at"]:
                    out.append(p)
            elif p.get("mtime") != st["mtime"] and (st["read_at"] is None or now - st["read_at"] >= FRESH_S):
                out.append(p)
        return out

    def done(self, p, now, locked=False, counts=None, error=""):
        st = self._get(p)
        if locked:
            st["fails"] += 1
            if st["fails"] <= len(RETRY_S):
                wait = RETRY_S[st["fails"] - 1]
                st["next_at"] = now + wait
                st["error"] = f"in use by the browser; trying again in {wait // 60} min"
            else:
                st.update(next_at=None, fails=0, mtime=p.get("mtime"),
                          error="in use by the browser; tried 4 times, tries again when it changes")
                log(f"browser data: {p['browser']} in use, given up until it changes", "warn")
            return
        st.update(mtime=p.get("mtime"), read_at=now, fails=0, next_at=None, error=error, counts=dict(counts or {}))

    def next_at(self, p):
        return self._get(p)["next_at"]

    def state(self, p):
        return dict(self._get(p))

    def forget(self, keep):
        for k in [k for k in self._s if k not in keep]:
            del self._s[k]
