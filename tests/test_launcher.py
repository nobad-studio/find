"""0.9.1: Windows settings and apps from the search box; only ids from the table or the Start list are ever run."""
import json

from nobadfind import launcher, winapi

EXPLORER = winapi.system_exe("explorer.exe")   # by full path (review L3)


def make(tmp_path):
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: ran.append(argv))
    L.apps = [{"id": "app:0:google-chrome", "name": "Google Chrome", "app_id": "Chrome", "version": "131.0",
               "publisher": "Google LLC", "folder": r"C:\Program Files\Google\Chrome\Application"},
              {"id": "app:1:spotify", "name": "Spotify", "app_id": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
               "version": "", "publisher": "", "folder": ""},
              {"id": "app:2:uninstall-node-js", "name": "Uninstall Node.js", "app_id": "x", "version": "",
               "publisher": "", "folder": ""}]
    return L, ran


def titles(L, q):
    return [a["title"] for a in L.actions(q)]


def test_settings_pages_by_the_words_people_use(tmp_path):
    L, _ = make(tmp_path)
    assert titles(L, "open bluetooth")[0] == "Bluetooth & devices"
    assert titles(L, "blutooth")[0] == "Bluetooth & devices"                # a typo
    assert titles(L, "turn off wifi")[0] == "Wi-Fi"
    assert titles(L, "brightness")[0] == "Display"
    assert titles(L, "dark mode")[0] == "Colors"
    assert titles(L, "uninstall")[0] == "Installed apps"                    # not an uninstaller shortcut
    assert titles(L, "device manager")[0] == "Device Manager"


def test_apps_by_name_with_their_details(tmp_path):
    L, _ = make(tmp_path)
    a = L.actions("open chrome")[0]
    assert a["title"] == "Google Chrome" and a["kind"] == "app"
    assert "Google LLC" in a["subtitle"] and "131.0" in a["subtitle"] and "Chrome\\Application" in a["subtitle"]
    assert titles(L, "spotify") == ["Spotify"]


def test_file_questions_offer_nothing(tmp_path):
    L, _ = make(tmp_path)
    for q in ("tax pdf", "invoice march", "budget.xlsx", "a83kd92Qz7", ""):
        assert L.actions(q) == [], q


def test_only_known_ids_run(tmp_path):
    L, ran = make(tmp_path)
    assert L.run("set:bluetooth")["ok"] and ran[-1] == [EXPLORER, "ms-settings:bluetooth"]
    assert L.run("set:device-manager")["ok"] and ran[-1] == [EXPLORER, "devmgmt.msc"]
    assert L.run("set:task-manager")["ok"] and ran[-1] == [winapi.system_exe("taskmgr.exe")]
    assert L.run("app:1:spotify")["ok"] and ran[-1][1].startswith("shell:AppsFolder\\SpotifyAB.")
    n = len(ran)
    for bad in ("C:\\Windows\\evil.exe", "set:nope", "app:9:gone", "ms-settings:bluetooth", "x" * 300, None):
        assert L.run(bad)["ok"] is False
    assert len(ran) == n                                                     # nothing else was started


def test_the_app_list_is_saved_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_start_apps", lambda: [("Brave", "Brave"), ("Calculator", "Microsoft.Calc!App")])
    monkeypatch.setattr(launcher, "_registry_apps", lambda: ([], {}))
    monkeypatch.setattr(launcher, "_installed_info", lambda *a: {"brave": {"version": "1.2", "publisher": "Brave",
                                                                          "folder": "C:\\Brave"}})
    L = launcher.Launcher(str(tmp_path), run=lambda a: None)
    L.refresh()
    saved = json.loads((tmp_path / "apps.json").read_text(encoding="utf-8"))
    assert [a["name"] for a in saved["apps"]] == ["Brave", "Calculator"]
    monkeypatch.setattr(launcher.wsettings, "load", lambda *a, **k: [])
    again = launcher.Launcher(str(tmp_path), run=lambda a: None)
    assert [a["name"] for a in again.apps] == ["Brave", "Calculator"] and again.apps[0]["version"] == "1.2"
    assert again.refresh_in_background() is True                             # the settings catalog, once
    again._busy.join(5)
    assert again.refresh_in_background() is False                            # fresh: not again for hours


def test_api_search_carries_the_actions(tmp_path):
    from nobadfind import api as api_mod, settings
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings.Settings(str(tmp_path / "s.json"))
    ix = type("Ix", (), {"embedder": None, "photo_text": None, "pindex": None, "drive_list": [],
                         "roots": lambda self, d: []})()
    a = api_mod.Api(s, st, ix, None)
    L, ran = make(tmp_path)
    a._launcher = L
    r = a.search("open bluetooth")
    assert r["actions"][0]["id"] == "set:bluetooth"
    assert a.run_action("set:bluetooth")["ok"] and ran
    assert "actions" not in a.search("tax pdf")
    s.close()


def test_a_question_naming_an_entry_exactly_wins(tmp_path):
    """0.9.5, from the reference PC: "windows" and "app" are filler words, so these used to pick a near miss."""
    L, _ = make(tmp_path)
    assert titles(L, "open windows update")[0] == "Windows Update"           # was Update history
    assert titles(L, "open settings app")[0] == "Settings"                   # was Advanced app settings


def _api(tmp_path, embedder=None, vindex=None):
    from nobadfind import api as api_mod, settings
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings.Settings(str(tmp_path / "s.json"))
    ix = type("Ix", (), {"embedder": embedder, "photo_text": None, "pindex": None, "drive_list": [],
                         "roots": lambda self, d: []})()
    a = api_mod.Api(s, st, ix, vindex)
    L, ran = make(tmp_path)
    a._launcher = L
    return a, s, ran


def test_the_pipe_answer_carries_the_actions_and_opens_the_page(tmp_path):
    """0.9.6, from the maintainer: "open windows update" opened Settings on its home page. The pipe's search answer
    dropped "actions", so the window never had the page to open and Enter opened the first file instead."""
    from nobadfind.rpc import handlers, protocol
    a, s, ran = _api(tmp_path)
    m = handlers.methods(a)

    def call(method, params):
        return protocol.handle_line(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}), m)

    r = call("search", {"text": "open windows update", "channel": "bar"})["result"]
    assert r["actions"][0] == {"id": "set:windows-update", "kind": "setting", "title": "Windows Update",
                               "subtitle": "Windows Settings"}
    assert call("run_action", {"id": r["actions"][0]["id"]})["result"]["ok"] is True
    assert ran == [[EXPLORER, "ms-settings:windowsupdate"]]           # the page, not Settings home
    assert "actions" not in call("search", {"text": "tax pdf"})["result"]
    s.close()


def test_the_pipe_answer_carries_the_needs_and_only_known_fields():
    from nobadfind.rpc.handlers.search import _search_result
    need = {"model": "meaning", "state": "off", "id": "gte-small", "size_mb": 30, "done": 0, "total": 0,
            "text": "Search by meaning is off."}
    act = {"id": "set:bluetooth", "kind": "setting", "title": "Bluetooth & devices", "subtitle": "Windows Settings"}
    out = _search_result({"results": [], "needs": [dict(need, extra=1)], "actions": [dict(act, path="C:\\x")]})
    assert out["needs"] == [need] and out["actions"] == [act]
    out = _search_result({"results": [], "actions": [{"id": "x" * 300, "kind": "setting", "title": "t"},
                                                     {"id": "set:x", "kind": "evil", "title": "t"}, "nope"]})
    assert "actions" not in out                                              # nothing the schema doesn't allow


DOCUMENTED = set("""
bluetooth connecteddevices printers mousetouchpad devices-touchpad pen autoplay usb camera network-wifi
network-status network-ethernet network-vpn network-proxy network-mobilehotspot network-airplanemode display
nightlight sound sound-devices notifications quiethours powersleep batterysaver storagesense multitasking clipboard
remotedesktop project about activation troubleshoot recovery windowsupdate windowsupdate-history
personalization-background colors themes lockscreen personalization-start taskbar fonts appsfeatures defaultapps
startupapps optionalfeatures maps yourinfo signinoptions emailandaccounts otherusers backup dateandtime
regionlanguage typing speech gaming-gamebar gaming-gamemode display-advancedgraphics easeofaccess-narrator
easeofaccess-magnifier easeofaccess-display easeofaccess-highcontrast privacy privacy-location privacy-microphone
privacy-webcam findmydevice developers
""".split())
# Microsoft's ms-settings: list (learn.microsoft.com, "Launch Windows Settings", 2026-11-02) has no row for these
# two (Data usage, the Accessibility page); kept as they were, not checked on a PC here.
UNLISTED = {"datausage", "easeofaccess"}


def test_every_settings_page_is_on_microsofts_list():
    for sid, _title, target, _w in launcher.SETTINGS:
        if target.startswith("ms-settings:") and target != "ms-settings:":
            page = target[len("ms-settings:"):]
            assert page in DOCUMENTED | UNLISTED, sid
    assert launcher.SETTINGS_BY_ID["set:network"][2] == "ms-settings:network-status"    # was ms-settings:network


def test_typos_in_the_question_still_find_the_page(tmp_path):
    L, ran = make(tmp_path)
    assert titles(L, "launch contrl pannle")[0] == "Control Panel"
    assert titles(L, "opn windws update")[0] == "Windows Update"
    assert titles(L, "opn task managr")[0] == "Task Manager"
    assert titles(L, "open blutooth setings")[0] == "Bluetooth & devices"
    assert L.wants("opn windws update") and L.wants("lanch contrl pannle") and not L.wants("pen tablet")
    assert L.run(L.actions("opn windws update")[0]["id"])["ok"]
    assert ran == [[EXPLORER, "ms-settings:windowsupdate"]]
    for q in ("tax pdf", "invoice march", "a83kd92Qz7"):                    # files are still not settings
        assert L.actions(q) == [], q


def test_matching_is_fast_with_the_whole_windows_catalog(tmp_path):
    import time
    L, _ = make(tmp_path)
    L.catalog = launcher.Catalog([{"id": f"ws:{n}", "title": f"Setting number {n} for item{n % 97}",
                                   "words": f"word{n % 131};thing{n % 59} other", "uri": "ms-settings:display"}
                                  for n in range(1800)])
    qs = ["open windows update", "launch contrl pannle", "opn windws update", "open blutooth", "tax pdf"]
    L.actions(qs[0])
    t = time.perf_counter()
    for _ in range(5):
        for q in qs:
            L.actions(q)
    each = (time.perf_counter() - t) / (5 * len(qs))
    assert each < 0.05, f"{each * 1000:.1f} ms per question"


def test_a_launch_question_doesnt_wait_for_meaning_search(tmp_path):
    """Enter on "open windows update" waits for this answer: the meaning model (seconds on a big index) only runs
    for questions that aren't opening a page or an app."""
    asked = []

    class Emb:
        model_id = "m"

        def encode(self, texts):
            asked.extend(texts)
            return [[0.0]]

    class Vix:
        model, n = "m", 1

        def search(self, v, k=10):
            return []
    a, s, _ran = _api(tmp_path, Emb(), Vix())
    assert a.search("open windows update")["actions"][0]["id"] == "set:windows-update"
    assert asked == []
    a.search("tax report from the bank")
    assert asked                                                             # other questions still use meaning
    s.close()


# ---------- Find 1.2: apps listed only in the registry ----------
PF = r"C:\Program Files"


def reg_entry(name, location="", icon=""):
    return {"name": name, "version": "1.0", "publisher": "Acme", "location": location, "icon": icon}


def fake_files(*present):
    have = set(present)                              # exact: case differences must matter
    return lambda p: p in have


def registry_only(monkeypatch, entries, app_paths, is_file, start=()):
    monkeypatch.setattr(launcher, "_start_apps", lambda: list(start))
    monkeypatch.setattr(launcher, "_installed_info", lambda *a: {})
    monkeypatch.setattr(launcher, "_registry_apps", lambda: (entries, app_paths))
    monkeypatch.setattr(launcher, "_is_file", is_file)
    monkeypatch.setattr(launcher, "_program_roots", lambda: [PF])


def test_registry_app_opens_by_install_location_and_icon(tmp_path, monkeypatch):
    exe = PF + r"\Acme\acme.exe"
    registry_only(monkeypatch, [reg_entry("Acme Tool", PF + r"\Acme", exe + ",0")], {}, fake_files(exe))
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: ran.append(argv))
    L.refresh()
    assert [a["name"] for a in L.apps] == ["Acme Tool"]
    assert L.run(L.apps[0]["id"])["ok"] is True
    assert ran == [[exe]]                            # an argument list: the program itself, no shell string


def test_registry_app_opens_by_app_paths(tmp_path, monkeypatch):
    exe = r"D:\Zed\zed.exe"
    registry_only(monkeypatch, [reg_entry("Zed", r"D:\Zed")], {"zed.exe": exe}, fake_files(exe))
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: ran.append(argv))
    L.refresh()
    assert L.run(L.apps[0]["id"])["ok"] and ran == [[exe]]


def test_registry_app_already_in_start_list_is_not_doubled(tmp_path, monkeypatch):
    exe = PF + r"\Acme\acme.exe"
    registry_only(monkeypatch, [reg_entry("Acme Tool", PF + r"\Acme", exe)], {}, fake_files(exe),
                  start=[("Acme Tool", "AcmeId")])
    L = launcher.Launcher(str(tmp_path), run=lambda a: None)
    L.refresh()
    assert [a["name"] for a in L.apps] == ["Acme Tool"] and "exe" not in L.apps[0]


def test_registry_app_with_bad_path_is_not_offered(tmp_path, monkeypatch):
    good = r"D:\Apps\Acme"
    cases = {
        "missing": (good, good + r"\acme.exe", False),
        "notexe": (good, good + r"\acme.bat", True),
        "outside": (good, r"C:\Users\x\evil.exe", True),
        "uninstaller": (good, good + r"\unins000.exe", True),
        "setup": (good, good + r"\AcmeSetup.exe", True),
        "updater": (good, good + r"\update.exe", True),
        "relative": ("", "acme.exe", True),
        "dotdot": (good, good + r"\..\..\evil.exe", True),
    }
    for label, (folder, exe, exists) in cases.items():
        registry_only(monkeypatch, [reg_entry("Acme", folder, exe)], {}, lambda p, ex=exists: ex)
        (tmp_path / label).mkdir()
        L = launcher.Launcher(str(tmp_path / label), run=lambda a: None)
        L.refresh()
        assert L.apps == [], label


def test_a_stored_registry_app_is_checked_again_when_run(tmp_path, monkeypatch):
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: ran.append(argv))
    L.apps = [{"id": "app:0:acme", "name": "Acme", "exe": r"D:\Acme\acme.exe", "folder": r"D:\Acme",
               "version": "", "publisher": ""}]
    monkeypatch.setattr(launcher, "_is_file", lambda p: True)
    monkeypatch.setattr(launcher, "_program_roots", lambda: [PF])
    assert L.run("app:0:acme")["ok"] is True
    L.apps[0]["exe"] = r"D:\Acme\unins000.exe"
    assert L.run("app:0:acme")["ok"] is False and len(ran) == 1


# ---------- fix round 1 ----------
def one(tmp_path, monkeypatch, entries, app_paths, is_file):
    registry_only(monkeypatch, entries, app_paths, is_file)
    L = launcher.Launcher(str(tmp_path), run=lambda a, **k: None)
    L.refresh()
    return L.apps


def test_registry_values_with_variables_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("NF_TEST_PF", PF)
    assert launcher._expand_value("%NF_TEST_PF%\\Foo\\foo.exe,0", 2) == PF + r"\Foo\foo.exe,0"
    assert launcher._expand_value("%NF_TEST_PF%\\x", 1) == "%NF_TEST_PF%\\x"      # REG_SZ stays as it is
    exe = PF + r"\Foo\foo.exe"
    apps = one(tmp_path, monkeypatch, [reg_entry("Foo", "", launcher._expand_value("%NF_TEST_PF%\\Foo\\foo.exe,0", 2))],
               {}, fake_files(exe))
    assert [a["exe"] for a in apps] == [exe]


def test_icon_path_forms():
    assert launcher._icon_path(r'"C:\A B\a.exe",0') == r"C:\A B\a.exe"
    assert launcher._icon_path(r'"C:\A B\a.exe"') == r"C:\A B\a.exe"
    assert launcher._icon_path(r"C:\A\a.exe,-12") == r"C:\A\a.exe"
    assert launcher._icon_path(r"C:\A\a.exe") == r"C:\A\a.exe"
    assert launcher._icon_path("") == ""


def test_quoted_icon_with_index_opens(tmp_path, monkeypatch):
    exe = PF + r"\Q R\q.exe"
    apps = one(tmp_path, monkeypatch, [reg_entry("Q R", "", '"' + exe + '",0')], {}, fake_files(exe))
    assert [a["exe"] for a in apps] == [exe]


def test_install_location_and_app_paths_in_the_same_folder(tmp_path, monkeypatch):
    exe = r"D:\Zed\bin\zed.exe"
    apps = one(tmp_path, monkeypatch, [reg_entry("Totally Different Name", r"D:\Zed\bin")],
               {"zed.exe": exe}, fake_files(exe))
    assert [a["exe"] for a in apps] == [exe]


def test_app_paths_shared_folder_is_not_guessed(tmp_path, monkeypatch):
    paths = {"a.exe": r"D:\Suite\a.exe", "b.exe": r"D:\Suite\b.exe"}
    ok = fake_files(*paths.values())
    assert one(tmp_path, monkeypatch, [reg_entry("Suite Tool", r"D:\Suite")], paths, ok) == []
    # the exe's own name matching the app's name is unambiguous
    (tmp_path / "n").mkdir()
    apps = one(tmp_path / "n", monkeypatch, [reg_entry("A", r"D:\Suite")], paths, ok)
    assert [a["exe"] for a in apps] == [r"D:\Suite\a.exe"]


def test_app_paths_pointing_at_a_non_exe_is_not_offered(tmp_path, monkeypatch):
    bat = r"D:\Zed\zed.bat"
    assert one(tmp_path, monkeypatch, [reg_entry("Zed", r"D:\Zed")], {"zed.exe": bat}, fake_files(bat)) == []


def test_program_files_prefix_trick_is_refused(tmp_path, monkeypatch):
    exe = r"C:\Program FilesX\evil\evil.exe"
    assert one(tmp_path, monkeypatch, [reg_entry("Evil", "", exe)], {}, fake_files(exe)) == []


def test_case_differences_are_the_same_folder(tmp_path, monkeypatch):
    exe = r"d:\apps\ACME\Acme.EXE"
    apps = one(tmp_path, monkeypatch, [reg_entry("Acme", r"D:\APPS\acme", exe)], {}, fake_files(r"d:\apps\ACME\Acme.EXE"))
    assert [a["exe"] for a in apps] == [exe]
    (tmp_path / "m").mkdir()
    assert one(tmp_path / "m", monkeypatch, [reg_entry("Acme", r"D:\apps\acme", exe)], {}, fake_files(exe.lower())) == []


def test_uninstall_exe_is_refused(tmp_path, monkeypatch):
    exe = PF + r"\Acme\uninstall.exe"
    assert one(tmp_path, monkeypatch, [reg_entry("Acme", PF + r"\Acme", exe)], {}, fake_files(exe)) == []


def test_network_paths_are_never_looked_up(tmp_path, monkeypatch):
    asked = []
    for i, (folder, exe) in enumerate([(r"\\srv\share\Acme", r"\\srv\share\Acme\a.exe"),
                                       (r"D:\Acme", r"\\srv\share\a.exe"), ("", r"\\?\C:\Program Files\a.exe")]):
        (tmp_path / str(i)).mkdir()
        apps = one(tmp_path / str(i), monkeypatch, [reg_entry("Acme", folder, exe)], {},
                   lambda p: asked.append(p) or True)
        assert apps == []
    assert asked == []


def test_system_components_and_updates_are_not_apps(tmp_path, monkeypatch):
    exe = PF + r"\Acme\acme.exe"
    for i, extra in enumerate([{"system": True}, {"parent": "Acme Suite"}, {"release": "Update"},
                               {"release": "Hotfix"}, {"release": "Security Update"}]):
        (tmp_path / str(i)).mkdir()
        e = dict(reg_entry("Acme", PF + r"\Acme", exe), **extra)
        assert one(tmp_path / str(i), monkeypatch, [e], {}, fake_files(exe)) == [], extra
    (tmp_path / "ok").mkdir()
    e = dict(reg_entry("Acme", PF + r"\Acme", exe), system=False, parent="", release="Application")
    assert len(one(tmp_path / "ok", monkeypatch, [e], {}, fake_files(exe))) == 1


def test_a_registry_app_starts_in_its_own_folder(tmp_path, monkeypatch):
    calls = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv, **k: calls.append((argv, k)))
    L.apps = [{"id": "app:0:acme", "name": "Acme", "exe": r"D:\Acme\acme.exe", "folder": r"D:\Acme",
               "version": "", "publisher": ""}]
    monkeypatch.setattr(launcher, "_is_file", lambda p: True)
    assert L.run("app:0:acme")["ok"]
    assert calls == [([r"D:\Acme\acme.exe"], {"cwd": r"D:\Acme"})]


def test_the_registry_is_read_once_per_refresh(tmp_path, monkeypatch):
    n = []
    monkeypatch.setattr(launcher, "_start_apps", lambda: [])
    monkeypatch.setattr(launcher, "_registry_apps", lambda: n.append(1) or ([], {}))
    launcher.Launcher(str(tmp_path), run=lambda a: None).refresh()
    assert len(n) == 1
