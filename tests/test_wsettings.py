"""0.9.1: every setting in Windows' own Settings search catalog, opened only through the allowlisted forms."""
import os

from nobadfind import launcher, wsettings

XML = """<?xml version="1.0" encoding="utf-8"?>
<PCSettings>
  <SearchableContent>
    <Filename>AAA_Battery_Percentage</Filename>
    <SettingIdentity><SettingPaths><Path><PageID>SettingsPagePowerAndBattery</PageID>
      <PolicyIds>batterysaver;powersleep</PolicyIds></Path></SettingPaths></SettingIdentity>
    <SettingInformation><Description>@res:Battery percentage</Description>
      <HighKeywords>@res:battery level;show battery</HighKeywords></SettingInformation>
  </SearchableContent>
  <SearchableContent IncludeWithFeature="X">
    <Filename>AAA_Battery_Percentage-2</Filename>
    <SettingIdentity><SettingPaths><Path><PageID>SettingsPagePowerAndBattery</PageID>
      <PolicyIds>batterysaver;powersleep</PolicyIds></Path></SettingPaths></SettingIdentity>
    <SettingInformation><Description>@res:Battery percentage</Description></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>AAA_New_Page</Filename>
    <SettingIdentity><SettingPaths><Path><PageID>SettingsPageBrandNew</PageID>
      <PolicyIds>brand-new;brand-new-advanced</PolicyIds></Path></SettingPaths></SettingIdentity>
    <SettingInformation><Description>Holographic widgets</Description></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>AAA_Unknown_Page</Filename>
    <SettingIdentity><SettingPaths><Path><Node Type="Page">SettingsPageNobodyKnows</Node></Path></SettingPaths>
    </SettingIdentity>
    <SettingInformation><Description>Lost setting</Description></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>Classic_EnvVars</Filename>
    <ApplicationInformation><DeepLink>%windir%\\system32\\rundll32.exe sysdm.cpl,EditEnvironmentVariables</DeepLink>
    </ApplicationInformation>
    <SettingInformation><Description>@shell32.dll,-1</Description>
      <Keywords>@@shell32.dll,-2@shell32.dll,-3</Keywords></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>Classic_System</Filename>
    <ApplicationInformation><DeepLink>Microsoft.PowerOptions\\pagePlanSettings</DeepLink></ApplicationInformation>
    <SettingInformation><Description>Change power plan</Description></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>Classic_Troubleshooter</Filename>
    <ApplicationInformation><DeepLink>%windir%\\system32\\msdt.exe -id AudioPlaybackDiagnostic</DeepLink>
    </ApplicationInformation>
    <SettingInformation><Description>Find and fix audio problems</Description></SettingInformation>
  </SearchableContent>
  <SearchableContent>
    <Filename>Classic_Elsewhere</Filename>
    <ApplicationInformation><DeepLink>C:\\Users\\me\\evil.exe</DeepLink></ApplicationInformation>
    <SettingInformation><Description>Something else</Description></SettingInformation>
  </SearchableContent>
</PCSettings>
"""
STRINGS = {"@shell32.dll,-1": "Edit the system environment variables", "@shell32.dll,-2": "path",
           "@shell32.dll,-3": "environment"}


def resolve(s):
    return s[len("@res:"):] if s.startswith("@res:") else STRINGS.get(s, "")


def catalog(tmp_path):
    f = tmp_path / "AllSystemSettings_{TEST}.xml"
    f.write_text(XML, encoding="utf-8")
    return [str(f)]


def test_the_catalog_is_read_in_the_users_words(tmp_path):
    items = {i["title"]: i for i in wsettings.parse(catalog(tmp_path), resolve)}
    assert items["Battery percentage"]["uri"] == "ms-settings:powersleep"      # the fallback table's page
    assert "battery level" in items["Battery percentage"]["words"]
    assert items["Holographic widgets"]["uri"] == "ms-settings:brand-new"      # learned from the policy ids
    assert items["Edit the system environment variables"]["words"] == "path;environment"
    assert "Lost setting" not in items                                         # no page we know: left out
    assert "Find and fix audio problems" not in items                          # retired troubleshooters
    assert "Something else" not in items                                       # not a System32 program
    assert len([i for i in wsettings.parse(catalog(tmp_path), resolve) if i["title"] == "Battery percentage"]) == 1


def test_deep_links_become_fixed_argument_lists():
    s32 = wsettings.system32()
    assert wsettings.target("Microsoft.PowerOptions\\pagePlanSettings") == [
        os.path.join(s32, "control.exe"), "/name", "Microsoft.PowerOptions", "/page", "pagePlanSettings"]
    assert wsettings.target("%windir%\\system32\\rundll32.exe sysdm.cpl,EditEnvironmentVariables") == [
        os.path.join(s32, "rundll32.exe"), "sysdm.cpl,EditEnvironmentVariables"]
    assert wsettings.target("%windir%\\system32\\mmc.exe %windir%\\system32\\diskmgmt.msc")[1].endswith("diskmgmt.msc")
    assert wsettings.target("Threat") == ["explorer.exe", "windowsdefender://threat"]
    for bad in ("%windir%\\system32\\cmd.exe /c del x", "%windir%\\system32\\mmc.exe C:\\Users\\me\\x.msc",
                "%windir%\\system32\\rundll32.exe a.dll,B & calc", "C:\\Temp\\control.exe", "Microsoft.X; calc",
                "ms-contact-support://?x=1", "", None):
        assert wsettings.target(bad) is None, bad


def test_it_is_cached_until_windows_changes_it(tmp_path):
    files = catalog(tmp_path)
    calls = []

    def counting(s):
        calls.append(s)
        return resolve(s)
    a = wsettings.load(str(tmp_path), files, counting)
    n = len(calls)
    b = wsettings.load(str(tmp_path), files, counting)
    assert a == b and len(calls) == n                                          # from wsettings.json
    os.utime(files[0], (1, 1))
    wsettings.load(str(tmp_path), files, counting)
    assert len(calls) > n                                                      # Windows changed it: read again


def test_search_box_finds_and_opens_catalog_settings(tmp_path):
    ran = []
    L = launcher.Launcher(str(tmp_path), run=lambda argv: ran.append(argv))
    L.read_catalog(catalog(tmp_path), resolve)
    a = L.actions("environment variables")[0]
    assert a["title"] == "Edit the system environment variables" and a["subtitle"] == "Control Panel"
    assert L.run(a["id"])["ok"] and ran[-1][0].lower().endswith("rundll32.exe")
    b = L.actions("battery percentage")[0]
    assert b["title"] == "Battery percentage" and b["subtitle"] == "Windows Settings"
    assert L.run(b["id"])["ok"] and ran[-1] == ["explorer.exe", "ms-settings:powersleep"]
    assert L.actions("open bluetooth")[0]["title"] == "Bluetooth & devices"   # the usual name still first
    assert L.actions("tax pdf") == []
    n = len(ran)
    assert L.run("ws:Classic_Troubleshooter")["ok"] is False and L.run("ws:nope")["ok"] is False
    assert len(ran) == n
