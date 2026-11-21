"""0.9.1: Windows settings and apps from the search box; only ids from the table or the Start list are ever run."""
import json

from nobadfind import launcher


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
    assert L.run("set:bluetooth")["ok"] and ran[-1] == ["explorer.exe", "ms-settings:bluetooth"]
    assert L.run("set:device-manager")["ok"] and ran[-1] == ["explorer.exe", "devmgmt.msc"]
    assert L.run("set:task-manager")["ok"] and ran[-1] == ["taskmgr.exe"]
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
