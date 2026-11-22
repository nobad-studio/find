"""Fixes for the security review of 2026-11-22 (.superpowers/sdd/security-review-2026-11-22.md) that have no better
home: forget past the old cap (M4), deep JSON (L1), Wipe (L10)."""
import os

from nobadfind import settings as settings_mod
from test_scope_indexer import PROF, make_api


def _add(s, n, folder="Docs"):
    d = os.path.join(PROF, folder)
    s.upsert_files([(os.path.join(d, f"f{i}.txt"), f"f{i}.txt", d, ".txt", "text", 1, 1.0, 1.0, 1) for i in range(n)])
    return {r[1]: r[0] for r in s.q("SELECT id, name FROM files")}


# ---------- M4: forget never says ok without keeping the file out ----------
def test_forget_after_200_entries_still_keeps_the_new_one_out(tmp_path):
    a, s = make_api(tmp_path)
    old = [os.path.join(PROF, "Old", f"x{i}") for i in range(250)]
    a._settings.update({"exclude": old})
    assert len(a._settings.get("exclude")) == 250                     # the old cap of 200 is gone
    ids = _add(s, 1)
    assert a.forget(ids["f0.txt"]) == {"ok": True}
    assert os.path.join(PROF, "Docs", "f0.txt") in a._settings.get("exclude")
    assert s.one("SELECT count(*) FROM files") == 0
    s.close()


def test_forget_with_a_full_list_refuses_and_keeps_the_file(tmp_path):
    a, s = make_api(tmp_path)
    full = [os.path.join(PROF, "Old", f"x{i}") for i in range(settings_mod.MAX_PATHS)]
    a._settings.update({"exclude": full})
    ids = _add(s, 1)
    r = a.forget(ids["f0.txt"])
    assert r["ok"] is False and "full" in r["error"]
    assert a._settings.get("exclude") == full                          # nothing dropped to make room
    assert s.one("SELECT count(*) FROM files") == 1                    # still in the index, as the answer says
    s.close()


def test_forget_that_cannot_save_says_so(tmp_path, monkeypatch):
    a, s = make_api(tmp_path)
    ids = _add(s, 1)

    def broken(changes):
        raise OSError("disk full")
    monkeypatch.setattr(a._settings, "update", broken)
    r = a.forget(ids["f0.txt"])
    assert r["ok"] is False and r["error"]
    assert s.one("SELECT count(*) FROM files") == 1
    s.close()


def test_a_too_long_list_keeps_the_newest_entries():
    paths = [os.path.join(PROF, f"p{i}") for i in range(settings_mod.MAX_PATHS + 10)]
    got = settings_mod.coerce("exclude", paths)
    assert len(got) == settings_mod.MAX_PATHS and got[-1] == paths[-1] and paths[0] not in got


def test_the_turbo_helper_takes_as_many_folders_as_the_settings_keep():
    from nobadfind import ntfs
    assert ntfs.MAX_FOLDERS == settings_mod.MAX_PATHS
    many = [rf"D:\Old\x{i}" for i in range(settings_mod.MAX_PATHS)]
    assert len(ntfs.parse_config({"roots": ["D:\\"], "exclude": many})["exclude"]) == settings_mod.MAX_PATHS


def test_a_long_never_index_list_is_checked_by_folder_level_not_one_by_one():
    from nobadfind import scope
    from nobadfind.walker import Walker
    ex = {scope.norm(rf"D:\Old\x{i}") for i in range(settings_mod.MAX_PATHS)} | {"e:\\"}
    assert scope.holders(scope.norm(r"D:\Old\x7\a.txt"), ex) == [scope.norm(r"D:\Old\x7")]
    assert scope.holders(scope.norm(r"D:\Old\x70a.txt"), ex) == []
    assert scope.holders(r"e:\a\b", ex) == ["e:\\"]
    w = Walker(["D:\\"], exclude=sorted(ex), rules=scope.Rules(others=()))
    assert w.excluded(r"D:\Old\x4999\deep\f.txt") and not w.excluded(r"D:\Old\keep.txt")
    w = Walker([r"D:\Old\x5\inner"], exclude=[r"D:\Old\x5"], rules=scope.Rules(others=()))
    assert not w.excluded(r"D:\Old\x5\inner\f.txt")               # a root inside an excluded folder is walked


