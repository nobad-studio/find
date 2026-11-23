"""A deterministic engine for the contract transcripts: the real handlers and the real Events, over a fake Api
whose answers never depend on the PC, the clock or the index. Transcripts are recorded from it and replayed
against it (tests/test_rpc_contract.py), so the Dart side can parse exactly what the Python side produces."""
import os
from nobadfind.activity import Activity
from nobadfind.const import DEFAULTS
from nobadfind.rpc import handlers
from nobadfind.rpc.events import Events
from nobadfind.settings import coerce

UPDATE_NOTES = "https://github.com/nobad-studio/find/releases/tag/find-v0.9.0"
RESULT = {"id": 7, "path": "C:\\Users\\me\\Documents\\tax 2025.pdf", "name": "tax 2025.pdf",
          "dir": "C:\\Users\\me\\Documents", "kind": "pdf", "size": 48213, "mtime": 1763400000.0,
          "ago": "2 days ago", "why": ["name matches"], "snippet": "", "weak": False}


class FakeGov:
    def __init__(self):
        self.level, self.reason = "gentle", "Gentle: you're using the PC"


class FakeApi:
    """Every method the handlers reach, with fixed answers; `calls` records what was asked."""

    def __init__(self):
        self.calls = []
        self.on_quit = None
        self.here = ""
        self.gov = FakeGov()
        self.paused = ""
        self.settings = dict(DEFAULTS)
        self.dl = {"meaning": {"state": "missing", "got": 0, "size": 0, "error": ""},
                   "photo": {"state": "missing", "got": 0, "size": 0, "error": ""}}
        self.ready = set()                       # model ids "downloaded" in this fake
        self.history = set()                     # questions kept for autocomplete (history_add)
        self.turbo = {"available": True, "enabled": False, "running": False, "error": "", "helper": "not_installed",
                      "volumes": [{"drive": "C:\\", "ntfs": True, "files": 0, "usn_ok": False, "last_scan": None}]}

    def _note(self, *call):
        self.calls.append(call)

    # search
    def search(self, text, filters=None, client=None, channel="main"):
        self._note("search", text, filters)
        if not text.strip() and not filters:
            return {"results": [], "understood": [], "terms": [], "notes": [], "ms": 0}
        return {"results": [dict(RESULT)], "understood": ["pdf"], "terms": ["tax"], "notes": [], "more": False,
                "ms": 4, "parts": [{"kind": "kind", "label": "PDFs", "without": "tax"},
                                   {"kind": "words", "label": "tax", "without": "pdf"}],
                "best": {"id": 7, "reason": "The only match"}}

    def suggest(self, text, channel="main"):
        self._note("suggest", text, channel)
        items = []
        if self.settings.get("search_history") and "tax pdf" in self.history and "tax pdf".startswith(text.lower()):
            items.append({"text": "tax pdf", "kind": "history", "label": "tax pdf", "detail": ""})
        if text.strip():
            items.append({"text": "tax 2025.pdf", "kind": "file", "label": "tax 2025.pdf",
                          "detail": RESULT["dir"], "id": 7})
            items.append({"text": text.rstrip() + " in downloads", "kind": "filter", "label": "in downloads",
                          "detail": "folder"})
        first = next((i["text"] for i in items if i["text"].lower().startswith(text.lower()) and text), "")
        return {"items": items[:5 if channel == "bar" else 8], "complete": text + first[len(text):] if first else ""}

    def history_add(self, text):
        self._note("history_add", text)
        if not self.settings.get("search_history") or len(text.strip()) < 2:
            return {"ok": True, "saved": False}
        self.history.add(text.strip().lower())
        return {"ok": True, "saved": True}

    def history_forget(self, text):
        self._note("history_forget", text)
        known = text.strip().lower() in self.history
        self.history.discard(text.strip().lower())
        return {"ok": known}

    def history_clear(self):
        self._note("history_clear")
        self.history.clear()
        return {"ok": True}

    def open(self, file_id):
        self._note("open", file_id)
        return {"ok": True} if file_id == 7 else {"ok": False, "error": "That file isn't there any more."}

    def open_with(self, file_id):
        self._note("open_with", file_id)
        return {"ok": True} if file_id == 7 else {"ok": False, "error": "That file isn't there any more."}

    def reveal(self, file_id):
        self._note("reveal", file_id)
        return {"ok": True} if file_id == 7 else {"ok": False, "error": "That file isn't there any more."}

    def thumbnail(self, file_id):
        return {"url": "data:image/png;base64,iVBORw0KGgo=" if file_id == 7 else ""}

    def here_folder(self):
        return {"path": self.here}

    def path_of(self, file_id):
        return {"path": RESULT["path"] if file_id == 7 else ""}

    def forget(self, file_id):
        self._note("forget", file_id)
        return {"ok": file_id == 7}

    # status
    def status_brief(self):
        return {"level": self.gov.level, "reason": self.gov.reason, "phase": "text", "files": 1200,
                "paused": self.paused}

    def status(self):
        return dict(STATUS_FULL, level=self.gov.level, reason=self.gov.reason, paused=self.paused)

    def downloads(self):
        return {k: dict(v) for k, v in self.dl.items()}

    def pause_for(self, seconds):
        self._note("pause_for", seconds)
        if not isinstance(seconds, int) or seconds <= 0:
            return {"ok": False}
        self.gov.level, self.gov.reason = "paused", "Paused: you paused NOBAD Find for 60 min"
        return {"ok": True}

    def resume(self):
        self._note("resume")
        self.gov.level, self.gov.reason = "gentle", "Gentle: you're using the PC"
        return {"ok": True}

    def learned_apps(self):
        return [{"exe": "game.exe", "seen": 3, "lag_events": 1, "worst_cpu": 92.0, "worst_gpu": None,
                 "start_level": "light", "last_seen": 1763400000.0, "reason": "It slowed down once while Find worked"}]

    def reset_learned(self, exe=None):
        self._note("reset_learned", exe)
        return {"ok": True}

    def hardware(self):
        return {"ram_gb": 15.7, "cores": 8, "threads": 16, "avx2": True, "avx512_vnni": False,
                "gpu": "Intel(R) Iris(R) Xe Graphics", "vram_gb": 0.1, "directml": False, "disk_free_gb": 120.5,
                "ssd": True}

    # settings
    def get_settings(self):
        return dict(self.settings)

    def set_settings(self, changes, consent=None):
        """Like Settings.update: every value through the real settings.coerce; secret_app_files goes on only with
        the consent word, like Api.set_settings."""
        from nobadfind.const import APP_FILES_CONSENT
        new = {k: coerce(k, v) for k, v in changes.items()
               if k in DEFAULTS and k not in ("wsearch_prev", "turbo", "settings_rev")}
        if new.get("secret_app_files") is True and consent != APP_FILES_CONSENT:
            del new["secret_app_files"]
        changed = [k for k, v in new.items() if self.settings[k] != v]
        self.settings.update(new)
        out = {"changed": changed}
        if set(changed) & {"hotkey", "bar_hotkey", "bar"}:
            out["hotkeys"] = self.hotkey_state()
        return out

    def hotkey_state(self):
        """Both registered, except the bar's when the bar is off (no Windows here: nothing is ever taken)."""
        return {"hotkey": {"spec": self.settings["hotkey"], "state": "ok"},
                "bar_hotkey": {"spec": self.settings["bar_hotkey"], "state": "ok" if self.settings["bar"] else "off"}}

    def hotkey_probe(self, which, spec):
        """The real Api.hotkey_probe's answers, with the real hotkey.reserved and normal (no RegisterHotKey here)."""
        from nobadfind import hotkey
        n = hotkey.normal(spec)
        other = "bar_hotkey" if which == "hotkey" else "hotkey"
        if n is None or hotkey.parse(n) is None:
            state = "invalid"
        elif n == hotkey.normal(self.settings[other]):
            state = "same"
        elif hotkey.reserved(n):
            state = "reserved"
        else:
            state = "ok"
        reason = {"ok": "Free to use.", "invalid": "Use Ctrl, Alt, Shift or Win with a letter, a number, Space or F1 to F12.",
                  "same": "The other NOBAD Find shortcut already uses it.",
                  "reserved": (hotkey.reserved(n or "") or "Windows keeps it for itself") + "."}[state]
        return {"state": state, "spec": n if state != "invalid" else "", "reason": reason}

    def pick_folder(self):
        return {"path": "C:\\Users\\me\\Projects", "busy": False}

    def rescan(self):
        self._note("rescan")
        return {"ok": True}

    def wipe(self, confirm):
        self._note("wipe", confirm)
        return {"ok": confirm == "DELETE"}

    def download_model(self):
        if not self.settings["allow_model_download"]:
            return {"ok": False, "error": "Allow the download in Settings first."}
        self.dl["meaning"].update(state="downloading", got=0, size=0)
        return {"ok": True}

    def download_photo_model(self):
        if not self.settings["allow_photo_model_download"]:
            return {"ok": False, "error": "Allow the photo model download in Settings first."}
        self.dl["photo"].update(state="downloading", got=0, size=0)
        return {"ok": True}

    # model tiers: the real catalog, a fixed PC, nothing downloaded unless the transcript downloads it
    def models(self):
        from nobadfind import models as cat
        pc = self.hardware()
        focus = self.settings.get("language_focus") or "english"
        rec = cat.recommend(pc)
        choice = cat.tier_choice(rec, focus)
        out = []
        rid = "llama-vulkan" if pc.get("gpu") else "llama-cpu"
        for m in cat.CATALOG:
            ok, why = cat.capable(m, pc)
            talk = {"vram_mb": int(m.get("vram_mb") or 0), "runtime": rid} if m["feature"] == "talk" else {}
            if m["builtin"]:
                state = "active" if self.settings.get("ocr") else "ready"
            elif self.dl.get(m["id"], {}).get("state") == "downloading":
                state = "downloading"
            elif m["id"] in self.ready:
                state = "active" if cat.selected(self.settings, m["feature"]) == m["id"] else "ready"
            else:
                state = "not_downloaded"
            out.append({**talk, "id": m["id"], "feature": m["feature"], "name": m["name"], "tier": m["tier"],
                        "licence": m["licence"], "source": m["source"], "size_mb": cat.size_mb(m),
                        "ram_mb": int(m.get("ram_mb") or 0), "speed_note": m.get("speed_note") or "",
                        "languages": list(m.get("languages") or []), "improves": m.get("improves") or "",
                        "builtin": bool(m["builtin"]), "state": state, "capable": ok, "capable_reason": why,
                        "recommended": choice.get(m["feature"]) == m["id"],
                        "quality": dict(m["quality"]) if m.get("quality") else None,
                        "dir": "" if m["builtin"] else "C:\\Users\\me\\AppData\\Local\\NOBAD\\Find\\"
                               + (m.get("dir") or "models\\" + m["id"])})
        return {"pc": pc, "tier_recommended": rec, "tier_current": cat.tier_current(self.settings, focus),
                "language_focus": focus, "models": out}

    def model_use(self, feature, mid):
        from nobadfind import models as cat
        m = cat.get(mid)
        if m is None or m["feature"] != feature:
            return {"ok": False, "error": "There's no such model for that.", "needs_download": False}
        self.set_settings({"text": {"text_model": mid, "semantic": True}, "photo": {"photo_model": mid,
                           "photo_meaning": True}, "ocr": {"ocr": True}}[feature])
        return {"ok": True, "error": "", "needs_download": not m["builtin"] and mid not in self.ready}

    def model_download(self, mid, consent):
        from nobadfind import models as cat
        m = cat.get(mid)
        if m is None or m["builtin"]:
            return {"ok": False, "error": "There's nothing to download for that."}
        if consent != "DOWNLOAD":
            return {"ok": False, "error": "A model is only downloaded when you say Download."}
        self.dl[mid] = {"state": "downloading", "got": 0, "size": sum(f[1] for f in m["files"].values()), "error": ""}
        return {"ok": True}

    def run_action(self, action_id):
        """Like Api.run_action: ids from the launcher's table only (nothing is opened here)."""
        from nobadfind import launcher
        if action_id.startswith("set:") and any("set:" + x[0] == action_id for x in launcher.SETTINGS):
            return {"ok": True, "error": ""}
        return {"ok": False, "error": "That isn't something NOBAD Find can open."}

    def update_state(self):
        """Like Api.update_state with an update found: this is 0.0.0-contract, the newest release 0.9.0."""
        return {"state": "available", "current": "0.0.0-contract", "latest": "0.9.0", "size": 41_000_000, "got": 0, "bps": 0,
                "notes_url": "https://github.com/nobad-studio/find/releases/tag/find-v0.9.0", "error": "",
                "auto": bool(self.settings["update_check"]), "checked_at": 1763600000}

    def update_check(self):
        return {"ok": True}

    def update_install(self, consent):
        if consent != "INSTALL":
            return {"ok": False, "error": "Nothing is installed without your OK."}
        return {"ok": True}

    def model_folder(self, mid):
        """Like Api.model_folder: an id only; a built-in model has no folder (no Explorer here)."""
        from nobadfind import models as cat
        m = cat.get(mid)
        if m is None or m["builtin"]:
            return {"ok": False, "error": "That model is part of Windows: it has no folder of its own."}
        return {"ok": True}

    def model_remove(self, mid):
        from nobadfind import models as cat
        m = cat.get(mid)
        if m is None or m["builtin"]:
            return {"ok": False, "error": "That model is part of Windows or NOBAD Find."}
        if cat.selected(self.settings, m["feature"]) == mid:
            return {"ok": False, "error": "NOBAD Find is using that model. Choose another one first."}
        self.ready.discard(mid)
        return {"ok": True}

    def auto_configure(self):
        from nobadfind import models as cat
        tier = cat.recommend(self.hardware())
        choice = cat.tier_choice(tier, self.settings.get("language_focus") or "english")
        self.set_settings({"text_model": choice["text"], "semantic": True, "ocr": True,
                           "photo_model": choice["photo"] or self.settings["photo_model"],
                           "photo_meaning": bool(choice["photo"])})
        return {"tier": tier, "steps": [{"feature": f, "id": choice[f],
                                         "needs_download": bool(choice[f]) and f != "ocr" and choice[f] not in self.ready}
                                        for f in ("text", "photo", "ocr")]}

    def model_language(self, focus):
        if focus not in ("english", "multilingual", "hindi"):
            return {"ok": False, "error": "Choose English, many languages or Hindi."}
        self.settings["language_focus"] = focus
        return {"ok": True}

    # Windows Search
    def wsearch_state(self):
        return {"start": "delayed-auto", "running": True, "saved": self.settings["wsearch_prev"]}

    def wsearch_set(self, off):
        self._note("wsearch_set", off)
        return {"ok": False, "state": {"start": "delayed-auto", "running": True},
                "error": "Windows didn't make the change (the permission prompt may have been closed)."}

    def use_instead_of_windows_search(self, on):
        return self.wsearch_set(bool(on))

    # what is indexed, and the turbo index
    def scope_info(self):
        mine = self.settings["scope"] == "my_files"
        cats = [dict(c, included=False, locked=True) if mine and c["id"] == "system" else
                dict(c, included=self.settings["include_secrets"]) if c["id"] == "secrets" else dict(c)
                for c in SCOPE_INFO["categories"]]
        return dict(SCOPE_INFO, scope=self.settings["scope"], categories=cats,
                    roots=SCOPE_INFO["roots"][:1] if mine else list(SCOPE_INFO["roots"]))

    def turbo_state(self):
        return dict(self.turbo, enabled=self.settings["turbo"], volumes=[dict(v, usn_ok=v["usn_ok"] and self.turbo["running"])
                                                                  for v in self.turbo["volumes"]])

    def turbo_set(self, on):
        """The permission prompt is answered No for on, like the real one in a test: never a UAC prompt."""
        self._note("turbo_set", on)
        if on:
            self.turbo["error"] = ("Windows didn't get permission (the prompt was closed or answered No). NOBAD Find "
                                   "keeps using its normal folder walk.")
            return {"ok": False, "error": self.turbo["error"], "state": self.turbo_state()}
        self.settings["turbo"] = False
        self.turbo.update(running=False, error="")
        if self.turbo["helper"] != "not_installed":       # removing it asks too: answered No here
            self.turbo["error"] = ("Turbo is off. Its helper is still installed because Windows didn't get "
                                   "permission to remove it; use Remove when you want it gone.")
        for v in self.turbo["volumes"]:
            v["usn_ok"] = False
        return {"ok": True, "error": self.turbo["error"], "state": self.turbo_state()}

    def turbo_helper(self, action):
        """update / remove: the permission prompt is answered No, like the real one in a test."""
        self._note("turbo_helper", action)
        if action == "remove":
            return self.turbo_set(False)
        self.turbo["error"] = ("Windows didn't get permission (the prompt was closed or answered No). NOBAD Find "
                               "keeps using its normal folder walk.")
        return {"ok": False, "error": self.turbo["error"], "state": self.turbo_state()}

    # talk about a photo: ids 7 and 8 are photos, the first job is number 1 (the answer streams as vision events)
    PHOTOS = (7, 8)
    GONE = "This photo is no longer there."

    def _job(self, *call):
        self._note(*call)
        self._jobs = getattr(self, "_jobs", 0) + 1
        return {"ok": True, "error": "", "job": self._jobs}

    def vision_state(self):
        return {"ok": True, "not_now": "", "loaded": "", "busy": False, "job": 0, "running": False,
                "models": [{"id": "smolvlm2-500m", "name": "SmolVLM2 500M", "deeper": False, "ready": True,
                            "missing_mb": 0, "ram_mb": 1000, "vram_mb": 1200, "load_s": 1, "answer_s": [1, 3], "slow_note": "",
                            "can_run": True, "why": ""},
                           {"id": "qwen3vl-2b", "name": "Qwen3-VL 2B", "deeper": True, "ready": False,
                            "missing_mb": 1800, "ram_mb": 3200, "vram_mb": 3500, "load_s": 13, "answer_s": [2, 12], "slow_note": "Slower now: NOBAD Find is in Very light mode.",
                            "can_run": False,
                            "why": "Not enough free memory for this one right now."}],
                "runtime": {"id": "llama-vulkan", "ready": True, "missing_mb": 0}}

    def vision_describe(self, file_id):
        if file_id not in self.PHOTOS:
            return {"ok": False, "error": self.GONE, "job": 0}
        return self._job("vision_describe", file_id)

    def vision_ask(self, file_id, question, deeper=False, more=False):
        if file_id not in self.PHOTOS:
            return {"ok": False, "error": self.GONE, "job": 0}
        if not question.strip():
            return {"ok": False, "error": "Type a question.", "job": 0}
        if deeper:
            return {"ok": False, "job": 0, "error": "To talk about photos, download Qwen3-VL 2B first (1800 MB, once).",
                    "download": [{"id": "qwen3vl-2b", "name": "Qwen3-VL 2B", "size_mb": 1800}]}
        return self._job("vision_ask", file_id, question, more)

    def vision_compare(self, a, b, question=None, deeper=False):
        if a == b:
            return {"ok": False, "error": "Pick a second, different photo to compare.", "job": 0}
        if a not in self.PHOTOS or b not in self.PHOTOS:
            return {"ok": False, "error": self.GONE, "job": 0}
        return self._job("vision_compare", a, b, question)

    def vision_cancel(self):
        self._note("vision_cancel")
        return {"ok": True, "error": "", "job": None}

    def vision_keep(self, file_id, text):
        if file_id not in self.PHOTOS:
            return {"ok": False, "error": self.GONE}
        self._note("vision_keep", file_id, text)
        return {"ok": True, "error": "", "kept": bool(text.strip())}

    # window
    def ui_shown(self):
        self._note("ui_shown")
        return {"ok": True}

    def hide(self):
        self._note("hide")
        return {"ok": True}

    def quit(self):
        self._note("quit")
        if self.on_quit is not None:
            self.on_quit()                      # engine.py: the quitting event, then the engine stops
        return {"ok": True}


SCOPE_INFO = {
    "scope": "whole_pc", "roots": ["C:\\Users\\me", "C:\\"],
    "categories": [
        {"id": "system", "name": "Windows and programs",
         "summary": "Windows itself and installed programs.", "names_only": "none", "why": "Windows itself and installed programs.",
         "examples": ["C:\\Windows", "C:\\Program Files"], "included": True, "locked": False, "count": 412000},
        {"id": "caches", "name": "App data, caches and code folders",
         "summary": "What apps keep for themselves.", "names_only": "some", "why": "Settings and caches apps keep.",
         "examples": ["C:\\Users\\me\\AppData", "...\\node_modules"], "included": True, "locked": False,
         "count": 230000},
        {"id": "secrets", "name": "Keys and password stores",
         "summary": "Keys and password vaults.", "names_only": "all", "why": "Off by default; names only when on.",
         "examples": ["C:\\Users\\me\\.ssh", "...\\vault.kdbx"], "included": False, "locked": False,
         "count": None},
        {"id": "other_profiles", "name": "Other people's files",
         "summary": "Other accounts on this PC.", "names_only": "none", "why": "Never indexed, not even by turbo.",
         "examples": ["C:\\Users\\<another account>", "C:\\System Volume Information"], "included": False,
         "locked": True, "count": 0},
        {"id": "removable", "name": "USB sticks and SD cards",
         "summary": "Drives you plug in.", "names_only": "none", "why": "Indexed while plugged in.",
         "examples": ["E:\\"], "included": False, "locked": False, "count": None},
        {"id": "network", "name": "Network drives", "summary": "Mapped network drives.",
         "names_only": "none", "why": "Mapped network drives.", "examples": ["Z:\\"],
         "included": False, "locked": False, "count": None}]}

STATUS_FULL = {
    "phase": "text", "files": 1200, "texts": 310, "vectors": 0, "paused": "", "rate": 0, "errors": 0,
    "plan": {"cpu": 16, "ssd": True, "walk_threads": 32, "text_workers": 8, "text_workers_idle": 15},
    "last_scan": 1763400000.0,
    "with_text": 310, "chunks": 900, "name_vectors": 0, "photo_vectors": 0, "encrypted": True, "db_bytes": 5242880,
    "version": "0.7.0",
    "model": {"state": "missing", "got": 0, "size": 0, "error": ""},
    "photo_model": {"state": "missing", "got": 0, "size": 0, "error": ""},
    "memory_mb": 180, "models_loaded": [], "admin": False, "roots": ["C:\\Users\\me"], "ocr": True,
    "drives": [{"root": "C:\\", "type": "fixed", "label": "Windows", "present": True}],
    "level": "gentle", "reason": "Gentle: you're using the PC",
    "history": [{"t": 1763400000.0, "cpu": 12.5, "gpu": 3.0, "find_cpu": 4.0, "find_mb": 180, "level": "gentle"}],
    "resources": {"cpu": 4.0, "memory_mb": 180, "read_mb_s": 1.5, "gpu": 3.0,
                  "processes": [{"name": "NOBAD Find engine", "role": "engine",
                                 "about": "The main process: the index, searching, watching folders and choosing "
                                          "the pace.", "pid": 100, "cpu": 2.0, "memory_mb": 120, "private_mb": 140,
                                 "age_s": 600, "readable": True, "note": ""},
                                {"name": "Text reader worker", "role": "text",
                                 "about": "Reads the words inside documents, and inside pictures with Windows OCR.",
                                 "pid": 101, "cpu": 2.0, "memory_mb": 60, "private_mb": 45, "age_s": 30,
                                 "readable": True, "note": ""}]},
    "phases": [{"id": "names", "label": "Finding file names", "state": "done", "done": 1200, "total": None,
                "rate": 0.0, "eta_s": None},
               {"id": "text", "label": "Reading documents", "state": "running", "done": 310, "total": 800,
                "rate": 5.0, "eta_s": 98},
               {"id": "ocr", "label": "Reading words in pictures", "state": "waiting", "done": 0, "total": 40,
                "rate": 0.0, "eta_s": None},
               {"id": "meaning", "label": "Learning what files mean", "state": "off", "done": 0, "total": 0,
                "rate": 0.0, "eta_s": None},
               {"id": "photos", "label": "Looking at photos", "state": "off", "done": 0, "total": 0,
                "rate": 0.0, "eta_s": None},
               {"id": "watching", "label": "Watching for changes", "state": "waiting", "done": 0, "total": None,
                "rate": 0.0, "eta_s": None}],
    "models": [{"id": "meaning", "name": "Meaning search (all-MiniLM-L6-v2)", "license": "Apache-2.0", "size_mb": 87,
                "on_disk": False, "loaded": False, "memory_mb": None, "device": "CPU", "items": 0, "download": None},
               {"id": "photo", "name": "Photo search (SigLIP base)", "license": "Apache-2.0", "size_mb": 211,
                "on_disk": False, "loaded": False, "memory_mb": None, "device": "CPU", "items": 0, "download": None},
               {"id": "ocr", "name": "Windows OCR", "license": "Windows", "size_mb": 0, "on_disk": True,
                "loaded": False, "memory_mb": None, "device": "Windows", "items": 0, "download": None}],
    "activity": [{"t": 1763400000.0, "kind": "level", "text": "Gentle: you're using the PC"}],
}


class Conn:
    """A client connection that keeps what the engine sent it."""

    def __init__(self, pid=4242):
        self.events, self.shown, self.sent, self.pid, self.alive = set(), set(), [], pid, True

    def send(self, obj):
        self.sent.append(obj)
        return True


class Engine:
    """FakeApi + the real Events and handlers for one connection; `trigger` plays the engine-side lines."""

    def __init__(self):
        self.api = FakeApi()
        self.conn = Conn()
        self.activity = Activity(clock=lambda: 1763400000.0)
        self.events = Events(lambda: [self.conn], lambda c: None, self.api, every=2.0)
        self.activity.listen(self.events.activity)
        self.api.on_quit = self.events.quitting
        self.methods = handlers.methods(self.api, self.events,
                                        lambda: {"app": "NOBAD Find", "version": "0.0.0-contract", "pid": 4242})

    _upd = None
    _update_at = 0.0

    def _updater(self):
        if self._upd is None:
            from nobadfind.update import Updater
            u = Updater(self.api.settings, data_dir=os.devnull, get=lambda *a, **k: None, start=lambda a: None,
                        current="0.0.0-contract", mono=lambda: self._update_at)
            u.release = {"version": "0.9.0", "size": 41_000_000, "notes_url": UPDATE_NOTES}
            u.checked_at = 1763600000
            u.on_change = self.events.update
            self._upd = u
        return self._upd

    def trigger(self, t):
        do = t["do"]
        if do == "tick":
            self.events.step(t["at"])
        elif do == "level":
            self.api.gov.level, self.api.gov.reason = t["level"], t["reason"]
        elif do == "activity":
            self.activity.add(t["kind"], t["text"])
        elif do == "download":
            self.api.dl.setdefault(t["id"], {"state": "missing", "got": 0, "size": 0, "error": ""}).update(
                {k: t[k] for k in ("state", "got", "size", "error") if k in t})
            if t.get("state") == "ready":
                self.api.ready.add(t["id"])
        elif do == "hotkey":
            self.events.show(t["what"])
        elif do == "here":
            self.api.here = t["path"]
            self.events.here(t["path"])
        elif do == "notice":
            self.events.notice(t["text"])
        elif do == "quitting":
            self.events.quitting()
        elif do == "turbo":
            self.api.turbo.update({k: t[k] for k in ("running", "error", "helper") if k in t})
            if t.get("running"):
                self.api.settings["turbo"] = True          # the user said yes at the prompt
            if "volume" in t:
                self.api.turbo["volumes"] = [dict(t["volume"])]
            self.events.turbo(self.api.turbo_state())
        elif do == "vision":
            self.events.push("vision", t["event"])
        elif do == "update":
            # a real update.Updater on a fake clock: the download's progress throttle and speed are the engine's own
            u = self._updater()
            if "at" in t:
                self._update_at = t["at"]
            if t.get("state") == "downloading":
                u.got, u.bps, u._samples, u._sent_at = 0, 0, [], None
            if "got" in t:
                u._progress(t["got"])
            elif "state" in t:
                u._set(t["state"])
        else:
            raise ValueError(f"unknown engine trigger {do!r}")
