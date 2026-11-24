"""1.2.0, browser spec §4: browser results (kind browser), the Browser filter with its dates, the "Settings & apps"
filter, the query words that ask for browser kinds, and how a browser result is opened (only by its result id).

Everything here is synthetic: rows are put straight into a throwaway index; no real browser profile is read."""
import datetime as dt
import json
import os
import time

import pytest

from nobadfind import api as api_mod, browsersearch, launcher, search, settings, winapi
from nobadfind.query import parse
from nobadfind.rpc import handlers, protocol
from nobadfind.store import Store

DAY = 86400


def _midnight(now):
    d = dt.datetime.fromtimestamp(now)
    return dt.datetime(d.year, d.month, d.day).timestamp()


def _last_week(now):
    """A moment inside query.parse's "last week" (Monday to Monday before this week)."""
    today = dt.datetime.fromtimestamp(_midnight(now))
    start = today - dt.timedelta(days=today.weekday() + 7)
    return (start + dt.timedelta(days=3, hours=12)).timestamp()


def _store(tmp_path, now):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:\\p\\github notes.txt", "github notes.txt", "C:\\p", ".txt", "text", 10, now - DAY, now - DAY, 1),
                    ("C:\\p\\bluetooth.txt", "bluetooth.txt", "C:\\p", ".txt", "text", 10, now - DAY, now - DAY, 1),
                    ("C:\\p\\beach.jpg", "beach.jpg", "C:\\p", ".jpg", "image", 50000, now - DAY, now - DAY, 1),
                    ("C:\\p\\history report.txt", "history report.txt", "C:\\p", ".txt", "text", 10,
                     _last_week(now), _last_week(now), 1)])
    s.put_browser_items("Edge", "Work", "history", [
        ("history", "GitHub: pull requests", "https://github.com/pulls", "github.com", _last_week(now), 9, ""),
        ("history", "GitHub settings", "https://github.com/settings", "github.com", now - 30 * DAY, 2, ""),
        ("history", "Beach weather", "https://weather.example/beach", "weather.example", now - 3600, 1, ""),
    ])
    s.put_browser_items("Edge", "Work", "bookmark", [
        ("bookmark", "GitHub docs", "https://docs.github.com/", "docs.github.com", _last_week(now), 0, "Work/Dev"),
    ])
    s.put_browser_items("Edge", "Work", "login", [
        ("login", "alice", "https://github.com/login", "github.com", now - 5 * DAY, 0, ""),
    ])
    s.put_browser_items("Edge", "Work", "download", [
        ("download", "setup.zip", str(tmp_path / "dl" / "setup.zip"), "github.com", now - 2 * DAY, 0, ""),
    ])
    return s


class Ix:
    embedder = photo_text = pindex = None
    drive_list = []

    def roots(self, d=None):
        return []


def _api(tmp_path, mode="history_logins", now=None):
    now = now or time.time()
    s = _store(tmp_path, now)
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"browser_data": mode})
    a = api_mod.Api(s, st, Ix(), None)
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: ran.append(argv))
    L.apps = []
    a._launcher = L
    return a, s, ran


def _kinds(r):
    return [(x["kind"], (x.get("browser") or {}).get("kind")) for x in r["results"]]


# ---------- "Settings & apps" ----------
def test_settings_and_apps_shows_only_launcher_actions(tmp_path):
    a, s, _ran = _api(tmp_path)
    try:
        r = a.search("bluetooth", {"kind": "launcher"})
        assert r["results"] == []                                    # bluetooth.txt is a file: not here
        assert r["actions"] and r["actions"][0]["id"] == "set:bluetooth"
        assert {x["kind"] for x in r["actions"]} <= {"setting", "tool", "app"}
        # without the filter, the file is found and the page offered beside it
        r = a.search("bluetooth")
        assert [x["name"] for x in r["results"]] == ["bluetooth.txt"]
        # a filter-only question lists no files either
        assert a.search("", {"kind": "launcher"})["results"] == []
    finally:
        s.close()


def test_settings_and_apps_goes_through_the_pipe(tmp_path):
    a, s, _ran = _api(tmp_path)
    m = handlers.methods(a)
    try:
        r = protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "search",
                                             "params": {"text": "display", "filters": {"kind": "launcher"}}}), m)
        assert r["result"]["results"] == [] and r["result"]["actions"][0]["id"] == "set:display"
    finally:
        s.close()


# ---------- the Browser filter and its dates ----------
def test_history_last_week_shows_only_history_visited_then(tmp_path):
    now = time.time()
    a, s, _ran = _api(tmp_path, now=now)
    try:
        r = a.search("history from last week")
        assert _kinds(r) == [("browser", "history")]
        assert r["results"][0]["name"] == "GitHub: pull requests"
        assert any("visited" in w for w in r["results"][0]["why"])
        # the filter bar: Browser > History, visited in the last 7 days / 30 days
        r = a.search("", {"kind": "browser", "browser": "history", "visited": "today"})
        assert [x["name"] for x in r["results"]] == ["Beach weather"]
        r = a.search("", {"kind": "browser", "browser": "history", "visited": "month"})
        assert {x["name"] for x in r["results"]} == {"Beach weather", "GitHub: pull requests"}
        # picked dates: the days themselves, both included
        day = dt.date.fromtimestamp(_last_week(now)).isoformat()
        r = a.search("", {"kind": "browser", "browser": "history", "visited": f"{day}..{day}"})
        assert [x["name"] for x in r["results"]] == ["GitHub: pull requests"]
        # words and the filter together; no files ever come with the Browser filter
        r = a.search("github", {"kind": "browser", "browser": "history"})
        assert {x["name"] for x in r["results"]} == {"GitHub: pull requests", "GitHub settings"}
        r = a.search("github", {"kind": "browser"})
        assert {k for _k, k in _kinds(r)} == {"history", "bookmark", "login", "download"}
        assert all(x["kind"] == "browser" for x in r["results"])
    finally:
        s.close()


def test_the_date_range_applies_only_to_history(tmp_path):
    a, s, _ran = _api(tmp_path)
    try:
        r = a.search("", {"kind": "browser", "browser": "bookmark", "visited": "today"})
        assert [x["name"] for x in r["results"]] == ["GitHub docs"]          # bookmarks: no date range
    finally:
        s.close()


def test_without_the_setting_the_browser_filter_finds_nothing(tmp_path):
    a, s, _ran = _api(tmp_path, mode="off")
    try:
        assert a.search("", {"kind": "browser"})["results"] == []
        assert a.search("github", {"kind": "browser", "browser": "history"})["results"] == []
        r = a.search("github")
        assert [x["name"] for x in r["results"]] == ["github notes.txt"]      # files only
    finally:
        s.close()


def test_logins_only_while_logins_are_read(tmp_path):
    a, s, _ran = _api(tmp_path, mode="history")
    try:
        assert a.search("", {"kind": "browser", "browser": "login"})["results"] == []
        assert "login" not in {k for _k, k in _kinds(a.search("github", {"kind": "browser"}))}
    finally:
        s.close()


def test_a_browser_result_carries_browser_profile_kind_and_date(tmp_path):
    now = time.time()
    a, s, _ran = _api(tmp_path, now=now)
    try:
        r = a.search("", {"kind": "browser", "browser": "login"})["results"][0]
        assert r["id"] < 0 and r["kind"] == "browser"
        assert r["name"] == "github.com" and "alice" in r["dir"] and "Edge" in r["dir"]
        b = r["browser"]
        assert b["browser"] == "Edge" and b["profile"] == "Work" and b["kind"] == "login"
        assert b["host"] == "github.com" and abs(b["at"] - (now - 5 * DAY)) < 1
        assert "password" not in json.dumps(r).lower()                 # only the site and the user name
    finally:
        s.close()


def test_the_pipe_takes_only_the_listed_browser_filter_values(tmp_path):
    a, s, _ran = _api(tmp_path)
    m = handlers.methods(a)

    def call(filters):
        return protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "search",
                                                "params": {"text": "", "filters": filters}}), m)
    try:
        for good in ({"kind": "browser", "browser": "download"}, {"kind": "browser", "browser": "history",
                                                                  "visited": "2026-11-01..2026-11-20"}):
            assert "result" in call(good), good
        for bad in ({"browser": "cookies"}, {"visited": "decade"}, {"visited": "2026-11-01"},
                    {"visited": "2026-13-01..2026-11-20"}, {"visited": "x" * 30}):
            assert call(bad)["error"]["code"] == protocol.INVALID_PARAMS, bad
    finally:
        s.close()


# ---------- opening: only by the result id, through fixed rules ----------
def test_a_login_opens_the_browsers_password_manager_through_the_launcher(tmp_path, monkeypatch):
    a, s, ran = _api(tmp_path)
    exe = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    monkeypatch.setattr(launcher, "_browser_exe", lambda prog: exe if prog == "msedge.exe" else None)
    try:
        r = a.search("", {"kind": "browser", "browser": "login"})["results"][0]
        assert a.open(r["id"])["ok"] is True
        assert ran == [[exe, "edge://password-manager"]]
        # the launcher's own table: a page or a program never comes from the window
        assert a.run_action("pw:edge")["ok"] is True and ran[-1] == [exe, "edge://password-manager"]
        for bad in ("pw:evil", "pw:", "pw:edge://settings", "pw:" + "x" * 300):
            assert launcher.Launcher(str(tmp_path), run=lambda *x, **k: None).run(bad)["ok"] is False
        assert launcher.PASSWORD_PAGES["Chrome"][1] == "chrome://password-manager/passwords"
        assert launcher.PASSWORD_PAGES["Firefox"][1] == "about:logins"
    finally:
        s.close()


def test_the_browser_program_must_be_its_own_installed_exe(tmp_path, monkeypatch):
    pf = str(tmp_path / "Program Files")
    good = os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe")
    os.makedirs(os.path.dirname(good))
    open(good, "wb").close()
    monkeypatch.setenv("ProgramFiles", pf)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    paths = {"chrome.exe": good, "msedge.exe": os.path.join(str(tmp_path), "elsewhere", "msedge.exe"),
             "firefox.exe": "\\\\server\\share\\firefox.exe", "brave.exe": os.path.join(pf, "Brave", "evil.exe")}
    monkeypatch.setattr(launcher, "_app_path", lambda prog: paths.get(prog))
    assert launcher._browser_exe("chrome.exe") == good
    assert launcher._browser_exe("msedge.exe") is None                  # not inside Program Files
    assert launcher._browser_exe("firefox.exe") is None                 # a network path is never looked up
    assert launcher._browser_exe("brave.exe") is None                   # not the browser's own program name
    assert launcher._browser_exe("vivaldi.exe") is None                 # not installed


def test_history_and_bookmarks_open_their_web_address_in_the_default_browser(tmp_path, monkeypatch):
    a, s, ran = _api(tmp_path)
    opened = []
    monkeypatch.setattr(winapi, "open_outside_job", lambda p: opened.append(p))
    try:
        r = a.search("github", {"kind": "browser", "browser": "history"})["results"]
        pulls = next(x for x in r if x["name"] == "GitHub: pull requests")
        assert a.open(pulls["id"])["ok"] is True and opened == ["https://github.com/pulls"]
        # an address that isn't plain http(s) (put there by anything) is never opened
        bid = s.one("SELECT id FROM browser_items WHERE kind = 'bookmark'")
        with s.wlock:
            s.db.execute("UPDATE browser_items SET url = ? WHERE id = ?", ("file:///C:/Windows/notepad.exe", bid))
            s.db.commit()
        assert a.open(-bid)["ok"] is False and len(opened) == 1
        # commas and quotes can't become explorer.exe switches
        assert browsersearch.web_address('https://x.example/a,/root,"C:\\"') == \
            "https://x.example/a%2C/root%2C%22C:%5C%22"
        assert a.open(-999999)["ok"] is False and ran == []
    finally:
        s.close()


def test_a_download_opens_its_file_or_else_its_folder(tmp_path, monkeypatch):
    a, s, _ran = _api(tmp_path)
    opened, folders = [], []
    monkeypatch.setattr(winapi, "open_outside_job", lambda p: opened.append(p))
    monkeypatch.setattr(api_mod, "open_folder", lambda p: folders.append(p) or True)
    try:
        r = a.search("", {"kind": "browser", "browser": "download"})["results"][0]
        assert r["path"].endswith("setup.zip")
        assert a.open(r["id"])["ok"] is False                           # neither the file nor its folder is there
        os.makedirs(tmp_path / "dl")
        assert a.open(r["id"])["ok"] is True and folders == [str(tmp_path / "dl")]
        (tmp_path / "dl" / "setup.zip").write_bytes(b"x")
        assert a.open(r["id"])["ok"] is True and opened == [str(tmp_path / "dl" / "setup.zip")]
        bid = -r["id"]
        with s.wlock:
            s.db.execute("UPDATE browser_items SET url = ? WHERE id = ?", ("\\\\server\\share\\setup.zip", bid))
            s.db.commit()
        assert a.open(r["id"])["ok"] is False and len(opened) == 1 and len(folders) == 1   # never a network path
    finally:
        s.close()


def test_a_download_on_a_mapped_network_drive_is_never_looked_up(tmp_path, monkeypatch):
    """Final review: Z: mapped to \\\\server\\share is a drive letter too; asking whether its file is there would make
    Windows contact the server. The drive's type is asked first (GetDriveTypeW: no server contact), and a network
    drive is refused before any isfile / isdir."""
    monkeypatch.setattr(browsersearch.winapi, "drive_type", lambda root: "network" if root == "Z:\\" else "fixed")
    assert browsersearch.download_path("Z:\\setups\\a.zip") is None
    assert browsersearch.download_path("z:/setups/a.zip") is None
    assert browsersearch.download_path("C:\\setups\\a.zip") == "C:\\setups\\a.zip"
    a, s, _ran = _api(tmp_path)
    looked = []
    real_isfile, real_isdir = os.path.isfile, os.path.isdir
    monkeypatch.setattr(api_mod.os.path, "isfile", lambda p: looked.append(p) or real_isfile(p))
    monkeypatch.setattr(api_mod.os.path, "isdir", lambda p: looked.append(p) or real_isdir(p))
    try:
        r = a.search("", {"kind": "browser", "browser": "download"})["results"][0]
        with s.wlock:
            s.db.execute("UPDATE browser_items SET url = ? WHERE id = ?", ("Z:\\setups\\setup.zip", -r["id"]))
            s.db.commit()
        looked.clear()
        assert a.open(r["id"])["ok"] is False and a.reveal(r["id"])["ok"] is False
        assert not [p for p in looked if p.upper().startswith("Z:")]
    finally:
        s.close()


def test_drive_type_names_a_network_drive():
    assert winapi.DRIVE_TYPES[4] == "network"
    assert winapi.drive_type("C:\\") in ("fixed", "removable", "network", "cd", "ram", None)
    assert winapi.drive_type("not a root") is None


def test_a_web_page_has_no_folder_and_other_file_actions_refuse(tmp_path):
    a, s, _ran = _api(tmp_path)
    try:
        r = a.search("", {"kind": "browser", "browser": "history"})["results"][0]
        assert a.reveal(r["id"])["ok"] is False
        assert a.open_with(r["id"])["ok"] is False and a.forget(r["id"])["ok"] is False
        assert a.thumbnail(r["id"]) == {"url": ""}
    finally:
        s.close()


def test_nothing_opens_while_the_setting_is_off(tmp_path, monkeypatch):
    a, s, _ran = _api(tmp_path)
    opened = []
    monkeypatch.setattr(winapi, "open_outside_job", lambda p: opened.append(p))
    try:
        rid = a.search("", {"kind": "browser", "browser": "history"})["results"][0]["id"]
        a._settings.update({"browser_data": "off"})
        assert a.open(rid)["ok"] is False and opened == []
    finally:
        s.close()


# ---------- the query words ----------
@pytest.mark.parametrize("text,kinds,terms", [
    ("history github", {"history"}, ["github"]),
    ("github history", {"history"}, ["github"]),
    ("visited yesterday", {"history"}, []),
    ("bookmark recipes", {"bookmark"}, ["recipes"]),
    ("bookmarks recipes", {"bookmark"}, ["recipes"]),
    ("saved login github", {"login"}, ["github"]),
    ("saved logins", {"login"}, []),
    ("password for github", {"login"}, ["github"]),
])
def test_the_query_words_map_to_soft_browser_kinds(text, kinds, terms):
    q = parse(text, browser_words=True)
    assert q.browser == kinds and q.terms == terms and q.soft
    # without the setting, or read as words again: plain words, no browser kind
    for q in (parse(text), parse(text, browser_words=True, soft_kinds=False)):
        assert q.browser == set()


def test_a_browser_word_with_nothing_found_is_read_as_a_word(tmp_path):
    a, s, _ran = _api(tmp_path)
    try:
        r = a.search("history report")
        assert [x["name"] for x in r["results"]] == ["history report.txt"]
        assert any("read as a word" in n for n in r["notes"])
        assert any(p["label"] == "Browser history" for p in a.search("history github")["parts"])
    finally:
        s.close()


def test_files_and_browser_items_are_ranked_together(tmp_path):
    a, s, _ran = _api(tmp_path)
    try:
        r = a.search("github")
        kinds = {x["kind"] for x in r["results"]}
        assert "text" in kinds and "browser" in kinds
        ids = [x["id"] for x in r["results"]]
        assert len(ids) == len(set(ids))                             # a browser id never collides with a file id
        # a file-only filter (a kind, a size, a folder) leaves browser items out
        assert {x["kind"] for x in a.search("github", {"kind": "text"})["results"]} == {"text"}
        assert {x["kind"] for x in a.search("github", {"size": "small"})["results"]} == {"text"}
    finally:
        s.close()


# ---------- photo channels never apply ----------
class PhotoText:
    model_id = "siglip"

    def encode(self, texts):
        return [[1.0]]

    def encode_question(self, text):
        return [1.0]


class PIndex:
    model = "siglip"
    n = 1
    FAST_FROM = 0

    def __init__(self, fid):
        self.fid = fid

    def search(self, v, k=10):
        return [(self.fid, 0.9)]

    def search_among(self, v, ids, k=10):
        return [(i, 0.9) for i in ids if i == self.fid][:k]


def test_photo_channels_never_apply_to_browser_items(tmp_path, monkeypatch):
    now = time.time()
    s = _store(tmp_path, now)
    try:
        beach = s.one("SELECT id FROM files WHERE name = 'beach.jpg'")
        asked = []
        real = search._photo_hits
        monkeypatch.setattr(search, "_photo_hits", lambda *x, **k: asked.append(x[1]) or real(*x, **k))
        kw = dict(now=now, photo_text=PhotoText(), pindex=PIndex(beach), browser=True)
        r = search.search(s, "beach", **kw)
        assert {x["name"] for x in r["results"]} == {"beach.jpg", "Beach weather"}
        web = next(x for x in r["results"] if x["kind"] == "browser")
        assert not [w for w in web["why"] if "picture" in w]
        # the Browser filter: no photo search at all, and no photo among the answers
        asked.clear()
        r = search.search(s, "beach", filters={"kind": "browser"}, **kw)
        assert [x["name"] for x in r["results"]] == ["Beach weather"] and asked == []
        r = search.search(s, "beach weather history", **kw)
        assert [x["name"] for x in r["results"]] == ["Beach weather"] and asked == []
    finally:
        s.close()


# ---------- the setting off changes nothing ----------
def test_with_the_setting_off_search_is_unchanged(tmp_path, monkeypatch):
    now = time.time()
    s = _store(tmp_path, now)
    try:
        def boom(*a, **k):
            raise AssertionError("the browser channel ran with the setting off")
        monkeypatch.setattr(browsersearch, "hits", boom)
        monkeypatch.setattr(browsersearch, "listing", boom)
        before = {}
        for text in ("github", "history report", "visited", "bookmark", "password for github", "beach"):
            before[text] = search.search(s, text, now=now)
        s.browser_clear()
        for text, r in before.items():
            again = search.search(s, text, now=now)
            assert [x["id"] for x in again["results"]] == [x["id"] for x in r["results"]], text
            assert again["parts"] == r["parts"] and again["notes"] == r["notes"], text
        assert "history" in before["history report"]["terms"]
        assert before["visited"]["terms"] == ["visited"]
    finally:
        s.close()


def test_api_search_reads_the_setting(tmp_path, monkeypatch):
    seen = []
    real = search.search
    monkeypatch.setattr(api_mod, "search", lambda *a, **k: seen.append(k.get("browser")) or real(*a, **k))
    for mode, want in (("off", False), ("history", True), ("history_logins", True)):
        sub = tmp_path / mode
        sub.mkdir()
        a, s, _ran = _api(sub, mode=mode)
        try:
            a.search("github")
        finally:
            s.close()
        assert bool(seen[-1]) is want, mode


def test_real_browser_results_match_the_contract(tmp_path):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from schemacheck import Checker
    contract = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract")
    check = Checker(contract)
    spec = check.doc("methods.schema.json")["methods"]["search"]
    a, s, _ran = _api(tmp_path)
    m = handlers.methods(a)
    try:
        for params in ({"text": "github"}, {"text": "", "filters": {"kind": "browser"}},
                       {"text": "bluetooth", "filters": {"kind": "launcher"}}):
            assert not check.errors(params, spec["params"], "methods.schema.json")
            r = protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "search", "params": params}), m)
            errs = check.errors(r["result"], spec["result"], "methods.schema.json")
            assert not errs, errs[:5]
        assert any(x["kind"] == "browser" for x in r["result"]["results"]) is False
    finally:
        s.close()
