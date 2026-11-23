"""The indexer and the Api follow the scope settings: roots, rules for the walk, secrets by name only, and a scope
change that leaves rows out of scope behind cleans them up."""
import os

from nobadfind import api as api_mod, indexer, scope, winapi
from nobadfind.const import DEFAULTS
from nobadfind.settings import Settings
from nobadfind.store import Store

PROF = scope.profile_dir()


class S(dict):
    # never this PC's own pauses (on battery, a full-screen window or a locked screen, a call): the walk would wait
    QUIET = {"pause_on_battery": False, "pause_fullscreen": False, "pause_on_call": False}

    def get(self, k, d=None):
        return super().get(k, self.QUIET.get(k, DEFAULTS.get(k)) if d is None else d)

    def all(self):
        return dict(DEFAULTS, **self)


DRIVES = [{"root": "C:\\", "type": "fixed", "label": ""}, {"root": "D:\\", "type": "fixed", "label": ""}]


def test_indexer_roots_follow_the_scope(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ix = indexer.Indexer(s, S())
    assert ix.roots(DRIVES) == scope.roots_for(DEFAULTS, DRIVES)
    ix.settings = S(scope="custom", roots=["D:\\Work"])
    assert ix.roots(DRIVES) == ["D:\\Work"]
    s.close()


def test_the_walk_gets_the_rules_from_the_settings(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    root = tmp_path / "r"
    (root / "node_modules").mkdir(parents=True)
    (root / "node_modules" / "x.js").write_text("x")
    (root / "a.txt").write_text("a")
    ix = indexer.Indexer(s, S(scope="custom", roots=[str(root)], include_caches=False))
    ix.status["plan"] = {"walk_threads": 2}
    monkeypatch.setattr(winapi, "drives", lambda: [])
    ix._scan_names()
    names = {r[0] for r in s.q("SELECT name FROM files")}
    assert "a.txt" in names and "x.js" not in names and "node_modules" not in names
    s.close()


def test_secrets_are_never_read_only_named(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ssh = os.path.join(PROF, ".ssh")
    s.upsert_files([(os.path.join(ssh, "config.txt"), "config.txt", ssh, ".txt", "text", 10, 5.0, 5.0, 1),
                    (os.path.join(PROF, "notes.txt"), "notes.txt", PROF, ".txt", "text", 10, 5.0, 5.0, 1)])
    ix = indexer.Indexer(s, S(include_secrets=True))
    rows = s.needs_text({".txt"}, 1 << 20)
    keep = ix._skip_secrets(rows, lambda r: s.set_text(r[0], r[4], [], indexer.NAMES_ONLY))
    assert [r[1] for r in keep] == [os.path.join(PROF, "notes.txt")]
    assert [r[1] for r in s.needs_text({".txt"}, 1 << 20)] == [os.path.join(PROF, "notes.txt")]
    assert s.one("SELECT text_err FROM files WHERE name='config.txt'") == indexer.NAMES_ONLY
    s.close()


def test_a_full_scan_drops_rows_left_outside_the_scope(tmp_path, monkeypatch):
    """Whole PC -> My files: the rows from the drive that's no longer walked go."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    root = tmp_path / "r"
    root.mkdir()
    (root / "a.txt").write_text("a")
    drive = os.path.splitdrive(str(tmp_path))[0] + "\\"
    other = os.path.join(drive, "zz-not-walked", "old.txt")
    s.upsert_files([(other, "old.txt", os.path.dirname(other), ".txt", "text", 1, 1.0, 1.0, 1)])
    s.set_meta("gen", 1)
    monkeypatch.setattr(winapi, "drives", lambda: [{"root": drive, "type": "fixed", "label": ""}])
    ix = indexer.Indexer(s, S(scope="custom", roots=[str(root)]))
    ix.status["plan"] = {"walk_threads": 2}
    ix._scan_names()
    names = {r[0] for r in s.q("SELECT name FROM files")}
    assert "a.txt" in names and "old.txt" not in names
    s.close()


# ---------- Api ----------
class Ix:
    drive_list = []

    def __init__(self):
        self.calls = []

        class W:
            def set(self_):
                self.calls.append("wake")
        self.wake = W()

    def rescan(self):
        self.calls.append("rescan")

    def roots(self, drives=None):
        return [PROF]


def make_api(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = Settings(str(tmp_path / "s.json"))
    a = api_mod.Api(s, st, Ix(), None)
    return a, s


def test_old_ui_setting_roots_switches_to_custom(tmp_path):
    a, s = make_api(tmp_path)
    r = a.set_settings({"roots": [PROF]})
    assert set(r["changed"]) == {"roots", "scope"} and a.get_settings()["scope"] == "custom"
    assert "rescan" in a._indexer.calls
    s.close()


def test_scope_and_category_changes_rescan(tmp_path):
    for key, value in (("scope", "my_files"), ("include_system", False), ("include_caches", False),
                       ("include_secrets", True)):
        a, s = make_api(tmp_path / key)
        assert a.set_settings({key: value})["changed"] == [key]
        assert "rescan" in a._indexer.calls, key
        s.close()


def test_secrets_turned_off_leave_the_index_at_once(tmp_path):
    a, s = make_api(tmp_path)
    a.set_settings({"include_secrets": True})
    ssh = os.path.join(PROF, ".ssh")
    s.upsert_files([(os.path.join(ssh, "id_rsa"), "id_rsa", ssh, "", "other", 10, 5.0, 5.0, 1),
                    (os.path.join(PROF, "k.pem"), "k.pem", PROF, ".pem", "other", 10, 5.0, 5.0, 1),
                    (os.path.join(PROF, "notes.txt"), "notes.txt", PROF, ".txt", "text", 10, 5.0, 5.0, 1)])
    a.set_settings({"include_secrets": False})
    assert {r[0] for r in s.q("SELECT name FROM files")} == {"notes.txt"}
    s.close()


def test_no_thumbnail_for_a_secret(tmp_path, monkeypatch):
    a, s = make_api(tmp_path)
    a.set_settings({"include_secrets": True})
    keys = os.path.join(PROF, ".gnupg")
    s.upsert_files([(os.path.join(keys, "card.jpg"), "card.jpg", keys, ".jpg", "image", 10, 5.0, 5.0, 1)])
    fid = s.one("SELECT id FROM files")
    monkeypatch.setattr(api_mod.thumbs, "data_url", lambda p, m: "data:image/png;base64,AAAA")
    assert a.thumbnail(fid) == {"url": ""}
    s.close()


def test_scope_info_from_the_api(tmp_path, monkeypatch):
    a, s = make_api(tmp_path)
    monkeypatch.setattr(winapi, "drives", lambda: DRIVES)
    info = a.scope_info()
    assert info["scope"] == "whole_pc" and [c["id"] for c in info["categories"]] == list(scope.CATEGORIES)
    s.close()


def test_the_watching_loop_counts_the_index_at_most_every_half_minute(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ix = indexer.Indexer(s, S())
    now = [1000.0]
    ix._clock = lambda: now[0]
    calls = []
    s.stats = lambda: calls.append(1) or {"files": 1}
    ix._refresh_stats()
    ix._refresh_stats()
    now[0] += indexer.STATS_EVERY + 1
    ix._refresh_stats()
    assert len(calls) == 2 and ix.status["files"] == 1
    s.close()


def test_status_counts_cost_at_most_a_twentieth_of_a_core(tmp_path):
    """A whole PC is about a million rows: every COUNT reads the whole table. The Indexing page polls status every
    2 s, so the counts are cached for 10 s, or 20 times as long as they took (5% of one core at most)."""
    a, s = make_api(tmp_path)
    now = [100.0]
    a._clock = lambda: now[0]
    took = [0.0]
    calls = []
    real = s.stats

    def slow_stats():
        calls.append(1)
        now[0] += took[0]                       # the counting itself takes time on the clock
        return real()
    s.stats = slow_stats
    a._stats()
    a._stats()
    assert len(calls) == 1
    now[0] += api_mod.STATS_TTL + 0.1
    took[0] = 3.0                               # a big index: 3 s to count
    a._stats()
    assert len(calls) == 2
    now[0] += 30                                # within 20 x 3 s of the last count
    a._stats()
    assert len(calls) == 2
    now[0] += 31
    a._stats()
    assert len(calls) == 3
    s.close()


def test_browser_profile_files_are_never_read_even_with_caches_on_and_secrets_off(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ff = os.path.join(PROF, "AppData", "Roaming", "Mozilla", "Firefox", "Profiles", "x.default")
    s.upsert_files([(os.path.join(ff, "prefs.js"), "prefs.js", ff, ".js", "code", 10, 5.0, 5.0, 1),
                    (os.path.join(PROF, "app.js"), "app.js", PROF, ".js", "code", 10, 5.0, 5.0, 1)])
    ix = indexer.Indexer(s, S(include_caches=True, include_secrets=False))
    keep = ix._skip_secrets(s.needs_text({".js"}, 1 << 20), lambda r: s.set_text(r[0], r[4], [], indexer.NAMES_ONLY))
    assert [r[1] for r in keep] == [os.path.join(PROF, "app.js")]
    assert s.one("SELECT text_err FROM files WHERE name='prefs.js'") == indexer.NAMES_ONLY
    s.close()


def test_turning_secrets_off_removes_browser_credential_stores(tmp_path):
    a, s = make_api(tmp_path)
    a.set_settings({"include_secrets": True})
    chrome = os.path.join(PROF, "AppData", "Local", "Google", "Chrome", "User Data", "Default")
    cred = os.path.join(PROF, "AppData", "Roaming", "Microsoft", "Credentials")
    s.upsert_files([(os.path.join(chrome, "Login Data"), "Login Data", chrome, "", "other", 1, 5.0, 5.0, 1),
                    (os.path.join(chrome, "Preferences"), "Preferences", chrome, "", "other", 1, 5.0, 5.0, 1),
                    (os.path.join(cred, "DFBE70A7"), "DFBE70A7", cred, "", "other", 1, 5.0, 5.0, 1),
                    (os.path.join(PROF, ".npmrc"), ".npmrc", PROF, "", "other", 1, 5.0, 5.0, 1),
                    (os.path.join(PROF, "History"), "History", PROF, "", "other", 1, 5.0, 5.0, 1)])
    a.set_settings({"include_secrets": False})
    assert {r[0] for r in s.q("SELECT name FROM files")} == {"Preferences", "History"}
    s.close()


# ---------- security review 2026-11-22 (M2): the one-time clean-up after the rules grew ----------
def _old_index(tmp_path):
    """An index made with the rules before RULES_REV 2: program records were read like any file."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    psr = os.path.join(PROF, "AppData", "Roaming", "Microsoft", "Windows", "PowerShell", "PSReadLine")
    fz = os.path.join(PROF, "AppData", "Roaming", "FileZilla")
    docs = os.path.join(PROF, "Documents")
    rows = [(os.path.join(psr, "ConsoleHost_history.txt"), "ConsoleHost_history.txt", psr, ".txt", "text"),
            (os.path.join(fz, "sitemanager.xml"), "sitemanager.xml", fz, ".xml", "text"),
            (os.path.join(docs, "notes.txt"), "notes.txt", docs, ".txt", "text"),
            (os.path.join(docs, "beach.jpg"), "beach.jpg", docs, ".jpg", "photo")]
    s.upsert_files([r + (10, 5.0, 5.0, 1) for r in rows])
    ids = {r[0]: r[1] for r in s.q("SELECT name, id FROM files")}
    for name in ("ConsoleHost_history.txt", "sitemanager.xml", "notes.txt"):
        s.set_text(ids[name], 5.0, [f"token-{name}"])
    chunk = {r[1]: r[0] for r in s.q("SELECT c.id, f.name FROM chunks c JOIN files f ON f.id=c.file_id")}
    s.add_vectors([(chunk[n], b"\x00" * 8) for n in chunk])
    s.set_photo_vector(ids["beach.jpg"], 5.0, b"\x01" * 8)
    s.set_meta("scope_rules", "1")
    return s, ids


def test_new_rules_drop_program_records_once_and_keep_the_rest(tmp_path):
    s, ids = _old_index(tmp_path)
    ix = indexer.Indexer(s, S())                                      # defaults: secrets off
    assert ix._apply_new_rules() == (2, 2)
    names = {r[0] for r in s.q("SELECT name FROM files")}
    assert names == {"notes.txt", "beach.jpg"}
    assert [r[0] for r in s.q("SELECT body FROM chunks")] == ["token-notes.txt"]
    assert s.one("SELECT count(*) FROM vecs") == 1                   # the rest of the index is untouched
    assert s.one("SELECT count(*) FROM pvecs WHERE length(v) > 0") == 1
    assert s.q("SELECT rowid FROM text WHERE text MATCH ?", ('"token"',)) != []
    assert s.q("SELECT rowid FROM text WHERE text MATCH ?", ('"consolehost"',)) == []
    assert s.meta("scope_rules") == scope.RULES_REV
    s.set_text(ids["notes.txt"], 5.0, ["again"])
    assert ix._apply_new_rules() == (0, 0)                           # once: the flag is set
    assert [r[0] for r in s.q("SELECT body FROM chunks")] == ["again"]
    s.close()


def test_new_rules_with_secrets_on_keep_the_names_only(tmp_path):
    s, ids = _old_index(tmp_path)
    ix = indexer.Indexer(s, S(include_secrets=True))
    assert ix._apply_new_rules() == (2, 0)
    names = {r[0] for r in s.q("SELECT name FROM files")}
    assert names == {"ConsoleHost_history.txt", "sitemanager.xml", "notes.txt", "beach.jpg"}
    assert [r[0] for r in s.q("SELECT body FROM chunks")] == ["token-notes.txt"]
    assert s.one("SELECT text_err FROM files WHERE name='sitemanager.xml'") == indexer.NAMES_ONLY
    assert [r[1] for r in s.needs_text({".txt", ".xml"}, 1 << 20)] == []          # never read again
    assert s.one("SELECT count(*) FROM vecs") == 1
    s.close()


def test_new_rules_run_at_the_start_of_the_indexer(tmp_path):
    src = open(indexer.__file__, encoding="utf-8").read()
    run = src[src.index("    def _run(self):"):]
    assert run.index("self._apply_new_rules()") < run.index("self._load_embedder()")


def test_new_rules_remove_recent_items_even_with_secrets_on(tmp_path):
    """Fix round 1 (I1): an index made while Recent items were names-only loses them at the next start."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    rec = os.path.join(PROF, "AppData", "Roaming", "Microsoft", "Windows", "Recent")
    jump = os.path.join(rec, "AutomaticDestinations")
    docs = os.path.join(PROF, "Documents")
    s.upsert_files([(rec, "Recent", os.path.dirname(rec), "", "folder", 0, 5.0, 5.0, 1),
                    (os.path.join(rec, "plan.docx.lnk"), "plan.docx.lnk", rec, ".lnk", "app", 1, 5.0, 5.0, 1),
                    (os.path.join(jump, "a.automaticDestinations-ms"), "a.automaticDestinations-ms", jump, "",
                     "other", 1, 5.0, 5.0, 1),
                    (os.path.join(docs, "Recent"), "Recent", docs, "", "folder", 0, 5.0, 5.0, 1),
                    (os.path.join(docs, "plan.docx"), "plan.docx", docs, ".docx", "document", 1, 5.0, 5.0, 1)])
    s.set_meta("scope_rules", "2")
    ix = indexer.Indexer(s, S(include_secrets=True))
    ix._apply_new_rules()
    names = {r[0] for r in s.q("SELECT path FROM files")}
    assert names == {os.path.join(docs, "Recent"), os.path.join(docs, "plan.docx")}
    assert s.meta("scope_rules") == scope.RULES_REV
    s.close()
