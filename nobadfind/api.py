"""The methods the UI can call (through the pipe handlers in nobadfind/rpc). Every argument from the UI is checked here.

The UI never hands the engine a path to open: it sends a result id, and the path comes from the index.
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque

from . import embed, jobs, models, ocr, photo, procs, scope, thumbs, wsearch, winapi
from . import hardware as hw
from .const import APP_VER
from .indexer import NAME_KINDS
from .kinds import READABLE_EXT
from .log import log
from .search import SORTS, search
from .vlm import runtime as vlm_runtime
from .vlm.worker import GONE as VISION_GONE, MAX_IMAGES

MAX_QUERY = 500
TOTALS_TTL = 10                  # seconds: the phase counts are COUNT queries, too heavy for every 2 s poll
STATS_TTL = 10                   # seconds the index counts (Store.stats) are reused by status()
COUNT_SHARE = 20                 # and at least 20x as long as they took to count: <= 5% of a core on a big index
RATE_WINDOW = 15                 # status polls a progress rate is measured over (about 30 s)
MAX_PAUSE_S = 24 * 3600
QUIT_TIMEOUT = 15                # seconds a quit may take before the process ends anyway
PHASES = (("names", "Finding file names"), ("text", "Reading documents"), ("ocr", "Reading words in pictures"),
          ("meaning", "Learning what files mean"),
          ("rebuild", "Rebuilding meaning for the new model"),          # a switched text model (indexer._rebuild)
          ("photos", "Looking at photos"), ("watching", "Watching for changes"))


class Api:
    def __init__(self, store, settings, indexer, vindex):
        self._store = store
        self._settings = settings
        self._indexer = indexer
        self._vindex = vindex
        self.here = ""                    # the Explorer folder the hotkey was pressed in (engine.here_finder)
        self._model = {"state": "ready" if embed.model_ready() else "missing", "got": 0, "size": 0, "error": ""}
        self._photo_model = {"state": "ready" if photo.model_ready() else "missing", "got": 0, "size": 0, "error": ""}
        self._governor = None             # set by engine.py (the status page reads the governor, the activity log,
        self._activity = None             # and what was learned about apps); None in tests
        self._apps = None
        self._slock = threading.Lock()
        self._totals = (0.0, None, {})    # (computed at, settings key, counts)
        self._refresher = None
        self._clock = time.monotonic      # tests replace it
        self._prev = None                 # (time, cpu_seconds, read_bytes) of the last status() call
        self._sampler = procs.Sampler()   # Find's own processes, what each is and what it uses
        self._ui_pids = None              # engine.py: the pipe's clients (Rpc.ui_pids)
        self._progress = {k: deque(maxlen=RATE_WINDOW) for k, _l in PHASES}
        self._rate = DownloadRate()       # the download speed on the model cards
        self._on_hide = None              # engine.py: what hiding the window means for indexing (lifecycle.after_hide)
        self._on_show = None              # engine.py: the UI's main window came up (indexing resumes)
        self._folder_dialog = None        # engine.py: Windows' own folder dialog
        self._turbo = None                # engine.py: turbo.Turbo, the optional elevated NTFS index helper
        self._timer, self._exit = threading.Timer, os._exit     # tests replace them
        self._talk = None                 # vlm.worker.Talker, made on the first talk-about-a-photo question
        self._talk_lock = threading.Lock()
        self._on_vision = None            # engine.py: push one `vision` event to the UI
        self._on_talk_budget = None       # engine.py: jobs.set_talk_allowance (the talk model's memory)

    # ---------- search ----------
    def search(self, text, filters=None, client=None, channel="main"):
        """client: who asked (one pipe connection); channel: which of its searches ("main" box, "home" list,
        "bar"). A newer search on the same client and channel cancels this one: its answer would only be thrown
        away, and on a whole-PC index the old one may still be running. Other channels are left alone."""
        empty = {"results": [], "understood": [], "terms": [], "notes": [], "ms": 0}
        cancelled = None
        if client is not None:
            seqs = self.__dict__.setdefault("_search_seq", {})
            key = (client, channel)
            seqs[key] = mine = seqs.get(key, 0) + 1
            cancelled = (lambda: seqs.get(key) != mine)          # noqa: E731 (a newer search came in)
        if not isinstance(text, str):
            return empty
        text = text.strip()[:MAX_QUERY]
        filters = filters if isinstance(filters, dict) else {}
        listing = any(filters.get(k) for k in ("kind", "modified", "size", "folder")) or filters.get("sort") in SORTS - {""}
        if not text and not listing:
            return empty
        try:
            asks = {}
            # the settings and apps first (a few ms): "open windows update" + Enter waits for this answer, so a
            # question that asks to open one of them skips the meaning and photo models (seconds on a big index);
            # its files are still found by name and words
            acts = self.actions_for(text) if channel != "home" else []
            quick = bool(acts) and self._launch_question(text)
            r = search(self._store, text, None if quick else self._indexer.embedder, None if quick else self._vindex,
                       drives=self._indexer.drive_list, here=self.here, filters=filters,
                       roots=self._indexer.roots(self._indexer.drive_list),
                       photo_text=None if quick else self._indexer.photo_text,
                       pindex=None if quick else self._indexer.pindex, cancelled=cancelled,
                       romanized=self._romanized(), asks=asks)
            if not r.get("cancelled"):
                needs = [] if quick else self._needs(asks, len(r.get("results") or ()))
                if needs:
                    r["needs"] = needs
                if acts:
                    r["actions"] = acts
            return r
        except Exception as e:
            log(f"search failed: {type(e).__name__}", "warn")
            return {"results": [], "understood": [], "terms": [], "ms": 0, "error": "Search failed. Try other words."}

    # ---------- Windows settings and apps from the search box (0.9.1, launcher.py) ----------
    def actions_for(self, text):
        lch = getattr(self, "_launcher", None)
        if lch is None or not text:
            return []
        try:
            return lch.actions(text)
        except Exception as e:
            log(f"actions failed: {type(e).__name__}", "warn")
            return []

    def _launch_question(self, text):
        lch = getattr(self, "_launcher", None)
        try:
            return lch is not None and lch.wants(text)
        except Exception:
            return False

    def run_action(self, action_id):
        """Open a Windows Settings page, a Windows tool or an app, by the id search gave (never a path)."""
        lch = getattr(self, "_launcher", None)
        if lch is None:
            return {"ok": False, "error": "Opening apps and settings isn't available in this copy of NOBAD Find."}
        return lch.run(action_id)

    def _needs(self, asks, found):
        """What this search would need that isn't ready (0.9.0), for a hint above the results. Cheap: the photo
        counts come from the Index page's cached totals, never a count over the index per keystroke.
        photo: the model is missing (offer the download), off (offer to switch it on), or still looking at photos.
        meaning: only when a description found little and meaning search is missing or off."""
        out, s = [], self._settings
        if asks.get("photo"):
            pid = self._photo_in_use()
            spec = models.get(pid) or {}
            mb = models.size_mb(spec) if spec else 0
            pindex = getattr(self._indexer, "pindex", None)
            ready_n = int(getattr(pindex, "n", 0) or 0)
            if not models.ready(pid, self._mdir()):
                left = models.missing_mb(pid, self._mdir()) or mb
                what = (f"an update of its photo model ({left} MB to download)" if left < mb
                        else f"its photo model ({left} MB, downloaded once)")
                out.append({"model": "photo", "state": "missing", "id": pid, "size_mb": left, "done": 0, "total": 0,
                            "text": f"To find what is in your photos, NOBAD Find needs {what}. Until then it only "
                                    "matches names and words in pictures."})
            elif not s.get("photo_meaning"):
                out.append({"model": "photo", "state": "off", "id": pid, "size_mb": mb, "done": 0, "total": 0,
                            "text": "Photo search is off, so only names and words in pictures are matched. "
                                    "Turn it on to search what is in them."})
            else:
                total, todo = (getattr(self, "_totals", (0, None, {}))[2] or {}).get("photos", (0, 0))
                where = asks.get("where")
                if where and where[0] and asks.get("roots") and self._store is not None:
                    # a folder (or time) was asked: count the photos that fit, and look at those first
                    try:
                        from . import photo as ph
                        marks = ",".join("?" * len(ph.PHOTO_EXT))
                        row = self._store.q(
                            f"SELECT count(*), sum(CASE WHEN p.file_id IS NOT NULL AND length(p.v) > 0 THEN 1 ELSE 0 END) "
                            f"FROM files f LEFT JOIN pvecs p ON p.file_id = f.id WHERE f.ext IN ({marks}) "
                            f"AND f.size BETWEEN ? AND ?{where[0]}",
                            (*sorted(ph.PHOTO_EXT), ph.MIN_PHOTO_BYTES, ph.MAX_PHOTO_BYTES, *where[1]))[0]
                        total, done = int(row[0] or 0), int(row[1] or 0)
                        todo, ready_n = total - done, done
                    except Exception as e:
                        log(f"photo progress count failed: {type(e).__name__}", "warn")
                    if todo > 0 and asks.get("roots"):
                        hurry = getattr(self._indexer, "hurry_photos", None)
                        if hurry is not None:
                            hurry(asks["roots"])
                if todo > 0 or ready_n == 0:
                    shown = max(int(total), ready_n)
                    text = (f"Still looking at your photos: {ready_n:,} of {shown:,} done. "
                            "Photo results get better as it goes." if shown
                            else "NOBAD Find hasn't looked at your photos yet. Photo results come as it does.")
                    out.append({"model": "photo", "state": "analyzing", "id": pid, "size_mb": mb,
                                "done": ready_n, "total": shown, "text": text})
        if asks.get("meaning") and not asks.get("photo") and found < 5:
            mid = self._text_in_use()
            spec = models.get(mid) or {}
            mb = models.size_mb(spec) if spec else 0
            if not models.ready(mid, self._mdir()):
                out.append({"model": "meaning", "state": "missing", "id": mid, "size_mb": mb, "done": 0, "total": 0,
                            "text": f"Search by meaning finds files by what they are about (\u201crent\u201d finds "
                                    f"\u201clease\u201d). It needs a {mb} MB model, downloaded once."})
            elif not s.get("semantic"):
                out.append({"model": "meaning", "state": "off", "id": mid, "size_mb": mb, "done": 0, "total": 0,
                            "text": "Search by meaning is off, so only names and words are matched. Turn it on to "
                                    "find files by what they are about."})
        return out

    # ---------- smart search (0.8.5): suggestions while typing, your own search history ----------
    def suggest(self, text, channel="main"):
        """Autocomplete (suggest.py): your past questions (when search_history is on), names in the index and the
        phrases search understands. Never fails a keystroke: a problem gives no suggestions."""
        from . import suggest as sg
        from .understand import place_bases
        if not isinstance(text, str):
            return {"items": [], "complete": ""}
        try:
            drives = self._indexer.drive_list
            bases = place_bases(self._indexer.roots(drives), drives)
            return sg.suggest(self._store, text[:MAX_QUERY], history_on=bool(self._settings.get("search_history")),
                              limit=5 if channel == "bar" else 8, bases=bases, drives=drives)
        except Exception as e:
            log(f"suggest failed: {type(e).__name__}", "warn")
            return {"items": [], "complete": ""}

    def history_add(self, text):
        """The UI says a question was used (Enter, a result opened, a suggestion picked): kept for autocomplete,
        only while search_history is on."""
        from . import history
        if not self._settings.get("search_history"):
            return {"ok": True, "saved": False}
        return {"ok": True, "saved": history.add(self._store, text)}

    def history_forget(self, text):
        from . import history
        return {"ok": history.forget(self._store, text)}

    def history_clear(self):
        from . import history
        history.clear(self._store)
        return {"ok": True}

    def _path(self, file_id):
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            return None
        p = self._store.one("SELECT path FROM files WHERE id=?", (file_id,))
        return p if p and os.path.exists(p) else None

    def open(self, file_id):
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        try:
            winapi.open_outside_job(p)    # the default program, outside Find's job: it survives Quit
            return {"ok": True}
        except OSError as e:
            log(f"could not open the file outside NOBAD Find's process group (error {e.winerror or e.errno}); "
                "opened it directly, so it closes if NOBAD Find quits", "warn")
        try:
            os.startfile(p)               # noqa: the default program for this file, as the normal user
            return {"ok": True}
        except OSError as e:
            return {"ok": False, "error": e.strerror or "Windows couldn't open it."}

    def open_with(self, file_id):
        """Windows' "Open with" picker for a result (by id only). It runs in a small helper started outside Find's
        job, so the program picked there (its child) survives Quit like a file opened with open()."""
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        try:
            winapi.start_outside_job(winapi.self_command("--open-with", p))
            return {"ok": True, "error": ""}
        except OSError as e:
            log(f"could not start the Open with picker (error {e.winerror or e.errno})", "warn")
            return {"ok": False, "error": "Windows couldn't show the Open with list."}

    def reveal(self, file_id):
        p = self._path(file_id)
        if not p:
            return {"ok": False, "error": "That file isn't there any more."}
        return {"ok": reveal_in_explorer(p)}

    def thumbnail(self, file_id):
        """A small preview of one result (photo, video, PDF) from Windows' thumbnail cache, or ""."""
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            return {"url": ""}
        row = self._store.q("SELECT path, kind, mtime FROM files WHERE id=?", (file_id,))
        if not row or row[0][1] not in thumbs.KINDS:
            return {"url": ""}
        if scope.Rules.from_settings(self._settings).names_only(row[0][0]):
            return {"url": ""}                      # a preview is the content: secrets are names only
        return {"url": thumbs.data_url(row[0][0], row[0][2])}

    def here_folder(self):
        """For the filter bar: the folder "here" means right now ('' if NOBAD Find wasn't opened from one)."""
        return {"path": self.here}

    def path_of(self, file_id):
        p = self._path(file_id)
        return {"path": p or ""}

    def forget(self, file_id):
        """Remove a file or folder from the index and keep it out from now on."""
        if not isinstance(file_id, int):
            return {"ok": False}
        p = self._store.one("SELECT path FROM files WHERE id=?", (file_id,))
        if not p:
            return {"ok": False}
        from .settings import MAX_PATHS
        keep = os.path.normpath(p)
        old = list(self._settings.get("exclude") or [])
        if keep not in old:
            if len(old) >= MAX_PATHS:            # security review 2026-11-22 (M4): never ok without keeping it out
                return {"ok": False, "error": f"The Never index list is full ({MAX_PATHS} entries). Remove some "
                                              "in Settings > What to index, or forget the folder instead."}
            try:
                self._settings.update({"exclude": old + [keep]})
            except OSError:
                return {"ok": False, "error": "NOBAD Find couldn't save the Never index list."}
            if keep not in (self._settings.get("exclude") or []):
                return {"ok": False, "error": "NOBAD Find couldn't add it to the Never index list."}
            self._note_forgotten(keep)
        self._store.forget_path(p)
        return {"ok": True}

    FORGOTTEN = "forgotten"                     # meta: the Never index entries Forget added (JSON list), for Wipe

    def _forgotten(self):
        try:
            v = json.loads(self._store.meta(self.FORGOTTEN, "[]") or "[]")
        except ValueError:
            v = []
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def _note_forgotten(self, path):
        """Remember, inside the encrypted index, that Forget (not the user's folder list) added path to exclude."""
        try:
            got = self._forgotten()
            if path not in got:
                self._store.set_meta(self.FORGOTTEN, json.dumps((got + [path])[-20000:]))
        except Exception as e:
            log(f"forget: not noted for Wipe ({type(e).__name__})", "warn")

    # ---------- status and settings ----------
    def status(self):
        st = dict(self._indexer.status)
        st.update(self._stats())
        st["version"] = APP_VER
        st["model"] = self._feature_dl("text")
        st["photo_model"] = self._feature_dl("photo")
        st["memory_mb"] = winapi.memory_mb()
        st["models_loaded"] = self._indexer.models_loaded()
        st["admin"] = winapi.is_admin()
        st["roots"] = self._indexer.roots()
        st["ocr"] = ocr.available() or ocr.why_missing()
        st["drives"] = self._indexer.drive_list
        with self._slock:
            self._transparency(st)
        return st

    def _stats(self):
        """Store.stats (six COUNTs over the whole index: seconds on a whole PC), reused for STATS_TTL seconds or
        COUNT_SHARE times as long as the last count took, whichever is longer."""
        at, ttl, cached = getattr(self, "_stats_cache", (None, 0.0, None))
        now = self._clock()
        if cached is not None and now - at < ttl:
            return cached
        cached = self._store.stats()
        took = self._clock() - now
        self._stats_cache = (now, max(STATS_TTL, COUNT_SHARE * took), cached)
        return cached

    def status_brief(self):
        """The few status fields a status line needs, cheap enough for every 2 s (the pipe's status event)."""
        st = self._indexer.status
        gov = self._governor
        if gov is not None:
            level, reason = gov.decision.level, gov.decision.reason
        else:
            level, reason = st.get("level", ""), st.get("reason", "")
        files = st.get("files", 0)
        return {"level": str(level or ""), "reason": str(reason or ""), "phase": str(st.get("phase") or ""),
                "files": int(files) if isinstance(files, (int, float)) and not isinstance(files, bool) else 0,
                "paused": str(st.get("paused") or "")}

    # ---------- transparency: what NOBAD Find is doing, what it uses, and why ----------
    def _transparency(self, st):
        now = self._clock()
        gov = self._governor
        if gov is not None:
            st["level"], st["reason"] = gov.decision.level, gov.decision.reason
            st["history"] = gov.history
        else:
            st["level"], st["reason"], st["history"] = st.get("level", ""), st.get("reason", ""), []
        history = st["history"]
        st["resources"] = self._resources(now, history[-1].get("gpu") if history else None)
        st["phases"] = self._phases(now, st)
        st["models"] = self._models(now, st, st["resources"]["processes"])
        st["activity"] = self._activity.recent(50) if self._activity is not None else []

    def _known_roles(self):
        """{pid: role id} the engine is sure of: its pools' workers and the turbo helper (procs.ROLES)."""
        known = {}
        try:
            known.update({pid: procs.WORKER_NAMES.get(n, "other") for pid, n in self._indexer.worker_names().items()})
        except Exception:
            pass
        known.update({pid: "talk" for pid in self.vision_pids()})
        try:
            tpid = self._turbo.helper_pid() if self._turbo is not None else 0
        except Exception:
            tpid = 0
        if tpid:
            known[int(tpid)] = "turbo"
        return known

    def _resources(self, now, gpu):
        """Totals and one row per process of Find's own (procs.Sampler): the workers in its job, the UIs, the
        turbo helper, Python's helpers. Sampled at most every procs.EVERY seconds."""
        job = jobs.OUTER.pids() if jobs.OUTER is not None else []
        try:
            ui = set(self._ui_pids() if self._ui_pids is not None else ())
        except Exception:
            ui = set()
        rows = self._sampler.sample(now, os.getpid(), job, self._known_roles(), ui)
        out = [{k: v for k, v in r.items() if k != "in_job"} for r in rows]
        use = jobs.OUTER.usage() if jobs.OUTER is not None else {"cpu_seconds": 0.0, "read_bytes": 0}
        prev, self._prev = self._prev, (now, use["cpu_seconds"], use["read_bytes"])
        cpu, read = 0.0, 0.0
        if prev and now > prev[0]:
            cores = os.cpu_count() or 1
            cpu = max(0.0, min(100.0, (use["cpu_seconds"] - prev[1]) / (now - prev[0]) / cores * 100))
            read = max(0.0, (use["read_bytes"] - prev[2]) / (now - prev[0]) / 1048576)
        if jobs.OUTER is not None:
            cpu += sum(r["cpu"] for r in rows if not r["in_job"])      # the UIs run outside the job
        else:
            cpu = sum(r["cpu"] for r in rows)
        return {"cpu": round(min(100.0, cpu), 1), "memory_mb": sum(p["memory_mb"] for p in out),
                "read_mb_s": round(read, 2), "gpu": gpu, "processes": out}

    def _counts(self, now):
        """(total, still to do) for each phase that counts files (cached TOTALS_TTL seconds)."""
        key = (self._settings.get("content_max_mb"), self._settings.get("src_mail"))
        at, k, counts = self._totals
        ttl = max(TOTALS_TTL, COUNT_SHARE * getattr(self, "_totals_took", 0.0))
        # Never inline, not even the first time (0.9.0): on a million-entry index the counts take seconds, and every
        # status poll that waited for them held one of the pipe's few request threads, so the Index page and then
        # the Settings pages stayed blank. Until the first count is in, the phases say "waiting" with no total.
        if (not counts or k != key or now - at >= ttl) and not (self._refresher and self._refresher.is_alive()):
            self._refresher = threading.Thread(target=self._refresh, args=(now, key), daemon=True, name="counts")
            self._refresher.start()                         # the COUNT queries never hold up a status poll
        return counts

    def _refresh(self, now, key):
        s, st = self._settings, self._store
        counts = self._totals[2]
        text_ext = set(READABLE_EXT)
        if not s.get("src_mail"):
            text_ext -= {".eml", ".mbox"}
        mx = s.get("content_max_mb") * 1024 * 1024
        t0 = time.monotonic()
        try:
            counts = {"text": (st.count_readable(text_ext, mx), st.count_needs_text(text_ext, mx)),
                      "ocr": (st.count_readable(ocr.OCR_EXT, mx, ocr.MIN_IMAGE_BYTES),
                              st.count_needs_text(ocr.OCR_EXT, mx, ocr.MIN_IMAGE_BYTES)),
                      "meaning": ((st.one("SELECT count(*) FROM chunks") or 0) + st.count_names(NAME_KINDS),
                                  st.count_chunks_without_vectors() + st.count_names_without_vectors(NAME_KINDS)),
                      "photos": (st.count_photos(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES),
                                 st.count_photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES))}
            if st.meta("vec_model_next"):
                counts["rebuild"] = ((st.one("SELECT count(*) FROM chunks") or 0) + st.count_names(NAME_KINDS),
                                     st.count_chunks_without_vectors(next=True)
                                     + st.count_names_without_vectors(NAME_KINDS, next=True))
        except Exception as e:
            log(f"status counts failed: {type(e).__name__}", "warn")
            counts = counts or {p: (0, 0) for p in ("text", "ocr", "meaning", "photos")}
        self._totals_took = time.monotonic() - t0
        self._totals = (now, key, counts)
        return counts

    def _phases(self, now, st):
        s = self._settings
        counts = self._counts(now)
        cur = {"images": "ocr"}.get(st.get("phase"), st.get("phase"))
        content = bool(s.get("content"))
        on = {"names": True, "text": content, "ocr": content and bool(s.get("ocr")) and bool(ocr.available()),
              "meaning": bool(s.get("semantic")) and models.ready(self._text_in_use(), self._mdir()),
              "photos": bool(s.get("photo_meaning")) and models.ready(self._photo_in_use(), self._mdir()),
              "watching": True,
              "rebuild": cur == "rebuild" or "rebuild" in counts}
        counter = {"text": "texts", "ocr": "texts", "meaning": "vectors", "photos": "photos", "rebuild": "rebuilt"}
        counting = not counts                     # the first count is still running: nothing is known to be done
        out = []
        for pid, label in PHASES:
            total = remaining = None
            if pid in counts:
                total, remaining = counts[pid]
            done = max(0, total - remaining) if total is not None else (st.get("files", 0) if pid == "names" else 0)
            hist = self._progress[pid]
            if not on[pid]:
                state = "off"
            elif cur == pid:
                state = "running"
            elif pid == "names":
                state = "waiting" if cur in ("starting", "error", None) else "done"
            elif pid == "watching":
                state = "waiting"
            elif counting and pid in counter:
                state = "waiting"
            else:
                state = "done" if not remaining else "waiting"
            if state == "running" and pid in counter:
                hist.append((now, st.get(counter[pid], 0)))
            else:
                hist.clear()                  # a rate only uses samples from while the phase ran
            rate = 0.0
            if state == "running" and len(hist) > 1 and hist[-1][0] > hist[0][0]:
                rate = max(0.0, (hist[-1][1] - hist[0][1]) / (hist[-1][0] - hist[0][0]))
            eta = int(remaining / rate) if rate > 0 and remaining else None
            out.append({"id": pid, "label": label, "state": state, "done": int(done),
                        "total": int(total) if total is not None else None, "rate": round(rate, 2), "eta_s": eta})
        return out

    def _download(self, mid, m, now):
        return self._rate.sample(mid, m, now)

    def _feature_dl(self, feature):
        """The download state shown under the plain "meaning" / "photo" names (status model / photo_model, the
        Index page's cards, the Welcome screen): the old fixed download while it runs, else the model in use for
        the feature, which the Welcome and Index buttons get with model_download."""
        legacy = self._model if feature == "text" else self._photo_model
        if legacy["state"] == "downloading":
            return dict(legacy)
        mid = self._text_in_use() if feature == "text" else self._photo_in_use()
        d = getattr(self, "_mdl", {}).get(mid)
        if d:
            return dict(d)
        ready = models.ready(mid, self._mdir())
        return {"state": "ready" if ready else "missing", "got": 0, "size": 0,
                "error": "" if ready else legacy.get("error", "")}

    def downloads(self):
        """Each model download's state ({"state", "got", "size", "error"}, bytes), for the pipe's download event:
        meaning / photo (the model in use for the feature, or the old download_model / download_photo_model while
        one runs) and every model_download by its model id."""
        out = {"meaning": self._feature_dl("text"), "photo": self._feature_dl("photo")}
        out.update({mid: dict(st) for mid, st in getattr(self, "_mdl", {}).items()})
        return out

    def _models(self, now, st, procs):
        """Cards describe the model doing the work (its worker process), else the in-process query encoder."""
        ix = self._indexer
        emb, pho = getattr(ix, "embedder", None), getattr(ix, "photo_text", None)
        worker = {p["role"]: p for p in procs}.get
        mw, pw = worker("meaning"), worker("photo")
        try:
            mdev = ix.meaning_device()
        except Exception:
            mdev = None
        mdev = mdev or ("GPU" if getattr(emb, "device", "CPU") == "GPU" else "CPU")
        pdev = "GPU" if getattr(pho, "device", "CPU") == "GPU" else "CPU"
        enc = [(emb, mw), (pho, pw)]
        mem = [w["memory_mb"] if w else None for _e, w in enc]
        tm, pm = models.get(self._text_in_use()), models.get(self._photo_in_use())
        ocr_total, ocr_left = self._counts(now).get("ocr", (0, 0))
        return [
            {"id": "meaning", "name": f"Meaning search ({tm['name']})", "license": tm["licence"],
             "size_mb": models.size_mb(tm), "on_disk": models.ready(tm["id"], self._mdir()),
             "loaded": bool(mw) or bool(getattr(emb, "loaded", False)), "memory_mb": mem[0],
             "device": mdev,
             "items": int(st.get("vectors", 0)) + int(st.get("name_vectors", 0)),
             "download": self._download("meaning", self._feature_dl("text"), now)},
            {"id": "photo", "name": f"Photo search ({pm['name']})", "license": pm["licence"],
             "size_mb": models.size_mb(pm), "on_disk": models.ready(pm["id"], self._mdir()),
             "loaded": bool(pw) or bool(getattr(pho, "loaded", False)), "memory_mb": mem[1],
             "device": pdev,
             "items": int(st.get("photo_vectors", 0)),
             "download": self._download("photo", self._feature_dl("photo"), now)},
            {"id": "ocr", "name": "Windows OCR", "license": "Windows", "size_mb": 0, "on_disk": bool(ocr.available()),
             "loaded": False, "memory_mb": None, "device": "Windows", "items": max(0, ocr_total - ocr_left),
             "download": None},
        ]

    # ---------- governor controls ----------
    def pause_for(self, seconds):
        if self._governor is None or not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
            return {"ok": False}
        self._governor.pause_for(min(seconds, MAX_PAUSE_S))
        return {"ok": True}

    def resume(self):
        if self._governor is None:
            return {"ok": False}
        self._governor.resume()
        return {"ok": True}

    def learned_apps(self):
        return self._apps.list() if self._apps is not None else []

    def reset_learned(self, exe=None):
        if self._apps is None or not (exe is None or isinstance(exe, str)):
            return {"ok": False}
        self._apps.reset(exe)
        return {"ok": True}

    def hardware(self):
        return hw.scan()

    def get_settings(self):
        return self._settings.all()

    def set_settings(self, changes):
        if not isinstance(changes, dict):
            return {"changed": []}
        changes = {k: v for k, v in changes.items()
                   if k not in ("wsearch_prev", "turbo", "settings_rev")}   # turbo: turbo_set (UAC); rev: engine only
        changes = scope.derive_changes(changes, self._settings.all())     # an older UI only sends roots
        changed = self._settings.update(changes)
        if "autostart" in changed:
            set_autostart(self._settings.get("autostart"))
        # 0.9.3: work on the index waits for its write lock (an indexing batch can hold it for seconds), so it
        # runs after the answer: the switch takes at once and the work follows in order (self._later).
        if "search_history" in changed and not self._settings.get("search_history"):
            self._later(self.history_clear)          # off: what was kept goes now, not later
        if "include_secrets" in changed and not self._settings.get("include_secrets"):
            self._later(self._remove_secrets)        # off: their names leave the index now, not at the next walk
        if set(changed) & {"roots", "exclude", "scope", "include_system", "include_caches", "include_secrets"}:
            self._indexer.rescan()
        for key, kind in (("index_removable", "removable"), ("index_network", "network")):
            if key in changed:
                if not self._settings.get(key):          # turned off: those drives leave the index
                    roots = [d["root"].rstrip("\\") for d in self._indexer.drive_list if d.get("type") == kind]
                    self._later(lambda r=roots: self._store.remove_paths(r))
                self._indexer.wake.set()
        if "photo_model" in changed and self._settings.get("photo_meaning") and "photo_meaning" not in changed:
            threading.Thread(target=self._indexer._load_photo, daemon=True).start()
            self._indexer.wake.set()
        if set(changed) & {"workers", "power"} and hasattr(self._indexer, "replan"):
            self._indexer.replan()                     # 0.9.3: the new workers now, no restart
        if set(changed) & {"safety_net", "games_mode", "pause_on_battery", "pause_on_call"}:
            g = getattr(self._indexer, "governor", None)
            if g is not None and hasattr(g, "now"):
                g.now()
        if "models_stay_loaded" in changed and self._settings.get("models_stay_loaded") \
                and hasattr(self._indexer, "warm_models"):
            threading.Thread(target=self._indexer.warm_models, daemon=True, name="warm").start()
        if "tray" in changed and getattr(self, "_on_tray", None) is not None:
            self._on_tray(bool(self._settings.get("tray")))
        hotkeys = None
        if set(changed) & {"hotkey", "bar_hotkey", "bar"} and getattr(self, "_on_hotkeys", None) is not None:
            hotkeys = self._on_hotkeys()                 # the new combinations work now, no restart
        if "text_model" in changed:
            wake = getattr(self._indexer, "wake", None)
            if wake is not None:
                wake.set()                              # the indexer builds the new model's vectors (rebuild)
        if "photo_meaning" in changed:
            if self._settings.get("photo_meaning"):
                threading.Thread(target=self._indexer._load_photo, daemon=True).start()
            else:
                self._indexer.photo_text = None
            self._indexer.wake.set()
        if "ocr" in changed:
            if not self._settings.get("ocr"):
                self._later(lambda: self._store.set_meta("ocr_pass", "0"))   # on again later: re-read the scans
            self._indexer.wake.set()
        if "semantic" in changed and self._settings.get("semantic"):
            threading.Thread(target=self._indexer._load_embedder, daemon=True).start()
            self._indexer.wake.set()
        out = {"changed": changed}
        if hotkeys is not None:
            out["hotkeys"] = hotkeys
        return out

    def _later(self, fn):
        """Settings work on the index, after the answer, one at a time in order (tests: at once)."""
        run = getattr(self, "_settings_worker", None)
        if run is None:
            return fn()
        run(fn)

    def hotkey_state(self):
        """{hotkey, bar_hotkey: {spec, state}}: state ok | taken | reserved | invalid | off."""
        fn = getattr(self, "_hotkey_state", None)
        if fn is not None:
            return fn()
        return {w: {"spec": self._settings.get(w), "state": "off"} for w in ("hotkey", "bar_hotkey")}

    def hotkey_probe(self, which, spec):
        """Would spec work for which (hotkey or bar_hotkey)? ok | taken | reserved | invalid | same, and why."""
        from . import hotkey
        fn = getattr(self, "_hotkey_probe", None)
        state = fn(which, spec) if fn is not None else hotkey.probe(spec)
        n = hotkey.normal(spec) or ""
        reason = {"ok": "Free to use.",
                  "taken": "Another app on this PC already uses it.",
                  "reserved": (hotkey.reserved(n) or "Windows keeps it for itself") + ".",
                  "invalid": "Use Ctrl, Alt, Shift or Win with a letter, a number, Space or F1 to F12.",
                  "same": "The other NOBAD Find shortcut already uses it."}[state]
        return {"state": state, "spec": n if state != "invalid" else "", "reason": reason}

    def _remove_secrets(self):
        """Every secret (scope category) out of the index: key files by extension, secret folders by name."""
        from .const import BROWSER_SECRET_FILES, SECRET_EXT, SECRET_FILES, SECRET_FILES_IN, SECRET_NAMES, SECRET_PATHS
        rules = scope.Rules.from_settings(self._settings)
        exts = sorted(SECRET_EXT)
        names = sorted(SECRET_NAMES | SECRET_FILES | BROWSER_SECRET_FILES | {run[-1] for run in SECRET_FILES_IN})
        names += [n + t for n in sorted(SECRET_FILES | BROWSER_SECRET_FILES) for t in ("-journal", "-wal", "-shm")]

        def esc(t):
            return t.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        folders = ["%\\" + esc(n) + "\\%" for n in sorted(SECRET_NAMES)]
        folders += ["%\\" + esc("\\".join(p)) + "\\%" for p in SECRET_PATHS]
        like = " OR ".join(["lower(path) LIKE ? ESCAPE '!'"] * len(folders))
        rows = self._store.q(f"SELECT path FROM files WHERE ext IN ({','.join('?' * len(exts))}) OR lower(name) IN "
                             f"({','.join('?' * len(names))}) OR {like}", (*exts, *names, *folders))
        gone = [r[0] for r in rows if rules.category(r[0]) == "secrets"]
        if gone:
            self._store.remove_paths(gone)
        return len(gone)

    SCOPE_FRESH_S = 300

    def _scope_key(self, drives):
        s = self._settings
        return json.dumps([[s.get(k) for k in ("scope", "roots", "exclude", "include_system", "include_caches",
                                               "include_secrets", "index_removable", "index_network")],
                           [(d.get("root"), d.get("type")) for d in drives]], default=str)

    def scope_info(self):
        """What is indexed: the scope, its folders and every category with what's in it (scope.info).
        0.9.3: the counts (a range count over the index, about 0.6 s on a whole-PC index) are kept for a few
        minutes and refreshed in the background, so Settings > What to index opens at once. A changed setting or
        drive counts again."""
        drives = winapi.drives()
        key = self._scope_key(drives)
        got = getattr(self, "_scope_cache", None)
        if got is not None and got[0] == key:
            if time.time() - got[1] > self.SCOPE_FRESH_S:
                self.warm_scope_info()                 # this answer now, fresh counts for the next one
            return got[2]
        return self._count_scope(drives, key)

    def _count_scope(self, drives, key):
        r = scope.info(self._settings, drives, self._store)
        self._scope_cache = (key, time.time(), r)
        return r

    def warm_scope_info(self):
        """Count in the background (after a scan, and every few minutes while the engine runs)."""
        if getattr(self, "_scope_busy", False):
            return False
        self._scope_busy = True

        def work():
            try:
                drives = winapi.drives()
                self._count_scope(drives, self._scope_key(drives))
            except Exception as e:
                log(f"scope counts failed: {type(e).__name__}", "warn")
            finally:
                self._scope_busy = False
        threading.Thread(target=work, daemon=True, name="scope-counts").start()
        return True

    # ---------- turbo index ----------
    def turbo_state(self):
        """The turbo index (turbo.Turbo.state); never running without one (tests)."""
        if self._turbo is not None:
            return self._turbo.state()
        return {"available": False, "enabled": bool(self._settings.get("turbo")), "running": False, "volumes": [],
                "error": "The turbo index runs with the NOBAD Find engine only.", "helper": "not_installed"}

    def turbo_set(self, on):
        """On: Windows asks for permission once if the helper isn't set up yet, then it starts (no prompt after
        that). Off: it ends and Windows asks once to remove its helper."""
        if self._turbo is None:
            return {"ok": False, "error": "The turbo index runs with the NOBAD Find engine only.",
                    "state": self.turbo_state()}
        r = self._turbo.turn_on() if on else self._turbo.turn_off()
        if r.get("ok") and on:
            self._indexer.rescan()                  # read the drives with turbo now
        return dict(r, state=self._turbo.state())

    def turbo_helper(self, action):
        """"update": Windows asks once to update the protected helper (then turbo starts if it's on); "remove":
        turbo off and the helper removed (one prompt)."""
        if self._turbo is None:
            return {"ok": False, "error": "The turbo index runs with the NOBAD Find engine only.",
                    "state": self.turbo_state()}
        was = self._turbo.running()
        r = self._turbo.helper_action(action)
        if r.get("ok") and action == "update" and self._turbo.running() and not was:
            self._indexer.rescan()
        return dict(r, state=self._turbo.state())

    def pick_folder(self):
        dialog = self._folder_dialog              # Windows' own dialog, shown by this process
        path = dialog() if dialog is not None else ""
        return {"path": "", "busy": True} if path is None else {"path": path or ""}

    def rescan(self):
        self._indexer.rescan()
        return {"ok": True}

    def wipe(self, confirm):
        """Delete the whole index and start over. Security review 2026-11-22 (L10): nothing of the old index stays
        in plain text either: the Never index entries Forget added (noted in the index; from before that, the ones
        that are files) leave settings.json, the log is emptied, the index copies set aside after a key problem
        (*.unreadable-*) and the previews in memory go. What the app needs to start stays: the settings, the
        user's own Never index folders, the index key, downloaded models."""
        if confirm != "DELETE":
            return {"ok": False}
        forgot = set(self._forgotten())
        exclude = list(self._settings.get("exclude") or [])
        keep = [e for e in exclude if e not in forgot and not os.path.isfile(e)]
        if keep != exclude:
            self._settings.update({"exclude": keep})
        self._store.wipe()
        self._store.remove_aside_copies()
        thumbs.clear()
        from . import log as log_mod
        log_mod.clear()
        log(f"index wiped ({len(exclude) - len(keep)} forgotten entries removed)")
        self._indexer.rescan()
        return {"ok": True}

    # ---------- meaning-search model ----------
    def download_model(self):
        if not self._settings.get("allow_model_download"):
            return {"ok": False, "error": "Allow the download in Settings first."}
        if self._model["state"] == "downloading":
            return {"ok": True}
        self._model.update(state="downloading", got=0, error="")

        def run():
            try:
                embed.download_model(progress=lambda n, got, size: self._model.update(got=got, size=size))
                self._model["state"] = "ready"
                self._settings.update({"semantic": True})
                self._indexer._load_embedder()
                self._indexer.wake.set()
            except Exception as e:
                self._model.update(state="missing", error=str(e)[:200])
                log(f"model download failed: {type(e).__name__}", "warn")
        threading.Thread(target=run, daemon=True, name="model").start()
        return {"ok": True}

    def download_photo_model(self):
        """The photo model (about 211 MB): same pinned, hash-checked download as the text model."""
        if not self._settings.get("allow_photo_model_download"):
            return {"ok": False, "error": "Allow the photo model download in Settings first."}
        if self._photo_model["state"] == "downloading":
            return {"ok": True}
        self._photo_model.update(state="downloading", got=0, error="")
        done = {}

        def progress(name, got, size):
            done[name] = (got, size)
            self._photo_model.update(got=sum(g for g, _s in done.values()),
                                     size=sum(f[1] for f in photo.PHOTO_FILES.values()))

        def run():
            try:
                photo.download_model(progress=progress)
                self._photo_model["state"] = "ready"
                self._settings.update({"photo_meaning": True})
                self._indexer._load_photo()
                self._indexer.wake.set()
            except Exception as e:
                self._photo_model.update(state="missing", error=str(e)[:200])
                log(f"photo model download failed: {type(e).__name__}", "warn")
        threading.Thread(target=run, daemon=True, name="photo-model").start()
        return {"ok": True}

    # ---------- Windows Search ----------
    # ---------- model tiers (contract: models, model_use, model_download, model_remove, auto_configure) ----------
    _models_dir = None                 # the data folder models live in (tests point it elsewhere)
    _mdl_thread = None

    def _mdir(self):
        return self._models_dir or models.DATA_DIR

    def _text_in_use(self):
        """The text model whose vectors search uses now (or the one chosen, before there are any)."""
        return (getattr(self._indexer, "text_model", None) or models.selected(self._settings, "text")
                or models.DEFAULT_TEXT)

    def _photo_in_use(self):
        return getattr(self._indexer, "photo_model", None) or models.selected(self._settings, "photo") or \
            models.DEFAULT_PHOTO

    def _romanized(self):
        """Hinglish is read in every question when the language focus is Hindi or many languages (cached 60 s:
        the focus may come from Windows' languages)."""
        import time as _t
        at, val = getattr(self, "_roman_cache", (0.0, False))
        if _t.monotonic() - at > 60:
            try:
                val = self._focus() in ("hindi", "multilingual")
            except Exception:
                val = False
            self._roman_cache = (_t.monotonic(), val)
        return val

    def _focus(self):
        return self._settings.get("language_focus") or models.focus_from_languages(winapi.windows_languages())

    def _model_state(self, m):
        d = getattr(self, "_mdl", {}).get(m["id"])
        if d and d["state"] == "downloading":
            return "downloading"
        ready = models.ready(m["id"], self._mdir())
        if m["feature"] == "ocr":
            return ("active" if self._settings.get("ocr") else "ready") if ocr.available() else "failed"
        if not ready:
            return "failed" if d and d.get("error") else "not_downloaded"
        if m["feature"] == "text":
            in_use = getattr(self._indexer, "text_model", None) or models.selected(self._settings, "text")
            return "active" if self._settings.get("semantic") and in_use == m["id"] else "ready"
        return "active" if models.selected(self._settings, "photo") == m["id"] else "ready"

    def models(self):
        pc = hw.scan()
        focus = self._focus()
        rec = models.recommend(pc)
        choice = models.tier_choice(rec, focus)
        out = []
        rid = models.talk_runtime(pc, self._mdir())
        for m in models.CATALOG:
            ok, why = models.capable(m, pc)
            if m["feature"] == "ocr" and not ocr.available():
                ok, why = False, ocr.why_missing() or "Windows OCR isn't available on this PC"
            # 1.1: the talk models also say their graphics memory and the runtime they need on this PC (its
            # download is offered with theirs, in one consent)
            talk = {"vram_mb": int(m.get("vram_mb") or 0), "runtime": rid} if m["feature"] == "talk" else {}
            out.append({**talk, "id": m["id"], "feature": m["feature"], "name": m["name"], "tier": m["tier"],
                        "licence": m["licence"], "source": m["source"], "size_mb": models.size_mb(m),
                        "ram_mb": int(m.get("ram_mb") or 0), "speed_note": m.get("speed_note") or "",
                        "languages": list(m.get("languages") or []), "improves": m.get("improves") or "",
                        "builtin": bool(m["builtin"]), "state": self._model_state(m), "capable": ok,
                        "capable_reason": why, "recommended": choice.get(m["feature"]) == m["id"],
                        "quality": dict(m["quality"]) if m.get("quality") else None,
                        "dir": "" if m["builtin"] else models.model_dir(m["id"], self._mdir())})
        return {"pc": pc, "tier_recommended": rec, "tier_current": models.tier_current(self._settings, focus),
                "language_focus": focus, "models": out}

    def model_use(self, feature, mid):
        m = models.get(mid) if isinstance(mid, str) else None
        if m is None or m["feature"] != feature:
            return {"ok": False, "error": "There's no such model for that.", "needs_download": False}
        changes = {"text": {"text_model": mid, "semantic": True}, "photo": {"photo_model": mid, "photo_meaning": True},
                   "ocr": {"ocr": True}}[feature]
        self.set_settings(changes)
        wake = getattr(self._indexer, "wake", None)
        if wake is not None:
            wake.set()                          # a switched text model is rebuilt by the indexer (phase rebuild)
        return {"ok": True, "error": "", "needs_download": not models.ready(mid, self._mdir())}

    def model_download(self, mid, consent):
        m = models.get(mid) if isinstance(mid, str) else None
        if m is None or m["builtin"]:
            return {"ok": False, "error": "There's nothing to download for that."}
        if consent != "DOWNLOAD":
            return {"ok": False, "error": "A model is only downloaded when you say Download."}
        self._mdl = getattr(self, "_mdl", {})
        lock = self.__dict__.setdefault("_mdl_lock", threading.Lock())
        with lock:
            if self._mdl.get(mid, {}).get("state") == "downloading":
                return {"ok": True, "error": ""}            # already on its way: one download per model
            self._mdl[mid] = {"state": "downloading", "got": 0, "size": 0, "error": ""}
        if m["feature"] in ("text", "photo"):       # talk models and llama.cpp runtimes: no stored consent (each
            self._settings.update({"allow_model_download" if m["feature"] == "text" else    # download is a click)
                                   "allow_photo_model_download": True})
        st = self._mdl[mid] = {"state": "downloading", "got": 0, "size": sum(f[1] for f in m["files"].values()),
                               "error": ""}
        d = models.model_dir(mid, self._mdir())

        def run():
            done = {}
            try:
                if m["feature"] == "runtime":                   # the pinned zip, then only its pinned DLLs
                    def zprogress(_n, got, _size):
                        st["got"] = got
                    # the folder is swapped by rename: the talk worker must not hold its DLLs (it refuses new
                    # questions while this runtime downloads, _vision_not_now)
                    self.vision_stop("Stopped: the picture runtime is being updated.")
                    vlm_runtime.install(mid, self._mdir(), zprogress)
                else:
                    os.makedirs(d, exist_ok=True)
                    for name, (path, size, sha) in m["files"].items():
                        def progress(_n, got, _size, name=name):
                            done[name] = got
                            st["got"] = sum(done.values())
                        embed._fetch_verified(models.url(m, path), os.path.join(d, name), size, sha, name, progress,
                                              part=".dl.part")      # not the 0.7.0 download's file names
                        done[name] = size
                        st["got"] = sum(done.values())
                st["state"] = "ready"
                log(f"model {mid} downloaded and verified")
                wake = getattr(self._indexer, "wake", None)
                if m["feature"] == "text" and models.selected(self._settings, "text") == mid and \
                        not getattr(self._indexer, "text_model", None):
                    threading.Thread(target=self._indexer._load_embedder, daemon=True).start()
                if m["feature"] == "photo" and models.selected(self._settings, "photo") == mid:
                    threading.Thread(target=self._indexer._load_photo, daemon=True).start()
                if wake is not None:
                    wake.set()
            except Exception as e:
                log(f"model {mid} download failed: {type(e).__name__}", "warn")
                st.update(state="missing", error=str(e)[:200] or "The download failed.")
        self._mdl_thread = threading.Thread(target=run, daemon=True, name="model-download")
        self._mdl_thread.start()
        return {"ok": True, "error": ""}

    # ---------- talk about a photo (1.1, vlm/worker.py) ----------
    # Every vision_* call answers at once {"ok", "error", "job"}; the answer comes as `vision` events
    # {"job", "state": loading | answering | done | error | cancelled, "text", "model", "note"} (worker.Talker).
    # One job at a time: a new one cancels the one streaming. Files only by result id.

    def _talker(self):
        with self._talk_lock:
            if self._talk is None:
                from .vlm import worker
                self._talk = worker.Talker(self._vision_emit, on_budget=self._talk_budget)
            return self._talk

    def _talk_budget(self, mb):
        fn = self._on_talk_budget
        if fn is not None:
            fn(mb)

    def _vision_emit(self, ev):
        push = self._on_vision
        if push is not None:
            push(ev)

    def _vision_file(self, file_id):
        """(path, "") of a photo the talk model may look at, or (None, why not)."""
        if not isinstance(file_id, int) or isinstance(file_id, bool):
            return None, VISION_GONE
        row = self._store.q("SELECT path, kind FROM files WHERE id=?", (file_id,))
        if not row:
            return None, VISION_GONE
        path, kind = row[0]
        if scope.Rules.from_settings(self._settings).names_only(path):
            return None, "NOBAD Find keeps only the name of this file, so it doesn't look inside it."
        if kind != "image":
            return None, "Only photos can be described."
        if not os.path.isfile(path):
            return None, VISION_GONE
        return path, ""

    def _vision_not_now(self):
        gov = self._governor
        d = getattr(gov, "decision", None)
        if d is not None and d.level == "paused":
            why = d.reason.split(":", 1)[1].strip() if ":" in d.reason else ""
            return "Not now: NOBAD Find is paused" + (f" ({why})." if why else ".")
        busy = [mid for mid, st in getattr(self, "_mdl", {}).items()
                if st.get("state") == "downloading" and (models.get(mid) or {}).get("feature") == "runtime"]
        if busy:
            return "Not now: the picture runtime is being downloaded. Try again when it's done."
        return ""

    def _vision_model(self, deeper):
        """(catalog entry, "") of the talk model to use now, or (None, why not)."""
        talk = models.talk_models()
        m = talk[1] if deeper and len(talk) > 1 else talk[0]
        gov = self._governor
        sample = getattr(gov, "sample", None)
        ok, why = talk_assess(m, sample, hw.scan()) if deeper else talk_fits(m, sample)
        return (m, "") if ok else (None, why or f"Not now: {m['name']} can't run on this PC right now.")

    def _vision_job(self, op, ids, question, deeper):
        """The worker job for these photos and this model, or {"ok": False, ...} when it can't start."""
        paths = []
        for fid in ids:
            p, why = self._vision_file(fid)
            if p is None:
                return None, {"ok": False, "error": why, "job": 0}
            paths.append(p)
        if len(paths) > MAX_IMAGES:
            return None, {"ok": False, "error": "At most two photos at a time.", "job": 0}
        if op == "ask":
            from .vlm import prompts
            try:
                prompts.ask(question)
            except ValueError:
                return None, {"ok": False, "error": "Type a question.", "job": 0}
        why = self._vision_not_now()
        if why:
            return None, {"ok": False, "error": why, "job": 0}
        m, why = self._vision_model(deeper)
        if m is None:
            return None, {"ok": False, "error": why, "job": 0}
        d = self._mdir()
        pc = hw.scan()
        rid = models.talk_runtime(pc, d)
        need = [x for x in (m, models.get(rid)) if not models.ready(x["id"], d)]
        if need:
            mb = sum(models.missing_mb(x["id"], d) for x in need)
            names = " and ".join(x["name"] for x in need)
            return None, {"ok": False, "job": 0,
                          "error": f"To talk about photos, download {names} first ({mb} MB, once).",
                          "download": [{"id": x["id"], "name": x["name"], "size_mb": models.missing_mb(x["id"], d)}
                                       for x in need]}
        vulkan = rid == "llama-vulkan"
        settings = dict(m["talk"])
        settings["need_mb"] = models.talk_need_mb(m, rid) or None
        mdir = models.model_dir(m["id"], d)
        talk = self._talker()
        job = {"job": talk.next_id(), "op": op, "paths": paths, "question": question or "",
               "model": {"id": m["id"], "model": os.path.join(mdir, "model.gguf"),
                         "mmproj": os.path.join(mdir, "mmproj.gguf"), "runtime": models.model_dir(rid, d)},
               "settings": settings, "gpu_layers": 99 if vulkan else 0, "files": list(ids)}
        return (job, m["name"]), None

    def _vision_start(self, op, ids, question=None, deeper=False):
        got, refused = self._vision_job(op, ids, question, deeper)
        if refused is not None:
            return refused
        job, name = got
        talk = self._talker()
        from .rpc.protocol import after_reply
        after_reply(lambda: talk.submit(job, name))     # its events come after this answer, which names the job
        return {"ok": True, "error": "", "job": job["job"]}

    def vision_describe(self, file_id):
        return self._vision_start("describe", [file_id])

    def vision_ask(self, file_id, question, deeper=False, more=False):
        """A question about one photo. A question about its writing ("what does the sign say?") gets the text read
        from the photo (OCR) first, as a finished answer; the model is asked only with more=True."""
        from .vlm import prompts
        if not isinstance(question, str):
            return {"ok": False, "error": "Type a question.", "job": 0}
        if not more and prompts.is_text_question(question) and prompts.clean_question(question):
            p, why = self._vision_file(file_id)
            if p is None:
                return {"ok": False, "error": why, "job": 0}
            text = self._store.read_text(file_id)
            if text:
                talk = self._talker()
                jid = talk.next_id()
                ev = {"job": jid, "state": "done", "text": text[:MAX_READ_TEXT], "model": "",
                      "note": "Text read from the photo"}
                from .rpc.protocol import after_reply
                after_reply(lambda: talk.emit_now(ev))
                return {"ok": True, "error": "", "job": jid}
        return self._vision_start("ask", [file_id], question, bool(deeper))

    def vision_compare(self, a, b, question=None, deeper=False):
        if a == b:
            return {"ok": False, "error": "Pick a second, different photo to compare.", "job": 0}
        if question is not None and not isinstance(question, str):
            return {"ok": False, "error": "The question must be text.", "job": 0}
        return self._vision_start("compare", [a, b], question, bool(deeper))

    def vision_cancel(self):
        if self._talk is not None:
            self._talk.cancel()
        return {"ok": True, "error": "", "job": None}

    def vision_keep(self, file_id, text):
        """Keep a description of a photo (the user's press): stored in vdesc and as one text chunk of that photo,
        so words and meaning search find it ("your kept description matches"). Empty text forgets it."""
        from .vlm import prompts
        _p, why = self._vision_file(file_id)
        if why:
            return {"ok": False, "error": why}
        if not isinstance(text, str):
            return {"ok": False, "error": "The description must be text."}
        t = prompts.clean_text(text, MAX_KEPT)
        if not t:
            self._store.forget_description(file_id)
            return {"ok": True, "error": "", "kept": False}
        model = self._talk.kept_model(file_id, t) if self._talk is not None else ""
        self._store.keep_description(file_id, t, model)
        wake = getattr(self._indexer, "wake", None)
        if wake is not None:
            wake.set()                                  # its meaning vector is made by the indexer's next pass
        return {"ok": True, "error": "", "kept": True}

    def vision_state(self):
        d = self._mdir()
        rid = models.talk_runtime(hw.scan(), d)          # the one a question would use (or ask to download)
        sample = getattr(self._governor, "sample", None)
        # the talk worker runs in the worker group under the level's CPU cap (and efficiency mode at Light): the
        # seconds are the ones measured at that level (docs/measurements.md, tools/measure_talk.py)
        level = getattr(getattr(self._governor, "decision", None), "level", None) or "full"
        out = []
        for i, m in enumerate(models.talk_models()):
            ok, why = talk_assess(m, sample, hw.scan()) if i else talk_fits(m, sample)
            load_s, answer_s = models.talk_timing(m, rid, level)    # measured: this runtime, this level
            out.append({"id": m["id"], "name": m["name"], "deeper": bool(i), "ready": models.ready(m["id"], d),
                        "missing_mb": models.missing_mb(m["id"], d), "ram_mb": int(m.get("ram_mb") or 0),
                        "vram_mb": int(m.get("vram_mb") or 0), "load_s": load_s, "answer_s": list(answer_s),
                        "slow_note": models.talk_slow_note(m, rid, level), "can_run": ok, "why": why})
        st = self._talk.state() if self._talk is not None else {"loaded": "", "busy": False, "job": 0,
                                                               "running": False}
        return {"ok": True, "not_now": self._vision_not_now(), "models": out,
                "runtime": {"id": rid, "ready": models.ready(rid, d), "missing_mb": models.missing_mb(rid, d)},
                **st}

    # the engine's hooks (engine.worker_hooks, run): idle release, memory pressure, quitting
    def vision_tick(self):
        """The governor's tick (engine.worker_hooks release_idle): a pause ends the answer and the model (the
        game or the memory comes first), a hung worker is ended, an idle one is released."""
        t = getattr(self, "_talk", None)
        if t is None:
            return False
        d = getattr(self._governor, "decision", None)
        if d is not None and d.level == "paused":
            why = d.reason.split(":", 1)[1].strip() if ":" in d.reason else ""
            return t.stop("Stopped: NOBAD Find paused" + (f" ({why})." if why else "."))
        if t.check_deadline():
            return True
        return t.release_if_idle()

    def vision_release_idle(self):
        t = getattr(self, "_talk", None)
        return t.release_if_idle() if t is not None else False

    def vision_budget_mb(self):
        t = getattr(self, "_talk", None)
        return t.budget_mb() if t is not None else 0

    def vision_stop(self, why=""):
        t = getattr(self, "_talk", None)
        return t.stop(why) if t is not None else False

    def vision_pids(self):
        t = getattr(self, "_talk", None)
        return t.pids() if t is not None else {}

    # ---------- updates (0.9.0, update.py) ----------
    def update_state(self):
        u = getattr(self, "_updater", None)
        if u is None:
            return {"state": "idle", "current": APP_VER, "latest": "", "size": 0, "got": 0, "bps": 0,
                    "notes_url": "", "error": "", "auto": bool(self._settings.get("update_check")), "checked_at": 0}
        return u.snapshot()

    def update_check(self):
        """Check now (the Settings button): in the background; the update event (or update_state) says how it went."""
        u = getattr(self, "_updater", None)
        if u is None:
            return {"ok": False, "error": "Updates aren't available in this copy of NOBAD Find."}
        u.check_in_background()
        return {"ok": True}

    def update_install(self, consent):
        """Download the newer version's installer, check it and run it: only with consent "INSTALL" (the button)."""
        u = getattr(self, "_updater", None)
        if u is None:
            return {"ok": False, "error": "Updates aren't available in this copy of NOBAD Find."}
        if consent != "INSTALL":
            return {"ok": False, "error": "Nothing is installed without your OK."}
        if u.release is None or u.state not in ("available", "ready", "error"):
            return {"ok": False, "error": "Check for updates first."}

        def go():
            if u.state != "ready" and not u.download(then_install=True):
                return
            u.install()
        threading.Thread(target=go, daemon=True, name="update-install").start()
        return {"ok": True}

    def model_folder(self, mid):
        """Open the folder a model is (or will be) downloaded to in File Explorer: a catalog id only, never a path
        from the UI. The models folder itself when that model's folder isn't there yet."""
        m = models.get(mid) if isinstance(mid, str) else None
        if m is None or m["builtin"]:
            return {"ok": False, "error": "That model is part of Windows: it has no folder of its own."}
        d = models.model_dir(mid, self._mdir())
        target = d if os.path.isdir(d) else os.path.join(self._mdir(), "models")
        if not os.path.isdir(target):
            target = self._mdir()
        if not os.path.isdir(target) or not open_folder(target):
            return {"ok": False, "error": "Couldn't open the folder."}
        return {"ok": True}

    def model_remove(self, mid):
        m = models.get(mid) if isinstance(mid, str) else None
        if m is None or m["builtin"]:
            return {"ok": False, "error": "That model is part of Windows or NOBAD Find."}
        in_use = {getattr(self._indexer, "text_model", None)}
        if self._store is not None:
            in_use |= {self._store.meta("vec_model"), self._store.meta("vec_model_next")}
        if m["feature"] == "photo" and self._settings.get("photo_meaning"):
            in_use.add(models.selected(self._settings, "photo"))
        if mid in in_use:
            return {"ok": False, "error": "NOBAD Find is using that model. Choose another one first."}
        if m["feature"] in ("talk", "runtime"):
            self.vision_stop("Stopped: that model is being removed.")     # its files are open in the talk worker
        d = models.model_dir(mid, self._mdir())
        # a runtime keeps only its pinned DLLs (the zip was deleted after unpacking): those are what goes
        names = list(m["files_in_zip"]) if m["feature"] == "runtime" else list(m["files"])
        for name in names:
            for p in (os.path.join(d, name), os.path.join(d, name + ".part"), os.path.join(d, name + ".dl.part")):
                try:
                    os.remove(p)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    return {"ok": False, "error": e.strerror or "Windows couldn't delete it."}
        try:
            os.rmdir(d)
        except OSError:
            pass                                # other files in there (not ours) stay
        return {"ok": True, "error": ""}

    def auto_configure(self):
        tier = models.recommend(hw.scan())
        choice = models.tier_choice(tier, self._focus())
        changes = {"text_model": choice["text"], "semantic": True, "ocr": True}
        changes.update({"photo_model": choice["photo"], "photo_meaning": True} if choice["photo"] else
                       {"photo_meaning": False})
        self.set_settings(changes)
        steps = [{"feature": f, "id": choice[f],
                  "needs_download": bool(choice[f]) and not models.ready(choice[f], self._mdir())}
                 for f in ("text", "photo", "ocr")]
        return {"tier": tier, "steps": steps}

    def model_language(self, focus):
        if focus not in models.FOCUSES:
            return {"ok": False, "error": "Choose English, many languages or Hindi."}
        self._settings.update({"language_focus": focus})
        return {"ok": True, "error": ""}

    def wsearch_state(self):
        s = wsearch.state()
        s["saved"] = self._settings.get("wsearch_prev")
        return s

    def wsearch_set(self, off):
        cur = wsearch.state()
        if cur.get("missing"):
            return {"ok": False, "error": "Windows Search isn't installed on this PC."}
        if off:
            if cur["start"] != "disabled":
                self._settings.update({"wsearch_prev": cur["start"]})
            ok = wsearch.request("disabled")
        else:
            ok = wsearch.request(self._settings.get("wsearch_prev") or "delayed-auto")
            if ok:
                self._settings.update({"wsearch_prev": ""})
        return {"ok": ok, "state": wsearch.state(),
                "error": "" if ok else "Windows didn't make the change (the permission prompt may have been closed)."}

    def use_instead_of_windows_search(self, on):
        """One click: Windows Search indexing off (Windows asks permission) and NOBAD Find starts with Windows.
        Off again: Windows Search back exactly as it was. NOBAD Find keeps starting with Windows unless changed."""
        r = self.wsearch_set(bool(on))
        if r.get("ok") and on and not self._settings.get("autostart"):
            self._settings.update({"autostart": True})
            try:
                set_autostart(True)
            except OSError:
                pass
        return r

    # ---------- window ----------
    def ui_shown(self):
        """The UI's main window came up (the pipe's ui_shown): indexing resumes if closing had stopped it."""
        if self._on_show is not None:
            self._on_show()
        return {"ok": True}

    def hide(self):
        """The UI's main window went away (ui_hidden, or its pipe closed): what that means for indexing."""
        if self._on_hide is not None:
            self._on_hide()
        return {"ok": True}

    def quit(self):
        self._quitting = True
        self._indexer.stop()
        self._arm_hard_exit()
        return {"ok": True}

    def _arm_hard_exit(self):
        """If the exit hangs, end the process anyway; the job then ends every worker with it."""
        if getattr(self, "_hard_exit_timer", None) is not None:
            return
        t = self._hard_exit_timer = self._timer(QUIT_TIMEOUT, self._hard_exit)
        t.daemon = True
        t.start()

    def _hard_exit(self):
        log("quit took too long; exiting now", "warn")
        self._indexer.stop()
        self._indexer.join(5)                  # a database write in progress is committed first
        self._exit(0)


MAX_READ_TEXT = 4000             # characters of a photo's read text (OCR) shown first for a question about writing
MAX_KEPT = 2000                  # characters of a kept description
TALK_MARGIN_MB, TALK_MARGIN_SHARE = 256, 0.25       # as capability.MARGIN_MB / MARGIN_SHARE (PR #16)


def talk_fits(m, sample):
    """(True, "") when the talk model's measured need (catalog ram_mb) plus the margin fits in free RAM now (the
    governor's last sample, else Windows now); unknown free memory never refuses."""
    free = getattr(sample, "free_mb", None) if sample is not None else None
    if not free:
        free = winapi.memory_status()[1]
    need = int(m.get("ram_mb") or 0)
    if free and need + TALK_MARGIN_MB + TALK_MARGIN_SHARE * need > free:
        short = m["name"].split()[0]
        return False, (f"Not now: only {free / 1024:.1f} GB free, {short} needs about {need / 1024:.1f} GB "
                       "plus margin")
    return True, ""


def talk_assess(m, sample, pc):
    """(can run now, why) for the deeper talk model. capability.assess (PR #16) when it is there; until it merges,
    this fallback: models.capable (the installed PC) and talk_fits (free memory now).
    TEMPORARY (find 1.1 release fix, maintainer ruling): the fallback, talk_fits' use here and TALK_MARGIN_* go
    when PR #16 merges; tests/test_vlm_progress.py::test_talk_assess_uses_capability_assess_when_the_module_is_there
    proves the capability path is taken (and the fallback isn't) as soon as nobadfind.capability exists."""
    try:
        from . import capability
    except ImportError:
        capability = None
    if capability is not None:
        r = capability.assess(sample, pc, catalog=[m])
        return bool(r["can_run"].get(m["id"])), r["why"].get(m["id"]) or ""
    ok, why = models.capable(m, pc)
    return (ok, why) if not ok else talk_fits(m, sample)


class DownloadRate:
    """MB done, MB in all and MB/s of one download from successive looks at its {"state", "got", "size"}."""

    def __init__(self):
        self._last = {}                   # model id -> (time, got bytes)

    def sample(self, mid, m, now):
        """{"got_mb", "size_mb", "mb_s"} while m is downloading, else None (and the speed starts over)."""
        if m["state"] != "downloading":
            self._last.pop(mid, None)
            return None
        prev, self._last[mid] = self._last.get(mid), (now, m["got"])
        speed = max(0.0, (m["got"] - prev[1]) / (now - prev[0]) / 1048576) if prev and now > prev[0] else 0.0
        return {"got_mb": round(m["got"] / 1048576, 1), "size_mb": round(m["size"] / 1048576, 1),
                "mb_s": round(speed, 2)}


def reveal_in_explorer(path):
    """Open the folder with the file selected (Shell API, no command line is built)."""
    if not winapi.WIN:
        return False
    ole32 = ctypes.WinDLL("ole32")
    shell32 = ctypes.WinDLL("shell32")
    shell32.ILCreateFromPathW.restype = ctypes.c_void_p
    shell32.ILCreateFromPathW.argtypes = [ctypes.c_wchar_p]
    shell32.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    shell32.ILFree.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize(None)
    pidl = shell32.ILCreateFromPathW(path)
    if not pidl:
        return False
    try:
        return shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0) == 0
    finally:
        shell32.ILFree(pidl)


def open_folder(path):
    """File Explorer on a folder (ShellExecute "open", no command line is built)."""
    if not winapi.WIN:
        return False
    shell32 = ctypes.WinDLL("shell32")
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                      ctypes.c_wchar_p, ctypes.c_int]
    return (shell32.ShellExecuteW(None, "open", path, None, None, 1) or 0) > 32


def set_autostart(on):
    """Start with Windows (hidden, hotkey ready) through the user's own Run key."""
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, "NOBAD Find", 0, winreg.REG_SZ,
                              subprocess.list2cmdline(winapi.self_command("--background")))
        else:
            try:
                winreg.DeleteValue(k, "NOBAD Find")
            except FileNotFoundError:
                pass


__all__ = ["Api", "DownloadRate", "reveal_in_explorer", "set_autostart", "sys"]
