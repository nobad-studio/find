"""1.2.0 browser data, the reader (browser spec 2026-11-22 §2-§3): opt-in (setting browser_data, off by default),
read by COPYING the databases with full sharing into <data>\\tmp\\browser-*, the copy opened read-only
(mode=ro&immutable=1) and deleted at once (also on error), a locked file retried at 1/5/30 min and never a browser
killed, password values never read, an unknown schema skipped with a note, off deletes every row, and the read in
a WORKERS text-reader worker, never in the engine. Every database here is synthetic: the user's real browser
profiles are never read (browserdata.profiles is always given a made-up environment or patched)."""
import ctypes
import json
import os
import sqlite3

import pytest

from nobadfind import browserdata as bd, indexer as ix_mod, settings as settings_mod
from nobadfind.const import BROWSER_CONSENT, DEFAULTS
from nobadfind.store import Store
from test_scope_indexer import S, make_api

T0 = 1_700_000_000                  # a visit time (unix)
MARKER = "PW-MARKER-7f3a9c"         # the password value: it must appear nowhere


def webkit(t):
    return int((t + 11644473600) * 1_000_000)


# ---------- synthetic browser databases ----------
def chromium_history(path, wal=False, schema="ok"):
    c = sqlite3.connect(path)
    if wal:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR)")
    c.execute("INSERT INTO meta VALUES('version', '70')")
    if schema == "ok":
        c.execute("CREATE TABLE urls(id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, visit_count INTEGER "
                  "DEFAULT 0 NOT NULL, typed_count INTEGER DEFAULT 0 NOT NULL, last_visit_time INTEGER NOT NULL, "
                  "hidden INTEGER DEFAULT 0 NOT NULL)")
    else:                           # a schema this version doesn't know: no last_visit_time
        c.execute("CREATE TABLE urls(id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, visit_count INTEGER, "
                  "last_visit INTEGER)")
    c.execute("CREATE TABLE downloads(id INTEGER PRIMARY KEY, guid VARCHAR, current_path LONGVARCHAR, "
              "target_path LONGVARCHAR NOT NULL, start_time INTEGER NOT NULL, end_time INTEGER NOT NULL, "
              "tab_url VARCHAR, total_bytes INTEGER)")
    if schema == "ok":
        c.executemany("INSERT INTO urls(url, title, visit_count, last_visit_time, hidden) VALUES(?,?,?,?,?)", [
            ("https://www.example.com/tax-form", "Tax form 2026", 7, webkit(T0), 0),
            ("https://news.example.org/a", "Morning news", 2, webkit(T0 + 60), 0),
            ("javascript:alert(1)", "A script, never kept", 1, webkit(T0), 0),
            ("https://hidden.example.com/", "hidden row", 1, webkit(T0), 1),
        ])
    c.execute("INSERT INTO downloads(guid, current_path, target_path, start_time, end_time, tab_url, total_bytes) "
              "VALUES('g', 'C:\\Users\\x\\Downloads\\report.pdf', 'C:\\Users\\x\\Downloads\\report.pdf', ?, ?, "
              "'https://files.example.net/report', 10)", (webkit(T0), webkit(T0 + 5)))
    c.commit()
    return c                        # still open: a running browser holds its database (WAL: frames not checkpointed)


def chromium_logins(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE logins(origin_url VARCHAR NOT NULL, action_url VARCHAR, username_element VARCHAR, "
              "username_value VARCHAR, password_element VARCHAR, password_value BLOB, signon_realm VARCHAR NOT NULL, "
              "date_created INTEGER NOT NULL, date_last_used INTEGER NOT NULL DEFAULT 0)")
    c.execute("INSERT INTO logins VALUES('https://mail.example.com/login', '', 'u', 'alice@example.com', 'p', ?, "
              "'https://mail.example.com/', ?, ?)", (("v10" + MARKER).encode(), webkit(T0), webkit(T0 + 9)))
    c.commit()
    c.close()


def chromium_bookmarks(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "roots": {
            "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "children": [
                {"type": "url", "name": "Recipes", "url": "https://cook.example.com/", "date_added": str(webkit(T0))},
                {"type": "folder", "name": "Work", "children": [
                    {"type": "url", "name": "Wiki", "url": "https://wiki.example.com/", "date_added": "0"},
                    {"type": "url", "name": "Bookmarklet", "url": "javascript:void(0)", "date_added": "0"}]}]},
            "other": {"type": "folder", "name": "Other", "children": []}}}, f)


def firefox_places(path):
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, "
              "rev_host LONGVARCHAR, visit_count INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0 NOT NULL, "
              "typed INTEGER DEFAULT 0 NOT NULL, frecency INTEGER DEFAULT -1 NOT NULL, last_visit_date INTEGER)")
    c.execute("CREATE TABLE moz_bookmarks(id INTEGER PRIMARY KEY, type INTEGER, fk INTEGER DEFAULT NULL, "
              "parent INTEGER, position INTEGER, title LONGVARCHAR, dateAdded INTEGER, lastModified INTEGER)")
    c.executemany("INSERT INTO moz_places(id, url, title, visit_count, last_visit_date) VALUES(?,?,?,?,?)", [
        (1, "https://fox.example.com/garden", "Garden ideas", 3, T0 * 1_000_000),
        (2, "https://maps.example.com/", "Maps", 0, None),
    ])
    c.executemany("INSERT INTO moz_bookmarks(id, type, fk, parent, title, dateAdded) VALUES(?,?,?,?,?,?)", [
        (1, 2, None, 0, "root", 0), (2, 2, None, 1, "Holidays", 0), (3, 1, 2, 2, "Maps", T0 * 1_000_000)])
    c.commit()
    c.close()


def firefox_logins(path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"logins": [{"hostname": "https://shop.example.com", "encryptedUsername": "MDIEEPgAAAAA",
                               "encryptedPassword": MARKER, "timeLastUsed": T0 * 1000}]}, f)


def make_env(tmp_path):
    """A made-up LOCALAPPDATA / APPDATA with an Edge profile (named "Work") and a Firefox profile."""
    local, roaming = tmp_path / "Local", tmp_path / "Roaming"
    edge = local / "Microsoft" / "Edge" / "User Data"
    (edge / "Profile 1").mkdir(parents=True)
    (edge / "Local State").write_text(json.dumps({"profile": {"info_cache": {"Profile 1": {"name": "Work"}}}}))
    held = chromium_history(str(edge / "Profile 1" / "History"))
    held.close()
    chromium_logins(str(edge / "Profile 1" / "Login Data"))
    chromium_bookmarks(str(edge / "Profile 1" / "Bookmarks"))
    ff = roaming / "Mozilla" / "Firefox"
    (ff / "Profiles" / "ab12.default-release").mkdir(parents=True)
    (ff / "profiles.ini").write_text("[Profile0]\nName=default-release\nIsRelative=1\n"
                                     "Path=Profiles/ab12.default-release\n")
    firefox_places(str(ff / "Profiles" / "ab12.default-release" / "places.sqlite"))
    firefox_logins(str(ff / "Profiles" / "ab12.default-release" / "logins.json"))
    return {"LOCALAPPDATA": str(local), "APPDATA": str(roaming)}


def browser_tmp(data):
    root = os.path.join(str(data), "tmp")
    return [n for n in os.listdir(root) if n.startswith("browser-")] if os.path.isdir(root) else []


def job_for(env, data, browser, logins=True):
    p = next(p for p in bd.profiles(env) if p["browser"] == browser)
    return dict(p, data_dir=str(data), logins=logins)


# ---------- the setting ----------
def test_the_setting_is_off_by_default_with_three_values():
    assert DEFAULTS["browser_data"] == "off"
    for v in ("off", "history", "history_logins"):
        assert settings_mod.coerce("browser_data", v) == v
    for v in (True, "on", "logins", None, 1):
        assert settings_mod.coerce("browser_data", v) == "off"


def test_turning_it_on_needs_the_consent_word_narrowing_does_not(tmp_path):
    from nobadfind.rpc.handlers import settings as h
    a, s = make_api(tmp_path)
    m = h.methods(a)
    assert m["set_settings"]({"changes": {"browser_data": "history"}})["changed"] == []
    assert m["set_settings"]({"changes": {"browser_data": "history"}, "consent": "READ_APP_SECRETS"})["changed"] == []
    r = m["set_settings"]({"changes": {"browser_data": "history"}, "consent": BROWSER_CONSENT})
    assert r["changed"] == ["browser_data"] and r["settings"]["browser_data"] == "history"
    assert m["set_settings"]({"changes": {"browser_data": "history_logins"}})["changed"] == []   # reads more: ask
    assert m["set_settings"]({"changes": {"browser_data": "history_logins"},
                              "consent": BROWSER_CONSENT})["changed"] == ["browser_data"]
    assert m["set_settings"]({"changes": {"browser_data": "history"}})["changed"] == ["browser_data"]
    assert m["set_settings"]({"changes": {"browser_data": "off"}})["changed"] == ["browser_data"]
    s.close()


# ---------- profiles ----------
def test_profiles_are_found_per_browser_with_their_names(tmp_path):
    env = make_env(tmp_path)
    got = {(p["browser"], p["profile"], p["engine"]) for p in bd.profiles(env)}
    assert got == {("Edge", "Work", "chromium"), ("Firefox", "default-release", "firefox")}
    assert bd.profiles({}) == []                 # no folders known: nothing, never a guess


# ---------- copy, don't lock ----------
def _hold(path, share):
    """Another program's handle on path (GENERIC_READ | GENERIC_WRITE) with the given sharing."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = ctypes.c_void_p
    k.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                              ctypes.c_uint32, ctypes.c_void_p]
    h = k.CreateFileW(path, 0xC0000000, share, None, 3, 0x80, None)
    assert h not in (None, ctypes.c_void_p(-1).value)
    return k, h


def test_copy_uses_full_sharing_with_wal_and_shm_into_data_tmp(tmp_path, monkeypatch):
    data = tmp_path / "data"
    src = tmp_path / "History"
    held = chromium_history(str(src), wal=True)          # the browser is running: open, WAL not checkpointed
    assert os.path.getsize(str(src) + "-wal") > 0
    k, h = _hold(str(src), 0x7)                          # and another handle that shares read/write/delete
    shares, copied = [], []
    real_open = bd._open_shared
    monkeypatch.setattr(bd, "_open_shared", lambda p: (shares.append(p), real_open(p))[1])
    real_copy = bd.copy_shared
    monkeypatch.setattr(bd, "copy_shared", lambda a, b: (copied.append((a, b)), real_copy(a, b))[1])
    try:
        assert bd.SHARE_ALL == 0x7 and bd.GENERIC_READ == 0x80000000
        with bd.snapshot(str(src), str(data)) as db:
            names = sorted(os.path.basename(b) for _a, b in copied)
            assert names == ["History", "History-shm", "History-wal"]
            folder = os.path.dirname(copied[0][1])
            assert os.path.dirname(folder) == os.path.join(str(data), "tmp")
            assert os.path.basename(folder).startswith("browser-")
            rows = db.execute("SELECT title FROM urls ORDER BY id").fetchall()
            assert ("Tax form 2026",) in rows                  # the WAL's rows are in the copy
        assert len(shares) == 3
        assert browser_tmp(data) == []                       # deleted at once
        held.execute("INSERT INTO urls(url, title, last_visit_time) VALUES('https://x.example/', 'x', 1)")
        held.commit()                                        # the browser's own database still works
    finally:
        k.CloseHandle(ctypes.c_void_p(h))
        held.close()


def test_the_copy_is_opened_read_only_and_immutable(tmp_path, monkeypatch):
    data = tmp_path / "data"
    chromium_history(str(tmp_path / "History")).close()
    uris = []
    real = sqlite3.connect
    monkeypatch.setattr(bd.sqlite3, "connect", lambda u, *a, **kw: (uris.append(u), real(u, *a, **kw))[1])
    with bd.snapshot(str(tmp_path / "History"), str(data)) as db:
        db.execute("SELECT 1 FROM urls").fetchall()
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM urls")
    opened = [u for u in uris if "immutable" in u]
    assert opened and all(u.startswith("file:") and u.endswith("?mode=ro&immutable=1") for u in opened)
    assert all("browser-" in u for u in opened)


def test_the_copy_is_deleted_also_on_error(tmp_path):
    data = tmp_path / "data"
    chromium_history(str(tmp_path / "History")).close()
    with pytest.raises(ZeroDivisionError):
        with bd.snapshot(str(tmp_path / "History"), str(data)):
            assert len(browser_tmp(data)) == 1
            raise ZeroDivisionError
    assert browser_tmp(data) == []


def test_leftover_copies_are_wiped_at_engine_start(tmp_path):
    data = tmp_path / "data"
    (data / "tmp" / "browser-old").mkdir(parents=True)
    (data / "tmp" / "browser-old" / "History").write_text("x")
    (data / "tmp" / "other").mkdir()
    bd.wipe_tmp(str(data))
    assert browser_tmp(data) == [] and (data / "tmp" / "other").is_dir()
    src = open(os.path.join(os.path.dirname(bd.__file__), "engine.py"), encoding="utf-8").read()
    assert "browserdata.wipe_tmp(DATA_DIR)" in src


def test_locked_history_is_copied_or_retried_never_killed(tmp_path):
    """Review Focus 5: a file the browser holds exclusively is never forced: no process is ever ended or asked to
    close; the read retries at 1, 5 and 30 minutes, then gives up with a note until the file changes."""
    src = open(bd.__file__, encoding="utf-8").read()
    for word in ("TerminateProcess", "taskkill", "OpenProcess", "WM_CLOSE", "PostMessage", "os.kill", "terminate(",
                 "subprocess", "psutil"):
        assert word not in src, word
    data = tmp_path / "data"
    path = tmp_path / "History"
    chromium_history(str(path)).close()
    k, h = _hold(str(path), 0)                           # exclusive: a sharing violation
    try:
        with pytest.raises(bd.Locked):
            with bd.snapshot(str(path), str(data)):
                pass
        assert browser_tmp(data) == []
    finally:
        k.CloseHandle(ctypes.c_void_p(h))
    assert bd.RETRY_S == (60, 300, 1800)
    sch = bd.Schedule()
    p = {"browser": "Edge", "profile": "Work", "mtime": 5.0}
    assert sch.due([p], now=0) == [p]
    waits = []
    now = 0.0
    for _ in range(3):
        sch.done(p, now, locked=True)
        nxt = sch.next_at(p)
        waits.append(nxt - now)
        assert sch.due([p], now=nxt - 1) == []
        now = nxt
        assert sch.due([p], now=now) == [p]
    assert waits == [60, 300, 1800]
    sch.done(p, now, locked=True)                        # the fourth: given up, with a note
    assert sch.due([p], now=now + 10 ** 6) == []
    assert "in use" in sch.state(p)["error"]
    assert sch.due([dict(p, mtime=6.0)], now=now + 10 ** 6) == [dict(p, mtime=6.0)]   # changed: try again


def test_fresh_at_most_every_ten_minutes_and_only_when_changed():
    sch = bd.Schedule()
    p = {"browser": "Edge", "profile": "Work", "mtime": 5.0}
    sch.done(p, 0.0, counts={"history": 2})
    assert sch.due([p], now=10_000) == []                # unchanged: no read
    q = dict(p, mtime=6.0)
    assert sch.due([q], now=bd.FRESH_S - 1) == []         # changed, but read less than 10 minutes ago
    assert sch.due([q], now=bd.FRESH_S) == [q]
    assert sch.state(p)["counts"] == {"history": 2}


# ---------- what is read ----------
def test_chromium_history_downloads_bookmarks_and_logins(tmp_path):
    env = make_env(tmp_path)
    data = tmp_path / "data"
    r = bd.read_profile(job_for(env, data, "Edge"))
    k = r["kinds"]
    assert {(i[1], i[2], i[3], round(i[4]), i[5]) for i in k["history"]} == {
        ("Tax form 2026", "https://www.example.com/tax-form", "www.example.com", T0, 7),
        ("Morning news", "https://news.example.org/a", "news.example.org", T0 + 60, 2)}   # no script, no hidden
    assert [(i[1], i[2], i[3], round(i[4])) for i in k["download"]] == [
        ("report.pdf", "C:\\Users\\x\\Downloads\\report.pdf", "files.example.net", T0 + 5)]
    assert {(i[1], i[2], i[6]) for i in k["bookmark"]} == {("Recipes", "https://cook.example.com/", "Bookmarks bar"),
                                                            ("Wiki", "https://wiki.example.com/", "Bookmarks bar/Work")}
    assert [(i[1], i[2], i[3]) for i in k["login"]] == [("alice@example.com", "https://mail.example.com/login",
                                                         "mail.example.com")]
    assert r["notes"] == [] and browser_tmp(data) == []
    r = bd.read_profile(job_for(env, data, "Edge", logins=False))
    assert "login" not in r["kinds"]


def test_firefox_history_bookmarks_and_logins_host_only(tmp_path):
    env = make_env(tmp_path)
    data = tmp_path / "data"
    k = bd.read_profile(job_for(env, data, "Firefox"))["kinds"]
    assert [(i[1], i[3], round(i[4]), i[5]) for i in k["history"]] == [("Garden ideas", "fox.example.com", T0, 3)]
    assert [(i[1], i[2], i[6]) for i in k["bookmark"]] == [("Maps", "https://maps.example.com/", "Holidays")]
    assert [(i[1], i[2], i[3]) for i in k["login"]] == [("", "https://shop.example.com", "shop.example.com")]
    assert browser_tmp(data) == []


def test_an_unknown_schema_is_skipped_with_a_note(tmp_path):
    env = make_env(tmp_path)
    data = tmp_path / "data"
    hist = os.path.join(env["LOCALAPPDATA"], "Microsoft", "Edge", "User Data", "Profile 1", "History")
    os.remove(hist)
    chromium_history(hist, schema="new").close()
    r = bd.read_profile(job_for(env, data, "Edge"))
    assert "history" not in r["kinds"]                   # not guessed: what it had stays as it was
    assert any("History" in n and "not read" in n for n in r["notes"])
    assert r["kinds"]["bookmark"] and r["kinds"]["login"]   # the other files are still read
    assert browser_tmp(data) == []


def test_password_value_never_read(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    data = tmp_path / "data"
    logged, made = [], []
    monkeypatch.setattr(bd, "log", lambda m, level="info": logged.append(m))
    monkeypatch.setattr(ix_mod, "log", lambda m, level="info": logged.append(m))
    real_copy = bd.copy_shared

    def copy(a, b):
        made.append(os.path.basename(b))
        return real_copy(a, b)
    monkeypatch.setattr(bd, "copy_shared", copy)
    store = Store(str(tmp_path / "i.db"), encrypt=False)
    try:
        for b in ("Edge", "Firefox"):
            r = bd.read_profile(job_for(env, data, b))
            assert MARKER not in repr(r)
            for kind, rows in r["kinds"].items():
                store.put_browser_items(b, r["profile"], kind, rows)
        assert store.one("SELECT count(*) FROM browser_items WHERE kind = 'login'") == 2
        assert not any(n.startswith("Login Data") for n in made)   # read in memory: never copied to disk
        store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for root, _d, files in os.walk(str(tmp_path)):
            for f in files:
                p = os.path.join(root, f)
                if "Local" in p.split(os.sep) or "Roaming" in p.split(os.sep):
                    continue                                 # the synthetic browser's own files
                with open(p, "rb") as fh:
                    assert MARKER.encode() not in fh.read(), p
        assert not any(MARKER in m for m in logged)
        assert browser_tmp(data) == []
    finally:
        store.close()


# ---------- the index ----------
def test_rows_go_in_per_kind_and_fts_finds_them(tmp_path):
    store = Store(str(tmp_path / "i.db"), encrypt=False)
    try:
        h = [("history", "Tax form 2026", "https://www.example.com/tax", "www.example.com", T0, 7, "")]
        store.put_browser_items("Edge", "Work", "history", h)
        store.put_browser_items("Edge", "Work", "login", [("login", "alice", "https://m.example.com/", "m.example.com",
                                                            T0, 0, "")])
        assert store.browser_counts() == {"history": 1, "login": 1}
        store.put_browser_items("Edge", "Work", "history", h + [("history", "Second", "https://b.example/", "b.example",
                                                                 T0, 1, "")])
        assert store.browser_counts() == {"history": 2, "login": 1}
        assert store.q("SELECT b.title FROM browser_fts f JOIN browser_items b ON b.id = f.rowid "
                       "WHERE browser_fts MATCH ?", ('"tax"',)) == [("Tax form 2026",)]
        assert store.put_browser_items("Edge", "Work", "history", h, allow=lambda: False) is False
        assert store.browser_counts()["history"] == 2   # a read that finished after off: dropped
        store.browser_keep_profiles({("Firefox", "default")})
        assert store.browser_counts() == {}              # a profile that's gone takes its rows
        store.put_browser_items("Edge", "Work", "history", h)
        store.wipe()
        assert store.one("SELECT count(*) FROM browser_items") == 0
    finally:
        store.close()


def test_setting_it_off_deletes_every_row_and_the_temp_folder_is_empty(tmp_path):
    a, s = make_api(tmp_path)
    data = os.path.dirname(s.db_path)
    os.makedirs(os.path.join(data, "tmp", "browser-left"))
    a.set_settings({"browser_data": "history_logins"}, consent=BROWSER_CONSENT)
    for kind in ("history", "bookmark", "download", "login"):
        s.put_browser_items("Edge", "Work", kind, [(kind, "t", "https://e.example/", "e.example", T0, 1, "")])
    a.set_settings({"browser_data": "history"})          # logins no more: their rows go, the rest stays
    assert s.browser_counts() == {"history": 1, "bookmark": 1, "download": 1}
    a.set_settings({"browser_data": "off"})
    assert s.one("SELECT count(*) FROM browser_items") == 0
    assert s.one("SELECT count(*) FROM browser_fts") == 0
    assert browser_tmp(data) == []
    s.close()


# ---------- the process ----------
def _indexer(tmp_path, env, mode="history_logins"):
    store = Store(str(tmp_path / "i.db"), encrypt=False)
    ix = ix_mod.Indexer(store, S(browser_data=mode))
    return ix, store


def test_the_read_runs_in_a_workers_text_reader_never_in_the_engine(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    real = bd.profiles
    monkeypatch.setattr(bd, "profiles", lambda env_=None: real(env))
    # in this (the engine's) process the reading code fails: rows can only come from the worker process
    monkeypatch.setattr(bd, "_read_sources", lambda job: (_ for _ in ()).throw(AssertionError("read in engine")))
    pools = []
    real_pool = ix_mod.cf.ProcessPoolExecutor

    def pool(*a, **kw):
        pools.append(kw)
        return real_pool(*a, **kw)
    monkeypatch.setattr(ix_mod.cf, "ProcessPoolExecutor", pool)
    ix, store = _indexer(tmp_path, env)
    try:
        ix._read_browsers()
        assert pools and all(p["initializer"] is ix_mod.extract.init_worker for p in pools)   # WORKERS, low priority
        assert store.browser_counts() == {"history": 3, "bookmark": 3, "download": 1, "login": 2}
        assert ix._text_pool is None and ix._browser_pool is None
        assert browser_tmp(os.path.dirname(store.db_path)) == []
        n = len(pools)
        ix._read_browsers()                              # unchanged: not read again
        assert len(pools) == n
    finally:
        store.close()


def test_off_reads_nothing_and_a_read_after_off_is_dropped(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    real = bd.profiles
    monkeypatch.setattr(bd, "profiles", lambda env_=None: (_ for _ in ()).throw(AssertionError("looked")))
    ix, store = _indexer(tmp_path, env, mode="off")
    try:
        ix._read_browsers()                              # off: not even the profile folders are looked at
        monkeypatch.setattr(bd, "profiles", lambda env_=None, real=real: real(env))
        settings = ix.settings

        class FakePool:
            def __init__(self, *a, **kw):
                pass

            def submit(self, fn, job):
                settings["browser_data"] = "off"         # turned off while the worker read
                import concurrent.futures as cf
                f = cf.Future()
                f.set_result(bd.read_profile(job))
                return f

            def shutdown(self, **kw):
                pass
        monkeypatch.setattr(ix_mod.cf, "ProcessPoolExecutor", FakePool)
        settings["browser_data"] = "history"
        ix._read_browsers()
        assert store.one("SELECT count(*) FROM browser_items") == 0
    finally:
        store.close()



def test_login_data_is_never_copied_even_with_a_wal(tmp_path, monkeypatch):
    env = make_env(tmp_path)
    data = tmp_path / "data"
    ld = os.path.join(env["LOCALAPPDATA"], "Microsoft", "Edge", "User Data", "Profile 1", "Login Data")
    with open(ld + "-wal", "wb") as f:
        f.write(b"\0" * 64)                              # a -wal not folded in yet
    made = []
    monkeypatch.setattr(bd, "copy_shared", lambda a, b: made.append(os.path.basename(b)))
    monkeypatch.setattr(bd, "snapshot", lambda *a: (_ for _ in ()).throw(FileNotFoundError("History")))
    r = bd.read_profile(job_for(env, data, "Edge"))
    assert [i[1] for i in r["kinds"]["login"]] == ["alice@example.com"]   # the main file, in memory
    assert not any(n.startswith("Login Data") for n in made)
