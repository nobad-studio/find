"""Open Windows settings and apps from the search box (0.9.1): "open bluetooth", "display settings", "turn off
wifi", "chrome", "open spotify".

- Settings: a fixed table of Windows Settings pages (ms-settings: links) and classic tools (Device Manager, Task
  Manager, ...), each with the words people use for it.
- Apps: Windows' own Start list (Get-StartApps: programs and Store apps alike), read in the background once and
  then every few hours, kept in <data>/apps.json; the registry's installed-programs list adds the version,
  publisher and install folder. Nothing stays running.
- Every other Windows setting: Windows' own Settings search catalog (wsettings.py, about 1,750 settings in the
  user's language), read in the background, matched through a word index.
- Matching: the question without "open", "launch", "settings", ...; whole words, word starts and typos
  (difflib), the name counting most. Cheap: a few hundred short strings.
- Running: only by an action id from this table or the app list, never a path or a command from the window. An
  app starts through the shell (explorer.exe shell:AppsFolder\\<AppID>), outside NOBAD Find's job, as the user.
"""
import bisect
import difflib
import json
import os
import re
import subprocess
import threading
import time

from . import wsettings
from .log import log

REFRESH_S = 6 * 3600
VERBS = {"open", "launch", "start", "run", "show", "go", "to", "goto", "turn", "on", "off", "switch", "enable",
         "disable", "change", "set", "setup", "settings", "setting", "page", "app", "the", "my", "windows", "win",
         "control", "panel", "manage", "adjust", "configure", "please", "find"}
LAUNCH_WORDS = {"open", "launch", "start", "run", "turn", "switch", "enable", "disable", "settings", "setting"}

# (id, title, uri or tool, words people use). ms-settings: pages are Windows' own; tools are fixed programs.
SETTINGS = [
    ("bluetooth", "Bluetooth & devices", "ms-settings:bluetooth", "bluetooth bt pair devices headphones earbuds"),
    ("devices", "Devices", "ms-settings:connecteddevices", "devices connected peripherals"),
    ("printers", "Printers & scanners", "ms-settings:printers", "printer printers scanner scanners print"),
    ("mouse", "Mouse", "ms-settings:mousetouchpad", "mouse cursor pointer speed scroll"),
    ("touchpad", "Touchpad", "ms-settings:devices-touchpad", "touchpad trackpad gestures"),
    ("pen", "Pen & Windows Ink", "ms-settings:pen", "pen stylus ink"),
    ("autoplay", "AutoPlay", "ms-settings:autoplay", "autoplay usb insert"),
    ("usb", "USB", "ms-settings:usb", "usb ports"),
    ("camera", "Cameras", "ms-settings:camera", "camera webcam"),
    ("wifi", "Wi-Fi", "ms-settings:network-wifi", "wifi wi-fi wireless wlan internet network hotspot"),
    ("network", "Network & internet", "ms-settings:network", "network internet connection ethernet status"),
    ("ethernet", "Ethernet", "ms-settings:network-ethernet", "ethernet cable lan wired"),
    ("vpn", "VPN", "ms-settings:network-vpn", "vpn virtual private network"),
    ("proxy", "Proxy", "ms-settings:network-proxy", "proxy"),
    ("hotspot", "Mobile hotspot", "ms-settings:network-mobilehotspot", "hotspot tethering share internet"),
    ("airplane", "Airplane mode", "ms-settings:network-airplanemode", "airplane flight mode aeroplane"),
    ("data-usage", "Data usage", "ms-settings:datausage", "data usage metered"),
    ("display", "Display", "ms-settings:display", "display screen monitor resolution brightness scale scaling hdr"),
    ("night-light", "Night light", "ms-settings:nightlight", "night light blue light warm"),
    ("sound", "Sound", "ms-settings:sound", "sound audio volume speaker speakers microphone mic output input"),
    ("sound-devices", "Sound devices", "ms-settings:sound-devices", "sound devices audio devices"),
    ("notifications", "Notifications", "ms-settings:notifications", "notifications alerts toast"),
    ("focus", "Focus", "ms-settings:quiethours", "focus assist do not disturb quiet hours dnd"),
    ("power", "Power & battery", "ms-settings:powersleep", "power battery sleep energy saver shutdown lid"),
    ("battery", "Battery saver", "ms-settings:batterysaver", "battery saver"),
    ("storage", "Storage", "ms-settings:storagesense", "storage disk space storage sense cleanup free space"),
    ("multitasking", "Multitasking", "ms-settings:multitasking", "multitasking snap windows alt tab"),
    ("clipboard", "Clipboard", "ms-settings:clipboard", "clipboard history copy paste"),
    ("remote-desktop", "Remote Desktop", "ms-settings:remotedesktop", "remote desktop rdp"),
    ("projecting", "Projecting to this PC", "ms-settings:project", "project projecting miracast cast"),
    ("about", "About this PC", "ms-settings:about", "about pc name specs system info device specifications ram"),
    ("activation", "Activation", "ms-settings:activation", "activation product key license"),
    ("troubleshoot", "Troubleshoot", "ms-settings:troubleshoot", "troubleshoot troubleshooter fix problems"),
    ("recovery", "Recovery", "ms-settings:recovery", "recovery reset this pc restore"),
    ("windows-update", "Windows Update", "ms-settings:windowsupdate", "windows update updates upgrade patch"),
    ("update-history", "Update history", "ms-settings:windowsupdate-history", "update history installed updates"),
    ("background", "Background", "ms-settings:personalization-background", "background wallpaper desktop picture"),
    ("colors", "Colors", "ms-settings:colors", "colors colours dark mode light mode accent theme color"),
    ("themes", "Themes", "ms-settings:themes", "themes theme"),
    ("lock-screen", "Lock screen", "ms-settings:lockscreen", "lock screen lockscreen"),
    ("start-menu", "Start", "ms-settings:personalization-start", "start menu"),
    ("taskbar", "Taskbar", "ms-settings:taskbar", "taskbar task bar system tray icons"),
    ("fonts", "Fonts", "ms-settings:fonts", "fonts font"),
    ("apps", "Installed apps", "ms-settings:appsfeatures", "apps installed apps uninstall programs features remove"),
    ("default-apps", "Default apps", "ms-settings:defaultapps", "default apps default browser open with"),
    ("startup-apps", "Startup apps", "ms-settings:startupapps", "startup apps start up boot programs autostart"),
    ("optional-features", "Optional features", "ms-settings:optionalfeatures", "optional features"),
    ("offline-maps", "Offline maps", "ms-settings:maps", "maps offline maps"),
    ("accounts", "Your info", "ms-settings:yourinfo", "account accounts profile user picture"),
    ("sign-in", "Sign-in options", "ms-settings:signinoptions", "sign in password pin windows hello fingerprint face"),
    ("email-accounts", "Email & accounts", "ms-settings:emailandaccounts", "email accounts mail"),
    ("family", "Family & other users", "ms-settings:otherusers", "family other users add user"),
    ("backup", "Windows Backup", "ms-settings:backup", "backup back up onedrive"),
    ("date-time", "Date & time", "ms-settings:dateandtime", "date time clock timezone time zone"),
    ("language", "Language & region", "ms-settings:regionlanguage", "language region keyboard layout locale"),
    ("typing", "Typing", "ms-settings:typing", "typing autocorrect spell check"),
    ("speech", "Speech", "ms-settings:speech", "speech voice"),
    ("gaming", "Gaming", "ms-settings:gaming-gamebar", "gaming game bar xbox"),
    ("game-mode", "Game Mode", "ms-settings:gaming-gamemode", "game mode"),
    ("graphics", "Graphics", "ms-settings:display-advancedgraphics", "graphics gpu performance preference"),
    ("accessibility", "Accessibility", "ms-settings:easeofaccess", "accessibility ease of access"),
    ("narrator", "Narrator", "ms-settings:easeofaccess-narrator", "narrator screen reader"),
    ("magnifier", "Magnifier", "ms-settings:easeofaccess-magnifier", "magnifier zoom"),
    ("text-size", "Text size", "ms-settings:easeofaccess-display", "text size bigger text"),
    ("contrast", "Contrast themes", "ms-settings:easeofaccess-highcontrast", "high contrast contrast themes"),
    ("privacy", "Privacy & security", "ms-settings:privacy", "privacy security permissions"),
    ("location", "Location", "ms-settings:privacy-location", "location gps"),
    ("mic-privacy", "Microphone access", "ms-settings:privacy-microphone", "microphone access mic permission"),
    ("camera-privacy", "Camera access", "ms-settings:privacy-webcam", "camera access webcam permission"),
    ("windows-security", "Windows Security", "windowsdefender:", "windows security defender antivirus virus firewall"),
    ("find-my-device", "Find my device", "ms-settings:findmydevice", "find my device lost"),
    ("developers", "For developers", "ms-settings:developers", "developer mode developers"),
    ("settings", "Settings", "ms-settings:", "settings"),
    # classic tools (fixed programs, fixed arguments)
    ("task-manager", "Task Manager", "tool:taskmgr.exe", "task manager processes kill end task"),
    ("device-manager", "Device Manager", "tool:devmgmt.msc", "device manager drivers hardware"),
    ("disk-management", "Disk Management", "tool:diskmgmt.msc", "disk management partitions drives format"),
    ("control-panel", "Control Panel", "tool:control.exe", "control panel"),
    ("services", "Services", "tool:services.msc", "services"),
    ("event-viewer", "Event Viewer", "tool:eventvwr.msc", "event viewer logs events"),
    ("system-information", "System Information", "tool:msinfo32.exe", "system information msinfo"),
    ("resource-monitor", "Resource Monitor", "tool:resmon.exe", "resource monitor"),
    ("network-connections", "Network connections", "tool:ncpa.cpl", "network connections adapters adapter"),
    ("sound-panel", "Sound control panel", "tool:mmsys.cpl", "sound control panel playback recording devices"),
    ("programs-features", "Programs and Features", "tool:appwiz.cpl", "programs and features uninstall a program"),
    ("system-properties", "System properties", "tool:sysdm.cpl", "system properties advanced system settings"),
    ("power-options", "Power options", "tool:powercfg.cpl", "power options power plan"),
    ("firewall", "Windows Defender Firewall", "tool:firewall.cpl", "firewall"),
    ("command-prompt", "Command Prompt", "tool:cmd.exe", "command prompt cmd terminal"),
    ("powershell", "PowerShell", "tool:powershell.exe", "powershell"),
    ("file-explorer", "File Explorer", "tool:explorer.exe", "file explorer explorer files folders"),
    ("snipping-tool", "Snipping Tool", "ms-screenclip:", "snipping tool screenshot snip screen capture"),
]
SETTINGS_BY_ID = {"set:" + x[0]: x for x in SETTINGS}
_TOOLS = {"taskmgr.exe", "devmgmt.msc", "diskmgmt.msc", "control.exe", "services.msc", "eventvwr.msc",
          "msinfo32.exe", "resmon.exe", "ncpa.cpl", "mmsys.cpl", "appwiz.cpl", "sysdm.cpl", "powercfg.cpl",
          "firewall.cpl", "cmd.exe", "powershell.exe", "explorer.exe"}
_SAFE_URI = re.compile(r"^(ms-settings:[a-z0-9\-]*|windowsdefender:|ms-screenclip:)$")
_WORD = re.compile(r"[a-z0-9]+(?:[+#][a-z0-9]*)?")


def words(text):
    return _WORD.findall((text or "").lower().replace("wi-fi", "wifi"))


def wants_launch(text):
    """The question starts with a launch word ("open ...", "turn off ..."), or ends with "settings"."""
    w = words(text)
    return bool(w) and (w[0] in LAUNCH_WORDS or w[-1] in ("settings", "setting"))


def _score(qwords, title, extra):
    """0..1: how well the question's words fit an entry (its title counts most)."""
    if not qwords:
        return 0.0
    tw, ew = words(title), set(words(extra)) | set(words(title))
    total = 0.0
    for q in qwords:
        best = 0.0
        for w in ew:
            if q == w:
                best = 1.0
                break
            if len(q) >= 3 and w.startswith(q):
                best = max(best, 0.85)
            elif len(q) >= 4 and len(w) >= 4:
                r = difflib.SequenceMatcher(None, q, w).ratio()
                if r >= 0.8:
                    best = max(best, r * 0.9)            # "blutooth" -> bluetooth
        total += best
    s = total / len(qwords)
    joined = " ".join(qwords)
    if joined == " ".join(tw) or joined == title.lower():
        s = max(s, 1.0) + 0.2                           # the exact name
    elif tw and tw[0].startswith(qwords[0]) and len(qwords[0]) >= 2:
        s += 0.1
    return s


class Catalog:
    """Windows' settings catalog with a word index: a question looks only at the settings sharing a word."""

    def __init__(self, items):
        self.items = list(items)
        self.title_words = [set(words(i["title"])) for i in self.items]
        self.all_words = []
        index = {}
        for n, i in enumerate(self.items):
            ws = self.title_words[n] | set(words(i.get("words", "")))
            self.all_words.append(ws)
            for w in ws:
                index.setdefault(w, []).append(n)
        self.index = index
        self.vocab = sorted(index)

    def _matches(self, q):
        """{word in the catalog: how well it fits q} for one question word."""
        out = {}
        if q in self.index:
            out[q] = 1.0
        if len(q) >= 3:
            i = bisect.bisect_left(self.vocab, q)
            while i < len(self.vocab) and self.vocab[i].startswith(q):
                out.setdefault(self.vocab[i], 0.85)
                i += 1
        if not out and len(q) >= 4:
            for w in difflib.get_close_matches(q, self.vocab, n=3, cutoff=0.8):
                out[w] = difflib.SequenceMatcher(None, q, w).ratio() * 0.9
        return out

    def search(self, qwords, limit=6):
        """[(score, item)] best first."""
        if not qwords or not self.items:
            return []
        per = [self._matches(q) for q in qwords]
        cand = set()
        for m in per:
            for w in m:
                cand.update(self.index[w])
        joined = " ".join(qwords)
        scored = []
        for n in cand:
            tw, aw = self.title_words[n], self.all_words[n]
            total, named = 0.0, False
            for m in per:
                best = 0.0
                for w, s in m.items():
                    if w in tw:
                        best = max(best, s)
                        named = True
                    elif w in aw:
                        best = max(best, s * 0.9)        # a keyword counts a little less than the name
                total += best
            s = total / len(qwords)
            title = self.items[n]["title"].lower()
            if joined == " ".join(words(title)):
                s += 0.2                                # the exact name
            s += 0.1 * len(tw & set(qwords)) / max(len(tw), 1)     # shorter, closer names first
            scored.append((s * 0.95, named, self.items[n]))     # the hand table's page wins a tie
        if any(x[1] for x in scored):
            scored = [x for x in scored if x[1]]       # a word only in the keywords: only when no name has it
        scored.sort(key=lambda x: -x[0])
        return [(s, item) for s, _named, item in scored[:limit]]


class Launcher:
    def __init__(self, data_dir, run=None, clock=time.time):
        self.data_dir = data_dir
        self.catalog = Catalog([])
        self._catalog_read = False
        self.path = os.path.join(data_dir, "apps.json")
        self.apps = []                                  # [{id, name, app_id, version, publisher, folder}]
        self._at = 0.0
        self._clock = clock
        self._run = run
        self._lock = threading.Lock()
        self._busy = None
        self._load()

    # ---------- the app list ----------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("apps"), list):
                self.apps = [a for a in d["apps"] if isinstance(a, dict) and a.get("name") and a.get("app_id")]
                self._at = float(d.get("at") or 0)
        except (OSError, ValueError):
            pass

    def refresh_in_background(self):
        if self._busy is not None and self._busy.is_alive():
            return False
        apps = self._clock() - self._at >= REFRESH_S
        if not apps and self._catalog_read:
            return False

        def work():
            if not self._catalog_read:
                self.read_catalog()
            if apps:
                self.refresh()
        self._busy = threading.Thread(target=work, daemon=True, name="apps")
        self._busy.start()
        return True

    def read_catalog(self, files=None, resolve=None):
        """Windows' settings catalog (from <data>/wsettings.json while Windows' files are unchanged)."""
        try:
            kw = {} if resolve is None else {"resolve": resolve}
            items = wsettings.load(self.data_dir, files, **kw)
            with self._lock:
                self.catalog = Catalog(items)
        except Exception as e:
            log(f"settings catalog failed: {type(e).__name__}", "warn")
        self._catalog_read = True

    def refresh(self):
        try:
            start = _start_apps()
            info = _installed_info()
            apps = []
            for i, (name, app_id) in enumerate(sorted(start, key=lambda x: x[0].lower())):
                extra = info.get(_norm(name), {})
                apps.append({"id": f"app:{i}:{_slug(name)}", "name": name, "app_id": app_id,
                             "version": extra.get("version", ""), "publisher": extra.get("publisher", ""),
                             "folder": extra.get("folder", "")})
            with self._lock:
                self.apps, self._at = apps, self._clock()
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"at": self._at, "apps": apps}, f)
            os.replace(tmp, self.path)
            log(f"apps: {len(apps)} apps in the Start list")
        except Exception as e:
            log(f"apps list failed: {type(e).__name__}", "warn")
            self._at = self._clock()                    # not again for a while

    # ---------- matching ----------
    def actions(self, text, limit=4):
        """The best settings pages and apps for the question, best first; [] when nothing fits well."""
        w = [x for x in words(text) if x not in VERBS] or [x for x in words(text) if x not in ("open", "launch")]
        if not w or len(" ".join(w)) < 2:
            return []
        launch = wants_launch(text)
        out = []
        for sid, title, target, extra in SETTINGS:
            s = _score(w, title, extra)
            if s >= (0.6 if launch else 0.8):
                kind = "tool" if target.startswith("tool:") else "setting"
                sub = "Windows Settings" if target.startswith("ms-settings:") else \
                    "Windows tool" if kind == "tool" else "Windows"
                out.append((s + (0.05 if launch else 0), {"id": "set:" + sid, "kind": kind, "title": title,
                                                           "subtitle": sub}))
        with self._lock:
            apps, catalog = list(self.apps), self.catalog
        pages = {SETTINGS_BY_ID[a["id"]][2] for _s, a in out}
        for s, item in catalog.search(w):
            if item.get("uri") in pages:
                continue                                # the same page is already offered by its usual name
            if s >= (0.6 if launch else 0.8):
                sub = "Windows Settings" if "uri" in item else "Control Panel"
                out.append((s + (0.05 if launch else 0), {"id": item["id"], "kind": "setting", "title": item["title"],
                                                           "subtitle": sub}))
        for a in apps:
            s = _score(w, a["name"], a.get("publisher", ""))
            if a["name"].lower().startswith("uninstall") and len(w) < 2:
                s -= 0.4                                # "uninstall" alone: the Installed apps page, not an uninstaller
            if s >= (0.65 if launch else 0.9):
                sub = " · ".join(x for x in (a.get("publisher"), a.get("version") and "version " + a["version"],
                                             a.get("folder")) if x) or "App"
                out.append((s + 0.02, {"id": a["id"], "kind": "app", "title": a["name"], "subtitle": sub}))
        out.sort(key=lambda x: -x[0])
        seen, res = set(), []
        for _s, a in out:
            k = a["title"].lower()                     # one "Task Manager", not the app and the tool
            if k not in seen:
                seen.add(k)
                res.append(a)
        return res[:limit]

    # ---------- running ----------
    def run(self, action_id):
        """Run one action by its id. {"ok", "error"}. Never a path or a command from the window."""
        if not isinstance(action_id, str) or len(action_id) > 200:
            return {"ok": False, "error": "That isn't something NOBAD Find can open."}
        if action_id.startswith("set:"):
            hit = next((x for x in SETTINGS if "set:" + x[0] == action_id), None)
            if hit is None:
                return {"ok": False, "error": "That setting isn't known."}
            target = hit[2]
            if target.startswith("tool:"):
                tool = target[5:]
                if tool not in _TOOLS:
                    return {"ok": False, "error": "That tool isn't known."}
                return self._start(["explorer.exe", tool] if tool.endswith((".msc", ".cpl")) else [tool], hit[1])
            if not _SAFE_URI.match(target):
                return {"ok": False, "error": "That setting isn't known."}
            return self._start(["explorer.exe", target], hit[1])
        if action_id.startswith("ws:"):
            with self._lock:
                item = next((x for x in self.catalog.items if x["id"] == action_id), None)
            if item is None:
                return {"ok": False, "error": "That setting isn't known."}
            if "uri" in item:
                if not wsettings._PAGE_URI.match(item["uri"]):
                    return {"ok": False, "error": "That setting isn't known."}
                return self._start(["explorer.exe", item["uri"]], item["title"])
            argv = wsettings.target(item.get("link"))
            if argv is None:
                return {"ok": False, "error": "That setting isn't known."}
            return self._start(argv, item["title"])
        if action_id.startswith("app:"):
            with self._lock:
                a = next((x for x in self.apps if x["id"] == action_id), None)
            if a is None:
                return {"ok": False, "error": "That app isn't in the Start list any more."}
            return self._start(["explorer.exe", "shell:AppsFolder\\" + a["app_id"]], a["name"])
        return {"ok": False, "error": "That isn't something NOBAD Find can open."}

    def _start(self, argv, what):
        try:
            run = self._run
            if run is None:
                from .winapi import start_outside_job as run
            run(argv)
            log(f"opened {what}")
            return {"ok": True, "error": ""}
        except Exception as e:
            log(f"couldn't open {what}: {type(e).__name__}", "warn")
            return {"ok": False, "error": f"Couldn't open {what}."}


def _norm(name):
    return " ".join(words(name))


def _slug(name):
    return "-".join(words(name))[:40] or "app"


def _start_apps():
    """[(name, AppID)] from Get-StartApps (programs and Store apps), UTF-8, no window, a fixed command."""
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
                       timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    data = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data if isinstance(data, list) else []:
        n, a = str(d.get("Name") or "").strip(), str(d.get("AppID") or "").strip()
        if n and a and "\x00" not in a and len(a) < 600:
            out.append((n, a))
    return out


def _installed_info():
    """{normalized name: {version, publisher, folder}} from the registry's installed-programs lists."""
    out = {}
    try:
        import winreg
    except ImportError:
        return out
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            k = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    with winreg.OpenKey(k, winreg.EnumKey(k, i)) as sub:
                        def val(n):
                            try:
                                v = winreg.QueryValueEx(sub, n)[0]
                                return str(v).strip() if isinstance(v, str) else ""
                            except OSError:
                                return ""
                        name = val("DisplayName")
                        if not name:
                            continue
                        folder = val("InstallLocation").strip('"')
                        if not folder:
                            icon = val("DisplayIcon").split(",")[0].strip('"')
                            folder = os.path.dirname(icon) if icon.lower().endswith(".exe") else ""
                        out.setdefault(_norm(name), {"version": val("DisplayVersion"), "publisher": val("Publisher"),
                                                     "folder": folder})
                except OSError:
                    continue
    return out
