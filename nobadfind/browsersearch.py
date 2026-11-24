"""Browser results (1.2.0, browser spec §4): the rows browserdata.py read into `browser_items`, searched beside the
files.

- Only while the setting browser_data is on (search.search(browser=...), off by default): with it off nothing here
  runs, so file search is exactly what it was (tools/eval_search.py, the photo evaluation).
- A result has kind "browser" and the id -(its browser_items id): never the same as a file's id, so a list of both
  can be selected, opened and guessed by id alone. Api.open opens it by that id (`open_target`), never by a page
  address or path from the window.
- Ranking: the name channel (title and site) and the text channel (title, address, site, bookmark folder) go into
  the same reciprocal rank fusion as the files' name and text lists, with the same weights. The meaning and photo
  channels never see browser items (they have no vectors; search skips them for a browser-only question).
- The filter bar: kind "browser" shows only browser items, `browser` one kind of them, and `visited` a date range
  for History (today, yesterday, last 7 / 30 days, or picked days "YYYY-MM-DD..YYYY-MM-DD").
- Titles, addresses and user names are untrusted: FTS only through store.fts_quote, the UI draws them as plain text,
  and an address is opened only when it is plain http(s) (`web_address`).
"""
import datetime as dt
import ntpath
import re
import urllib.parse

from .display import visible
from .store import fts_quote

KINDS = ("history", "bookmark", "login", "download")
FILTER_BROWSER = {""} | set(KINDS)
VISITED = {"today", "yesterday", "week", "month"}
_RANGE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.\.(\d{4})-(\d{2})-(\d{2})$")
LABELS = {"history": "Browser history", "bookmark": "Bookmarks", "login": "Saved logins",
          "download": "Browser downloads"}
WHEN = {"history": "visited", "bookmark": "bookmarked", "download": "downloaded", "login": "last used"}
MAX_URL = 2048


def allowed_kinds(browser):
    """search(browser=...): True (every kind), a tuple of kinds (browserdata.MODE_KINDS), or falsy (off)."""
    if browser is True:
        return KINDS
    return tuple(k for k in (browser or ()) if k in KINDS)


def _range(v):
    m = _RANGE.match(v or "")
    if not m:
        return None
    try:
        a = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        b = dt.date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None
    return (a, b) if a <= b else None


def visited_ok(v):
    """The filter's `visited` value: "", a VISITED word or a range of days."""
    return isinstance(v, str) and (v == "" or v in VISITED or _range(v) is not None)


def visited_range(v, now):
    """(t0, t1, label) of a `visited` value, local days; None for "" or a value that isn't one."""
    today = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if v == "today":
        return today.timestamp(), now + 60, "visited today"
    if v == "yesterday":
        return (today - dt.timedelta(days=1)).timestamp(), today.timestamp(), "visited yesterday"
    if v == "week":
        return now - 7 * 86400, now + 60, "visited in the last 7 days"
    if v == "month":
        return now - 30 * 86400, now + 60, "visited in the last 30 days"
    r = _range(v)
    if r is None:
        return None
    a = dt.datetime(r[0].year, r[0].month, r[0].day)
    b = dt.datetime(r[1].year, r[1].month, r[1].day) + dt.timedelta(days=1)
    label = f"visited on {r[0].isoformat()}" if r[0] == r[1] else f"visited {r[0].isoformat()} to {r[1].isoformat()}"
    return a.timestamp(), b.timestamp(), label


def apply_filters(q, filters, now):
    """The filter bar's Browser choice. Applied whatever the setting says: with it off, the Browser filter finds
    nothing (and never lists files instead)."""
    if not isinstance(filters, dict) or filters.get("kind") != "browser":
        return
    k = filters.get("browser")
    q.browser = {k} if k in KINDS else set(KINDS)
    if k == "history" and q.t0 is None:              # the date range belongs to History only (spec §4)
        r = visited_range(filters.get("visited"), now) if isinstance(filters.get("visited"), str) else None
        if r:
            q.t0, q.t1, q.when = r


def file_only(q):
    """A filter only files have (a kind, an extension, a size, a folder or drive): no browser items then."""
    return bool(q.kinds or q.all_exts() or getattr(q, "secrets", False) or q.folder or q.path or q.dirs or q.place
                or q.min_size is not None or q.max_size is not None)


def _where(q, allowed):
    kinds = [k for k in KINDS if k in allowed and (not q.browser or k in q.browser)]
    if not kinds or file_only(q):
        return None, ()
    sql = f" AND b.kind IN ({','.join('?' * len(kinds))})"
    args = list(kinds)
    if q.t0 is not None:
        sql += " AND b.at BETWEEN ? AND ?"
        args += [q.t0, q.t1]
    return sql, tuple(args)


_FROM = "FROM browser_fts JOIN browser_items b ON b.id = browser_fts.rowid WHERE browser_fts MATCH ?"


def hits(store, q, allowed, limit=300):
    """(name list, text list) of browser result ids (negative), best first. Name: the words in the title or the
    site (word starts); text: the words anywhere in the item (title, address, site, folder)."""
    words = [t for t in q.terms if len(t) >= 2] + q.phrases
    where, args = _where(q, allowed)
    if not words or where is None:
        return [], []
    name_m = " AND ".join("{title host} : " + fts_quote(w) + "*" for w in words)
    text_m = " AND ".join(fts_quote(w) for w in words)
    out = []
    for m in (name_m, text_m):
        rows = store.q(f"SELECT b.id {_FROM}{where} ORDER BY bm25(browser_fts), b.visits DESC, b.at DESC LIMIT ?",
                       (m, *args, limit))
        out.append([-r[0] for r in rows])
    return out[0], out[1]


ORDER = {"": "b.at DESC", "newest": "b.at DESC", "largest": "b.at DESC", "oldest": "b.at ASC",
         "name": "b.title COLLATE NOCASE ASC"}


def listing(store, q, allowed, limit):
    """Only filters (Browser > History, last 7 days): the items, newest first unless an order was chosen."""
    where, args = _where(q, allowed)
    if where is None:
        return []
    rows = store.q(f"SELECT b.id FROM browser_items b WHERE 1=1{where} ORDER BY {ORDER.get(q.sort, ORDER[''])} "
                   "LIMIT ?", (*args, limit))
    return [-r[0] for r in rows]


def rows(store, ids):
    """{result id: (id, browser, profile, kind, title, url, host, at, visits, folder)} for negative result ids."""
    want = [-i for i in ids if isinstance(i, int) and i < 0]
    out = {}
    for i in range(0, len(want), 900):
        part = want[i:i + 900]
        for r in store.q("SELECT id, browser, profile, kind, title, url, host, at, visits, folder FROM browser_items "
                         f"WHERE id IN ({','.join('?' * len(part))})", part):
            out[-r[0]] = r
    return out


def info(row):
    """The row in search's file-info shape (id, path, name, dir, kind, size, mtime, ctime), for its sort keys."""
    return (-row[0], row[5], row[4] or row[6] or row[5], row[6], "browser", None, row[7], row[7])


def result(row, why, ago):
    """One answer row (contract `result`, kind browser). Built sentences show untrusted parts with
    display.visible; the window draws everything as plain text."""
    bid, browser, profile, kind, title, url, host, at, visits, folder = row
    source = visible(f"{browser} ({profile})" if profile else browser)
    if kind == "login":
        name = host or url
        place = f"{source} · saved login for {visible(title)}" if title else f"{source} · saved login"
    elif kind == "download":
        name = title or ntpath.basename(url)
        place = f"{source} · downloaded from {visible(host)}" if host else f"{source} · download"
    elif kind == "bookmark":
        name = title or url
        place = f"{source} · bookmarks{' / ' + visible(folder) if folder else ''}"
    else:
        name = title or url
        place = f"{source} · {visible(host)}" if host else source
    return {"id": -bid, "path": url, "name": name, "dir": place, "kind": "browser", "size": None, "mtime": at,
            "ago": ago, "why": why, "snippet": "", "weak": False,
            "browser": {"browser": browser, "profile": profile, "kind": kind, "title": title, "url": url,
                        "host": host, "at": at, "visits": int(visits or 0), "folder": folder}}


def why(row, by_name, by_text, timed, ago):
    kind = row[3]
    out = []
    if by_name:
        out.append("site matches" if kind == "login" else "title matches")
    elif by_text:
        out.append("address matches")
    if timed and row[7]:
        out.append(f"{WHEN.get(kind, 'visited')} {ago}")
    return out


# characters kept as they are in an address handed to the browser; everything else (spaces, quotes, commas,
# backslashes, controls) is percent-encoded, so explorer.exe never reads part of it as one of its switches
_SAFE = "-._~:/?#[]@!$&'()*+;=%"


def web_address(url):
    """url when it is a plain http(s) address (percent-encoding what isn't plainly safe), else None."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        return None
    try:
        u = urllib.parse.urlsplit(url)
        host = u.hostname
    except ValueError:
        return None
    if u.scheme.lower() not in ("http", "https") or not host:
        return None
    return urllib.parse.quote(url, safe=_SAFE)


_LOCAL_ABS = re.compile(r"^[A-Za-z]:\\")


def download_path(path):
    """A download's file path when it is a plain local path (never \\\\server\\share or \\\\?\\: those would make
    Windows reach out or skip its checks), normalized; else None."""
    if not isinstance(path, str) or not path or len(path) > 1024 or "\x00" in path:
        return None
    p = ntpath.normpath(path.replace("/", "\\"))
    return p if _LOCAL_ABS.match(p) else None
