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
import ntpath
import os
import re
import subprocess
import threading
import time

from . import wsettings
from .display import visible
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
    ("network", "Network & internet", "ms-settings:network-status", "network internet connection ethernet status"),
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
    return _wants(words(text))


def _wants(w):
    return bool(w) and (w[0] in LAUNCH_WORDS or w[-1] in ("settings", "setting"))


def _osa(a, b, cap):
    """Edit distance with swapped neighbours counting once (optimal string alignment); > cap stops early."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


# The words Find's own table knows: launch words, filler words and every entry's title and keywords. A typo is
# corrected only to one of these (never to anything typed or read from the PC), so matching stays deterministic.
_TABLE = {w for x in SETTINGS for w in words(x[1] + " " + x[3])}
_FIXED = sorted(VERBS | LAUNCH_WORDS | _TABLE)
_FIXED_SET = set(_FIXED)
_FIRST = {}
for _w in _FIXED:
    _FIRST.setdefault(_w[0], []).append(_w)


def correct(ws, known=()):
    """ws with typos fixed against the fixed table's words: "opn windws update" -> open windows update.
    Only a word of 3+ letters that no table, catalog or app knows; the first letter must match; 1 edit up to 5
    letters, 2 from 6 ("pannle" -> panel). The nearest word wins; on a tie a launch word, then a word an entry
    has over a filler word ("managr" -> manager, not manage), then the alphabet."""
    out = []
    for w in ws:
        if len(w) < 3 or w in known or w.isdigit() or w in _FIXED_SET:
            out.append(w)
            continue
        cap = 1 if len(w) <= 5 else 2
        best = None
        for c in _FIRST.get(w[0], ()):
            if len(c) < 3 or (len(w) == 3 and c not in VERBS):
                continue                                # 3 letters: only "opn" -> open, never "tax" -> tab
            d = _osa(w, c, cap)
            if d <= cap:
                k = (d, c not in LAUNCH_WORDS, c not in _TABLE, c)
                if best is None or k < best:
                    best = k
        out.append(best[-1] if best else w)
    return out


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
                self.apps = [a for a in d["apps"] if isinstance(a, dict) and a.get("name") and (a.get("app_id") or a.get("exe"))]
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
            entries, app_paths = _registry_apps()
            info = _installed_info(entries)
            apps = []
            for i, (name, app_id) in enumerate(sorted(start, key=lambda x: x[0].lower())):
                extra = info.get(_norm(name), {})
                apps.append({"id": f"app:{i}:{_slug(name)}", "name": name, "app_id": app_id,
                             "version": extra.get("version", ""), "publisher": extra.get("publisher", ""),
                             "folder": extra.get("folder", "")})
            known = {_norm(n) for n, _a in start}
            for name, version, publisher, folder, exe in _registry_only(entries, app_paths, known):
                apps.append({"id": f"app:{len(apps)}:{_slug(name)}", "name": name, "exe": exe, "version": version,
                             "publisher": publisher, "folder": folder})
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
    def _words(self, text):
        """The question's words, typos corrected against the fixed table (correct()); words the settings catalog
        or an app's name has are kept as typed."""
        ws = words(text)
        with self._lock:
            index, apps = self.catalog.index, self.apps
        if all(len(w) < 3 or w in _FIXED_SET or w in index for w in ws):
            return ws
        known = set(index)
        for a in apps:
            known.update(words(a.get("name", "")))
        return correct(ws, known)

    def wants(self, text):
        """wants_launch with typos corrected: "opn windws update" asks to open something."""
        return _wants(self._words(text))

    def actions(self, text, limit=4):
        """The best settings pages and apps for the question, best first; [] when nothing fits well."""
        qw = self._words(text)
        w = [x for x in qw if x not in VERBS] or [x for x in qw if x not in ("open", "launch")]
        if not w or len(" ".join(w)) < 2:
            return []
        launch = _wants(qw)
        # 0.9.5: the question minus its launch word (and a trailing "app" / "page") naming an entry exactly wins:
        # "open windows update" is Windows Update, not Update history ("windows" alone is a filler word above)
        full = [x for x in qw if x not in ("open", "launch", "start", "run", "go", "to", "please", "the", "my")]
        while len(full) > 1 and full[-1] in ("app", "page", "window"):
            full.pop()
        named = " ".join(full)

        def exact(title):
            return 0.6 if named and named == " ".join(words(title)) else 0.0
        out = []
        for sid, title, target, extra in SETTINGS:
            s = _score(w, title, extra) + exact(title)
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
            s += exact(item["title"])
            if item.get("uri") in pages:
                continue                                # the same page is already offered by its usual name
            if s >= (0.6 if launch else 0.8):
                sub = "Windows Settings" if "uri" in item else "Control Panel"
                out.append((s + (0.05 if launch else 0), {"id": item["id"], "kind": "setting", "title": item["title"],
                                                           "subtitle": sub}))
        for a in apps:
            s = _score(w, a["name"], a.get("publisher", "")) + exact(a["name"])
            if a["name"].lower().startswith("uninstall") and len(w) < 2:
                s -= 0.4                                # "uninstall" alone: the Installed apps page, not an uninstaller
            if s >= (0.65 if launch else 0.9):
                sub = " · ".join(x for x in (a.get("publisher"), a.get("version") and "version " + a["version"],
                                             a.get("folder")) if x) or "App"
                out.append((s + 0.02, {"id": a["id"], "kind": "app", "title": visible(a["name"]),   # L7
                                       "subtitle": visible(sub)}))
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
                return self._start([_exe("explorer.exe"), tool] if tool.endswith((".msc", ".cpl")) else [_exe(tool)],
                                   hit[1])
            if not _SAFE_URI.match(target):
                return {"ok": False, "error": "That setting isn't known."}
            return self._start([_exe("explorer.exe"), target], hit[1])
        if action_id.startswith("ws:"):
            with self._lock:
                item = next((x for x in self.catalog.items if x["id"] == action_id), None)
            if item is None:
                return {"ok": False, "error": "That setting isn't known."}
            if "uri" in item:
                if not wsettings._PAGE_URI.match(item["uri"]):
                    return {"ok": False, "error": "That setting isn't known."}
                return self._start([_exe("explorer.exe"), item["uri"]], item["title"])
            argv = wsettings.target(item.get("link"))
            if argv is None:
                return {"ok": False, "error": "That setting isn't known."}
            return self._start(argv, item["title"])
        if action_id.startswith("app:"):
            with self._lock:
                a = next((x for x in self.apps if x["id"] == action_id), None)
            if a is None:
                return {"ok": False, "error": "That app isn't in the Start list any more."}
            if a.get("exe"):                            # registry-only: checked again, then the program itself
                if not _safe_exe(a["exe"], a.get("folder", "")):
                    return {"ok": False, "error": "That app can't be opened from here any more."}
                return self._start([a["exe"]], a["name"], cwd=ntpath.dirname(a["exe"]))
            return self._start([_exe("explorer.exe"), "shell:AppsFolder\\" + a["app_id"]], a["name"])
        return {"ok": False, "error": "That isn't something NOBAD Find can open."}

    def _start(self, argv, what, cwd=None):
        try:
            run = self._run
            if run is None:
                from .winapi import start_outside_job as run
            run(argv) if cwd is None else run(argv, cwd=cwd)
            log(f"opened {what}")
            return {"ok": True, "error": ""}
        except Exception as e:
            log(f"couldn't open {what}: {type(e).__name__}", "warn")
            return {"ok": False, "error": f"Couldn't open {what}."}


def _exe(name):
    """Windows' own program by full path (winapi.system_exe), never by the search order."""
    from .winapi import system_exe
    return system_exe(name)


def _norm(name):
    return " ".join(words(name))


def _slug(name):
    return "-".join(words(name))[:40] or "app"


def _start_apps():
    """[(name, AppID)] from Get-StartApps (programs and Store apps), UTF-8, no window, a fixed command."""
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    r = subprocess.run([_exe("powershell.exe"), "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True,
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


_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"


def _registry_apps():
    """([{name, version, publisher, location, icon}], {exe name: path}) from the installed-programs lists and
    App Paths. Read only; nothing here is trusted until _safe_exe."""
    entries, app_paths = [], {}
    try:
        import winreg
    except ImportError:
        return entries, app_paths
    for hive, path in ((winreg.HKEY_LOCAL_MACHINE, _UNINSTALL),
                       (winreg.HKEY_LOCAL_MACHINE, _UNINSTALL.replace("SOFTWARE", r"SOFTWARE\WOW6432Node", 1)),
                       (winreg.HKEY_CURRENT_USER, _UNINSTALL)):
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
                                v, kind = winreg.QueryValueEx(sub, n)
                                return _expand_value(v, kind).strip() if isinstance(v, str) else ""
                            except OSError:
                                return ""

                        def flag(n):
                            try:
                                return winreg.QueryValueEx(sub, n)[0] == 1
                            except OSError:
                                return False
                        name = val("DisplayName")
                        if name:
                            entries.append({"name": name, "version": val("DisplayVersion"),
                                            "publisher": val("Publisher"), "location": val("InstallLocation"),
                                            "icon": val("DisplayIcon"), "system": flag("SystemComponent"),
                                            "parent": val("ParentKeyName"), "release": val("ReleaseType")})
                except OSError:
                    continue
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            k = winreg.OpenKey(hive, _APP_PATHS)
        except OSError:
            continue
        with k:
            for i in range(winreg.QueryInfoKey(k)[0]):
                try:
                    exe = winreg.EnumKey(k, i)
                    with winreg.OpenKey(k, exe) as sub:
                        v, kind = winreg.QueryValueEx(sub, "")
                    if isinstance(v, str) and v.strip():
                        app_paths.setdefault(exe.lower(), _expand_value(v, kind).strip())
                except OSError:
                    continue
    return entries, app_paths


def _expand_value(value, kind):
    """REG_EXPAND_SZ (type 2) values hold %VARIABLES%; REG_SZ stays as it is."""
    return os.path.expandvars(value) if kind == 2 else value


def _installed_info(entries=None):
    """{normalized name: {version, publisher, folder}} from the registry's installed-programs lists."""
    out = {}
    for e in _registry_apps()[0] if entries is None else entries:
        folder = e["location"].strip('"')
        if not folder:
            icon = _icon_path(e["icon"])
            folder = ntpath.dirname(icon) if icon.lower().endswith(".exe") else ""
        out.setdefault(_norm(e["name"]), {"version": e["version"], "publisher": e["publisher"], "folder": folder})
    return out


def _icon_path(icon):
    """DisplayIcon is 'path,index' (the path sometimes quoted)."""
    icon = icon.strip()
    if icon.startswith('"'):
        return icon[1:].split('"', 1)[0].strip()
    return icon.rsplit(",", 1)[0].strip() if re.search(r",\s*-?\d+$", icon) else icon


_LOCAL_ABS = re.compile(r"^[A-Za-z]:[\\/]")


def _is_file(path):
    return os.path.isfile(path)


def _program_roots():
    roots = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
    return [r for r in roots if r]


def _inside(path, folder):
    p, f = ntpath.normcase(ntpath.normpath(path)), ntpath.normcase(ntpath.normpath(folder))
    if not f or not _LOCAL_ABS.match(f) or ntpath.dirname(f) == f:                 # no folder, or a whole drive: not a boundary
        return False
    return p.startswith(f.rstrip("\\") + "\\")


def _safe_exe(exe, folder):
    """A registry-listed program may be opened only when it is an existing .exe inside its own install folder or
    Program Files, and isn't an uninstaller, installer or updater."""
    if not isinstance(exe, str) or "\x00" in exe or len(exe) > 520 or not _LOCAL_ABS.match(exe):
        return False                                    # also no \\server\share or \\?\ paths: never looked up
    exe = ntpath.normpath(exe)
    base = ntpath.basename(exe).lower()
    if not base.endswith(".exe") or base.startswith(("unins", "update")) or "setup" in base:
        return False
    if not (_inside(exe, folder or "") or any(_inside(exe, r) for r in _program_roots())):
        return False
    return bool(_is_file(exe))


_NOT_APP_RELEASE = {"update", "hotfix", "security update", "update rollup", "service pack"}


def _registry_only(entries, app_paths, known):
    """[(name, version, publisher, folder, exe)] for installed programs that have no Start-list entry and whose
    program is found by DisplayIcon or App Paths and passes _safe_exe."""
    out, seen = [], set(known)
    for e in sorted(entries, key=lambda x: x["name"].lower()):
        n = _norm(e["name"])
        if not n or n in seen:
            continue
        if e.get("system") or e.get("parent") or str(e.get("release") or "").lower() in _NOT_APP_RELEASE:
            continue
        folder = e["location"].strip().strip('"')       # the boundary: only InstallLocation, never derived from the exe
        icon = _icon_path(e["icon"])
        if icon and not ntpath.isabs(icon) and folder:
            icon = ntpath.join(folder, icon)
        cands = [icon] if icon.lower().endswith(".exe") else []
        here = [p.strip('"') for p in app_paths.values()
                if folder and ntpath.normcase(ntpath.dirname(p.strip('"'))) == ntpath.normcase(ntpath.normpath(folder))]
        if len(here) == 1:                              # one App Paths program there: that one; several: not guessed
            cands.append(here[0])
        cands += [p.strip('"') for name, p in app_paths.items() if _norm(ntpath.splitext(name)[0]) == n]
        exe = next((c for c in cands if _safe_exe(c, folder)), None)
        if exe:
            seen.add(n)
            out.append((e["name"], e["version"], e["publisher"], folder, ntpath.normpath(exe)))
    return out
