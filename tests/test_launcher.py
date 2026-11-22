"""0.9.1: Windows settings and apps from the search box; only ids from the table or the Start list are ever run."""
import json

from nobadfind import launcher, winapi

EXPLORER = winapi.system_exe("explorer.exe")   # by full path (review L3)


def make(tmp_path):
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv: ran.append(argv))
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
    monkeypatch.setattr(launcher, "_installed_info", lambda: {"brave": {"version": "1.2", "publisher": "Brave",
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
