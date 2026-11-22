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


# ---------- L1: deep or odd JSON always gets a JSON-RPC error back ----------
def _methods():
    return {"ping": lambda params, conn: {"ok": True, "n": len(params)}}


def test_the_reviewers_deep_json_gets_an_error_not_a_recursion_error():
    from nobadfind.rpc import protocol
    line = b"[" * 200_000 + b"]" * 200_000                          # 400 KB, under MAX_MESSAGE
    assert len(line) < protocol.MAX_MESSAGE
    r = protocol.handle_line(line, _methods())
    assert r["error"]["code"] == protocol.INVALID_REQUEST and r["id"] is None
    r = protocol.handle_line(b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"a":' + b"[" * 5000 + b"]" * 5000
                             + b"}}", _methods())
    assert r["error"]["code"] == protocol.INVALID_REQUEST


def test_nesting_inside_strings_and_ordinary_requests_still_pass():
    from nobadfind.rpc import protocol
    deep_text = '"' + "[" * 5000 + '\\"{' * 100 + '"'
    line = ('{"jsonrpc":"2.0","id":7,"method":"ping","params":{"text":' + deep_text + ',"f":{"a":[[1]]}}}').encode()
    assert protocol.handle_line(line, _methods()) == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True, "n": 2}}
    ok_depth = b'{"jsonrpc":"2.0","id":2,"method":"ping","params":{"x":' + b"[" * 30 + b"]" * 30 + b"}}"
    assert protocol.handle_line(ok_depth, _methods())["result"]["ok"] is True


def test_a_recursion_error_from_the_parser_is_a_parse_error(monkeypatch):
    from nobadfind.rpc import protocol

    def deep(*a, **k):
        raise RecursionError("maximum recursion depth exceeded")
    monkeypatch.setattr(protocol.json, "loads", deep)
    assert protocol.handle_line(b'{"jsonrpc":"2.0","id":1,"method":"ping"}', _methods())["error"]["code"] == \
        protocol.PARSE_ERROR


# ---------- L3: Windows' own programs by full path, never the search order ----------
def test_system_programs_come_from_windows_own_folders(monkeypatch):
    from nobadfind import winapi
    monkeypatch.setenv("WINDIR", r"C:\Planted")
    monkeypatch.setenv("SystemRoot", r"C:\Planted")
    monkeypatch.setattr(winapi, "windows_dir", lambda: r"C:\Win")
    monkeypatch.setattr(winapi, "system_dir", lambda: r"C:\Win\System32")
    assert winapi.system_exe("explorer.exe") == r"C:\Win\explorer.exe"
    assert winapi.system_exe("cmd.exe") == r"C:\Win\System32\cmd.exe"
    assert winapi.system_exe("taskmgr.exe") == r"C:\Win\System32\taskmgr.exe"
    assert winapi.system_exe("powershell.exe") == r"C:\Win\System32\WindowsPowerShell\v1.0\powershell.exe"
    for bad in ("", r"..\explorer.exe", r"C:\Temp\explorer.exe", "x/explorer.exe", "c:explorer.exe"):
        try:
            winapi.system_exe(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_the_real_folders_are_absolute_and_hold_explorer():
    from nobadfind import winapi
    if not winapi.WIN:
        return
    assert os.path.isfile(winapi.system_exe("explorer.exe"))
    assert os.path.isfile(winapi.system_exe("cmd.exe"))
    assert os.path.isfile(winapi.system_exe("powershell.exe"))


def test_every_launch_uses_a_full_path(tmp_path, monkeypatch):
    """The launcher, the Settings catalog and Open: argv[0] is always absolute; a bare name never starts."""
    from nobadfind import launcher, winapi, wsettings
    ran = []
    L = launcher.Launcher(str(tmp_path), run=ran.append)
    for action in ("set:bluetooth", "set:device-manager", "set:task-manager"):
        assert L.run(action)["ok"], action
    assert wsettings.target("Threat")[0] == winapi.system_exe("explorer.exe")
    assert all(os.path.isabs(argv[0]) for argv in ran), ran
    started = []
    monkeypatch.setattr(winapi.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    try:
        winapi.start_outside_job(["explorer.exe", "x"])
    except OSError:
        pass
    else:
        raise AssertionError("a bare name was started")
    assert started == []
    import inspect
    src = inspect.getsource(launcher._start_apps)
    assert '"powershell.exe"' not in src.replace('_exe("powershell.exe")', "")


# ---------- L7: names in the sentences the engine builds read in their real order ----------
def test_visible_shows_every_direction_control_and_keeps_ordinary_text():
    from nobadfind import display
    assert display.visible("Invoice_\u202efdp.exe") == "Invoice_[U+202E]fdp.exe"
    for c in display.HIDDEN:
        out = display.visible(f"a{chr(c)}b")
        assert out == f"a[U+{c:04X}]b" and display.visible(out) == out
    for s in ("tax 2025.pdf", "बिजली.pdf", "क्\u200dष.txt", "", None, 3):
        assert display.visible(s) == s


def test_the_ui_and_the_engine_hide_the_same_characters():
    import re
    from nobadfind import display
    dart = open(os.path.join(os.path.dirname(__file__), "..", "ui_flutter", "lib", "engine", "models",
                             "safe_text.dart"), encoding="utf-8").read()
    block = dart[dart.index("const hiddenControls"):dart.index("};")]
    assert {int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{4})", block)} == set(display.HIDDEN)


def test_suggestions_place_labels_and_app_actions_show_hidden_characters(tmp_path):
    from nobadfind import launcher, suggest
    from nobadfind.query import parse
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    d = os.path.join(PROF, "Docs\u202e")
    s.upsert_files([(os.path.join(d, "Invoice_\u202efdp.exe"), "Invoice_\u202efdp.exe", d, ".exe", "app", 1, 1.0, 1.0,
                     1)])
    got = [x for x in suggest.suggest(s, "invoi")["items"] if x["kind"] == "file"]
    assert got and got[0]["label"] == "Invoice_[U+202E]fdp.exe" and "[U+202E]" in got[0]["detail"]
    s.close()
    q = parse("report in Docs\u202e")
    assert "\u202e" not in q.place_label()
    L = launcher.Launcher(str(tmp_path), run=lambda argv: None)
    L.apps = [{"id": "app:0:x", "name": "Spot\u202eify", "app_id": "X!App", "version": "", "publisher": "",
               "folder": ""}]
    titles = [a["title"] for a in L.actions("open spot")]
    assert titles and all("\u202e" not in t for t in titles), titles


