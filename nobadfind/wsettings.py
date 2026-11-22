"""Every setting Windows' own Settings search knows (0.9.1): "show battery percentage", "edit environment
variables", "turn off location", "create a restore point".

Windows keeps the catalog its Settings search uses in C:\\Windows\\ImmersiveControlPanel\\Settings\\
AllSystemSettings_*.xml: about 1,750 settings on Windows 11, each with its name and the words people use, in
the user's display language (resolved here with SHLoadIndirectString), for the Windows version that is
installed. It is a fixed system file, not a record of anything the user did. Read in the background, kept in
<data>/wsettings.json until Windows changes it.

- A Settings setting opens its Settings page (ms-settings:<page>; the page comes from the catalog's own policy
  ids, or the fallback table below).
- A Control Panel setting opens its Control Panel item (control.exe /name Microsoft.X [/page Y]), its
  shell:::{CLSID} folder, its Windows Security page, or its program in System32, from an allowlist: the program
  must be one of _PROGRAMS, in the real System32, with plain arguments. Retired troubleshooters (msdt) are left out.
- Running is by catalog id only (`ws:<Filename>`), checked again against those rules at run time.
"""
import ctypes
import glob
import json
import os
import re
import time
import xml.etree.ElementTree as ET

from .log import log

CATALOG_GLOB = r"ImmersiveControlPanel\Settings\AllSystemSettings_*.xml"

# Settings page id (without "SettingsPage") -> ms-settings name, for catalogs that don't carry policy ids.
# Learned from Windows 11 26300's own catalog.
PAGES = {
    "A9": "a9", "AIComponents": "aicomponents", "About": "about", "AccountsEmailApp": "emailandaccounts",
    "AccountsPicture": "yourinfo", "AccountsSync": "sync", "Activate": "activation",
    "AdvancedApps": "advanced-apps", "AppActions": "appactions", "AppBrowserProtection": "apps-appbrowserprotection",
    "AppsDefaults": "defaultapps", "AppsForWebsites": "appsforwebsites", "AppsNotifications": "notifications",
    "Audio": "sound", "Background": "personalization-background", "C2D": "clicktodo", "Clipboard": "clipboard",
    "CloudPC": "privacy-cloudpc", "Colors": "colors", "Continuum": "project", "DeviceEncryption": "deviceencryption",
    "Devices": "bluetooth", "DevicesCameras": "camera", "DevicesDL": "personalization-lighting",
    "DevicesKeyboard": "devices-keyboard", "DevicesMobileDevices": "mobile-devices", "DevicesPen": "pen",
    "DevicesPrinters": "printers", "DevicesTouch": "devices-touch", "DevicesTouchpad": "devices-touchpad",
    "EaseOfAccessAudio": "easeofaccess-audio", "EaseOfAccessClosedCaptioning": "easeofaccess-closedcaptioning",
    "EaseOfAccessColorFilter": "easeofaccess-colorfilter", "EaseOfAccessEyeGaze": "easeofaccess-eyecontrol",
    "EaseOfAccessHearingAids": "easeofaccess-hearingaids", "EaseOfAccessHighContrast": "easeofaccess-highcontrast",
    "EaseOfAccessKeyboard": "easeofaccess-keyboard", "EaseOfAccessMagnifier": "easeofaccess-magnifier",
    "EaseOfAccessMouse": "easeofaccess-mouse", "EaseOfAccessMousePointer": "easeofaccess-mousepointer",
    "EaseOfAccessNarrator": "easeofaccess-narrator", "EaseOfAccessNarratorNS": "easeofaccess-narrator",
    "EaseOfAccessScreenTint": "easeofaccess-screentint",
    "EaseOfAccessSpeechRecognition": "easeofaccess-speechrecognition",
    "EaseOfAccessTextCursor": "easeofaccess-cursor", "EaseOfAccessTextSize": "easeofaccess-display",
    "EaseOfAccessVisualEffects": "easeofaccess-visualeffects", "FindMyDevice": "findmydevice", "Focus": "quiethours",
    "Fonts": "fonts", "GameBar": "gaming-gamebar", "GameDVR": "gaming-gamedvr", "GameMode": "gaming-gamemode",
    "GamingPosture": "gaming-fullscreen", "InstalledApps": "appsfeatures", "LockScreen": "lockscreen",
    "Maps": "maps", "MultiTasking": "multitasking", "NetworkAirplaneMode": "network-airplanemode",
    "NetworkDialup": "network-dialup", "NetworkDirectAccess": "network-directaccess",
    "NetworkEthernet": "network-ethernet", "NetworkFirewall": "network-firewall",
    "NetworkManageAdapterOptions": "network-advancedsettings", "NetworkMobileBroadband": "network-cellular",
    "NetworkMobileHotspot": "network-mobilehotspot", "NetworkProxy": "network-proxy", "NetworkVPN": "network-vpn",
    "NetworkWiFi": "network-wifi", "OptionalFeatures": "optionalfeatures", "OtherUsers": "otherusers",
    "PCSystemAutoPlay": "autoplay", "PCSystemDeviceSettings": "mousetouchpad", "PCSystemDisplay": "display",
    "PasskeysManagement": "savedpasskeys", "PersonalizationTextInput": "personalization-textinput",
    "PersonalizeCopilot": "personalization-copilot", "PowerAndBattery": "powersleep",
    "PrivacyAccountInfo": "privacy-accountinfo", "PrivacyActivityHistory": "privacy-activityhistory",
    "PrivacyAgentTools": "privacy-agenttools", "PrivacyAppDiagnostics": "privacy-appdiagnostics",
    "PrivacyAppRequestedDownloads": "privacy-automaticfiledownloads",
    "PrivacyBackgroundApps": "privacy-backgroundapps",
    "PrivacyBroadFileSystemAccess": "privacy-broadfilesystemaccess", "PrivacyCalendar": "privacy-calendar",
    "PrivacyCallHistory": "privacy-callhistory", "PrivacyContacts": "privacy-contacts",
    "PrivacyCustomPeripherals": "privacy-customdevices", "PrivacyDocuments": "privacy-documents",
    "PrivacyDownloadsFolder": "privacy-downloadsfolder", "PrivacyEmail": "privacy-email",
    "PrivacyForegroundTextAccess": "privacy-foregroundtextaccess", "PrivacyGaze": "privacy-eyetracker",
    "PrivacyGeneral": "privacy-general", "PrivacyGraphicsCaptureProgrammatic": "privacy-graphicscaptureprogrammatic",
    "PrivacyGraphicsCaptureWithoutBorder": "privacy-graphicscapturewithoutborder",
    "PrivacyHumanPresence": "privacy-presencesensing", "PrivacyLocation": "privacy-location",
    "PrivacyMessaging": "privacy-messaging", "PrivacyMicrophone": "privacy-microphone",
    "PrivacyMotionData": "privacy-motion", "PrivacyMusicLibrary": "privacy-musiclibrary",
    "PrivacyNotifications": "privacy-notifications", "PrivacyPasskeys": "privacy-passkeys",
    "PrivacyPersonalization": "privacy-speechtyping", "PrivacyPhoneCall": "privacy-phonecalls",
    "PrivacyPictures": "privacy-pictures", "PrivacyRadios": "privacy-radios",
    "PrivacySIUFSettings": "privacy-feedback", "PrivacySpeech": "privacy-speech",
    "PrivacySystemAIModels": "privacy-systemaimodels", "PrivacyTasks": "privacy-tasks",
    "PrivacyVideos": "privacy-videos", "PrivacyVoiceActivation": "privacy-voiceactivation",
    "PrivacyWebcam": "privacy-webcam", "RadialController": "wheel", "RationalizedSearchSettings": "search",
    "RemoteDesktop": "remotedesktop", "RestoreMusUpdate": "windowsupdate", "RestoreRestore": "recovery",
    "Resume": "system-resume", "SearchIndex": "search", "SearchPermissionsAndHistory": "search-permissions",
    "SecurityBaselineCheck": "security-baseline", "SecurityDeviceProtection": "security-deviceprotection",
    "SecurityVirusThreat": "security-virusandthreatprotection", "SharedExperiences": "crossdevice",
    "SignInOptions": "signinoptions", "Speech": "speech", "Start": "personalization-start", "Start2":
    "personalization-start", "Startup": "startupapps", "StorageSenseStorageOverview": "storagesense",
    "SystemComponents": "systemcomponents", "Taskbar": "taskbar", "Themes": "themes",
    "TimeRegionDateTime": "dateandtime", "TimeRegionKeyboard": "keyboard", "TimeRegionLanguage": "regionlanguage",
    "TimeRegionSpelling": "typing", "Troubleshoot": "troubleshoot", "Usb": "usb", "UserIntent": "deviceusage",
    "Video": "videoplayback", "WindowsDefender": "windowsdefender", "WorkAccess": "workplace",
    "YourFamilyGroup": "family-group",
}
# Windows Security pages named in the catalog -> its own links (the rest open Windows Security's home)
DEFENDER = {"Threat": "windowsdefender://threat", "ThreatSettings": "windowsdefender://threatsettings",
            "AccountProtection": "windowsdefender://account", "Network": "windowsdefender://network",
            "AppBrowser": "windowsdefender://appbrowser", "DeviceSecurity": "windowsdefender://devicesecurity",
            "PerfHealth": "windowsdefender://perfhealth", "Family": "windowsdefender://family"}
DEFENDER_OTHER = {"AllowAppThroughFolder", "CoreIsolation", "DataEncryption", "ExploitProtection",
                  "ProtectedFolders", "RansomwareProtection", "SecurityProcessor",
                  "SecurityProcessorTroubleshooting", "SmartApp", "SmartScreenPua"}
# Programs in System32 a Control Panel setting may start (with the catalog's plain arguments)
_PROGRAMS = {"msra.exe", "filehistory.exe", "optionalfeatures.exe", "recoverydrive.exe",
             "systempropertiesadvanced.exe", "systempropertiescomputername.exe", "systempropertiesperformance.exe",
             "systempropertiesprotection.exe", "systempropertiesremote.exe", "useraccountcontrolsettings.exe",
             "colorcpl.exe", "control.exe", "cttune.exe", "dccw.exe", "dfrgui.exe", "eudcedit.exe", "mdsched.exe",
             "mmc.exe", "perfmon.exe", "presentationsettings.exe", "psr.exe", "rekeywiz.exe", "rundll32.exe",
             "taskmgr.exe", "xwizard.exe"}
_ARG = re.compile(r"^[A-Za-z0-9_.,@/{}\-\\:%]+$")
_PAGE_URI = re.compile(r"^ms-settings:[A-Za-z0-9\-]+$")
_CANONICAL = re.compile(r"^(Microsoft\.[A-Za-z]+)(?:\\([A-Za-z0-9]+))?$")
_SHELL = re.compile(r"^shell:::\{[0-9A-Fa-f\-]{36}\}(?:\\\d+\\::\{[0-9A-Fa-f\-]{36}\})?$")


def _windir():
    from .winapi import windows_dir
    return windows_dir()


def _explorer():
    from .winapi import system_exe
    return system_exe("explorer.exe")                  # full path, never the search order (review L3)


def system32():
    return os.path.join(_windir(), "System32")


def _resolve_windows(s):
    """A catalog string ("@{windows?ms-resource://...}", "@shell32.dll,-24273") in the user's language."""
    sh = ctypes.WinDLL("shlwapi")
    sh.SHLoadIndirectString.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    buf = ctypes.create_unicode_buffer(2048)
    return buf.value if sh.SHLoadIndirectString(s, buf, 2048, None) == 0 else ""


def text(s, resolve):
    """One catalog field as plain text; "@@a@b" is a list of resources."""
    s = (s or "").strip()
    if not s:
        return ""
    if s.startswith("@@"):
        return ";".join(t for t in (resolve("@" + p) for p in s[2:].split("@") if p) if t)
    return resolve(s) if s.startswith("@") else s


def target(link):
    """A Control Panel deep link -> an argument list to start, or None when it isn't one we open."""
    link = (link or "").strip()
    if link in DEFENDER:
        return [_explorer(), DEFENDER[link]]
    if link in DEFENDER_OTHER:
        return [_explorer(), "windowsdefender:"]
    m = _CANONICAL.match(link)
    if m:
        argv = [os.path.join(system32(), "control.exe"), "/name", m.group(1)]
        return argv + ["/page", m.group(2)] if m.group(2) else argv
    if _SHELL.match(link):
        return [_explorer(), link]
    parts = link.split()
    if not parts:
        return None
    exe = re.sub(r"(?i)^%(windir|systemroot)%", lambda _m: _windir(), parts[0])
    if os.path.normcase(os.path.dirname(exe)) != os.path.normcase(system32()):
        return None
    if os.path.basename(exe).lower() not in _PROGRAMS:
        return None                                    # msdt (retired troubleshooters), ServerManager, ...
    args = [re.sub(r"(?i)%(windir|systemroot)%", lambda _m: _windir(), a) for a in parts[1:]]
    if not all(_ARG.match(a) for a in args):
        return None
    if os.path.basename(exe).lower() == "mmc.exe" and not (len(args) == 1 and args[0].lower().endswith(".msc")
                                                          and os.path.normcase(os.path.dirname(args[0]))
                                                          == os.path.normcase(system32())):
        return None
    return [os.path.join(system32(), os.path.basename(exe))] + args


def parse(files, resolve=_resolve_windows):
    """The catalog files -> [{id, title, words, uri | link}], one per setting (feature variants merged)."""
    trees = []
    for f in files:
        try:
            trees.append(ET.parse(f).getroot())
        except (OSError, ET.ParseError):
            log(f"settings catalog unreadable: {os.path.basename(f)}", "warn")
    learned = {}                                       # page id -> ms-settings name, from the policy ids
    for root in trees:
        sets = {}
        for p in root.iter("Path"):
            pol = [x for x in (p.findtext("PolicyIds") or "").split(";") if x]
            if pol:
                pid = p.findtext("PageID") or ""
                sets[pid] = sets[pid] & set(pol) if pid in sets else set(pol)
        for pid, s in sets.items():
            short = pid[len("SettingsPage"):] if pid.startswith("SettingsPage") else pid
            if short not in PAGES and s:
                learned[short] = min(s, key=lambda c: (len(c), c))
    pages = {**learned, **PAGES}
    out, seen_ids, seen = [], set(), set()
    for root in trees:
        for e in root.iter("SearchableContent"):
            fid = (e.findtext("Filename") or "").strip()
            if not fid or fid in seen_ids or len(fid) > 150:
                continue
            seen_ids.add(fid)
            info = e.find("SettingInformation")
            if info is None:
                continue
            title = text(info.findtext("Description"), resolve)
            if not title:
                continue
            kw = ";".join(x for x in (text(info.findtext("HighKeywords"), resolve),
                                      text(info.findtext("Keywords"), resolve)) if x)
            item = {"id": "ws:" + fid, "title": title[:120], "words": kw[:1500]}
            link = e.findtext("ApplicationInformation/DeepLink")
            if link:
                if target(link) is None:
                    continue
                item["link"] = link.strip()
            else:
                page = None
                for node in e.iter():
                    if node.tag == "PageID" or (node.tag == "Node" and node.attrib.get("Type") == "Page"):
                        v = (node.text or "").strip()
                        page = v[len("SettingsPage"):] if v.startswith("SettingsPage") else v
                        if page in pages:
                            break
                if page not in pages:
                    continue
                item["uri"] = "ms-settings:" + pages[page]
            key = (item["title"].lower(), item.get("uri") or item.get("link"))
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def catalog_files():
    return sorted(glob.glob(os.path.join(_windir(), CATALOG_GLOB)))


def _signature(files):
    lang = 0
    try:
        lang = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        pass
    sig = [lang]
    for f in files:
        try:
            st = os.stat(f)
            sig.append([os.path.basename(f), st.st_size, int(st.st_mtime)])
        except OSError:
            pass
    return sig


def load(data_dir, files=None, resolve=_resolve_windows):
    """The catalog, from <data>/wsettings.json when Windows' files haven't changed, else read and saved again."""
    files = catalog_files() if files is None else files
    path = os.path.join(data_dir, "wsettings.json")
    sig = _signature(files)
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("sig") == sig and isinstance(d.get("items"), list):
            return d["items"]
    except (OSError, ValueError, AttributeError):
        pass
    if not files:
        return []
    t = time.perf_counter()
    items = parse(files, resolve)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sig": sig, "items": items}, f)
        os.replace(tmp, path)
    except OSError:
        pass
    log(f"settings catalog: {len(items)} Windows settings ({time.perf_counter() - t:.1f} s)")
    return items
