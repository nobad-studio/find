"""Talk about a photo: the worker process that holds ONE talk model, and the engine side that drives it (`Talker`).

The worker (a `multiprocessing` spawn child, `main`) joins Find's WORKERS job and steps aside with
`winapi.worker_priority()`. Model loading, picture decoding (Windows' decoders, photo.decode_rgb) and answering all
happen there, never on the engine's threads. It has no network code and only opens files the engine names: the
photo(s) of the job and the model / runtime files that are already on disk (downloads stay the consented
`model_download` path).

Jobs come over the pipe, one at a time:
    {"op": "describe" | "ask" | "compare", "job": n, "paths": [one or two photo paths], "question": str,
     "model": {"id", "model", "mmproj", "runtime"}, "settings": the catalog's talk settings (+ need_mb),
     "gpu_layers": int}
    {"op": "cancel", "job": n} · {"op": "unload"} · {"op": "quit"}
and the worker answers with
    {"t": "state", "job": n, "state": "loading" | "answering" | "cancelled"}
    {"t": "state", "job": None, "loaded": model id or ""}        (what is resident now)
    {"t": "phase", "job": n, "phase": one of PHASE_ORDER}        (the job's step now)
    {"t": "progress", "job": n, "phase": p, "frac": 0..1 | None}  (what moved in that step, see below)
    {"t": "token", "job": n, "s": text}  ·  {"t": "done", "job": n, "text": answer}  ·  {"t": "error", "job": n, "why"}

- One model resident: a job for another model unloads the current one first.
- A new job (or cancel / quit) arriving stops the job at once wherever it is (vlm/session.py): llama's model load
  (its progress callback returns false), the vision part's load (mtmd's), the image encode (mtmd's eval callback),
  the prompt eval (llama's abort callback, CPU), or between two tokens; the model stays loaded unless its load was
  the part stopped. Not stoppable, and bounded by PHASES: loading the runtime's DLLs, Windows decoding the photo,
  llama_init_from_model (the context) and, on Vulkan, the prompt eval. The engine drops anything still arriving for
  a job it no longer follows.
- While a job runs, the worker's memory and I/O priority are normal (winapi.worker_activity), and back to low /
  very low when it ends: the 1.1 GB Qwen file is then not the first memory Windows takes back, nor queued behind
  every other read. The CPU priority (idle), the WORKERS job and the governor's CPU cap and EcoQoS never change.
- Out of memory (session.AllocFailed), loading or in the middle of an answer: the model is unloaded, the job ends
  with an error naming the catalog's measured need, and the worker keeps serving (nothing is retried).
- llama.cpp's logging is switched off before any model loads (llama_api.silence_logs): its prompt echo carries
  the user's question.

The engine side (`Talker`) starts the worker on the first job, follows ONE job at a time, turns the worker's
messages into `vision` events ({"job", "state", "text", "model", "note"}; "text" is the whole answer so far) and
stops the worker after IDLE seconds without a question (governor tick, engine.worker_hooks), on memory pressure,
before a runtime reinstall and when the engine stops.

Hang deadline (`Talker.check_deadline`, the governor's tick): the Talker follows what the WORKER is doing (its job,
even one the engine already let go, until the worker says it ended), one phase at a time, each with its own bound
(PHASES). Only real progress moves the deadline, and only progress of the phase the worker is in:
- "model" / "vision": the load fraction must INCREASE; the same fraction again is ignored.
- "image": "still computing" calls (frac None) from the encode / eval callbacks move it, but never past the
  phase's cap counted from its start: a process can't keep its deadline alive by calling.
- "answer": each token.
- every other phase: nothing moves it; its bound is fixed.
Phases only go forward (PHASE_ORDER), so entering one can't be repeated to refresh a deadline either.
"""
import itertools
import multiprocessing
import os
import threading
import time
from collections import deque

from . import prompts
from .session import AllocFailed, Cancelled

IDLE = 180                      # = embed.Lazy.IDLE (tests keep them equal): the talk model leaves after 3 min idle
MAX_IMAGES = 2                  # compare is two photos; more is refused
OPS = ("describe", "ask", "compare")
ANSWER_S = 120                  # no token for this long while answering: the worker hangs
# The steps of a job, in order. "start": the job was sent, the worker hasn't said anything about it yet;
# "prepare": the runtime's DLLs; "photo": Windows decodes the photo(s); "model": llama loads the model file;
# "context": llama makes its context; "vision": mtmd loads the vision part; "image": the photo is read (image encode
# + prompt eval); "answer": the tokens.
PHASE_ORDER = ("start", "prepare", "photo", "model", "context", "vision", "image", "answer")
# phase: (seconds without progress, cap: seconds from the phase's start that "still computing" calls can't pass, or
# None when such calls don't count). A phase without progress is a fixed bound.
# PROVISIONAL (release fix, 2026-11-22): set before the full re-measurement through the worker (pending:
# tools/measure_talk.py, docs/measurements.md). What was measured so far, SmolVLM2 through vlm.session on this PC
# (CPU and Vulkan, normal free memory): longest gap between two load fractions 0.4-0.6 s, context 0.04-0.17 s,
# vision part 0.1-0.2 s, "still computing" calls in the photo eval at most 0.24 s apart. 60 s is 100x those;
# the cold Qwen load that stalled before (127 s without any message) had no progress reporting at all.
PHASES = {
    "start": (60, None),        # process start + the job read
    "prepare": (60, None),      # the runtime's DLLs
    "photo": (60, None),        # Windows decodes up to two photos
    "model": (60, None),        # between two increases of llama's load fraction
    "context": (60, None),      # llama_init_from_model (no callback)
    "vision": (60, None),       # between two increases of mtmd's fraction (and after 1.0)
    "image": (60, 600),         # between "still computing" calls; in all at most 600 s (slowest answer so far
                                # 32 s: Qwen, CPU, Very light, 2026-11-22)
    "answer": (ANSWER_S, None),
}
FRACTION_PHASES = ("model", "vision")
STOPPING_NOTE_S = 1.0           # a new question still waiting for the last one to stop after this: say so
HUNG = "The photo model stopped responding. Try again."
GONE = "This photo is no longer there."
STOPPING = "Stopping the last answer…"
BUILD = {"describe": lambda q: prompts.describe(), "ask": prompts.ask, "compare": lambda q: prompts.compare(q or None)}
SEND_EVERY = 0.25               # the worker sends a load fraction at most this often (and always the final 1.0) ...
PING_EVERY = 1.0                # ... and "still computing" at most this often
POLL_EVERY = 0.05               # seconds between two looks at the pipe for a Stop from inside llama / mtmd


def _size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


def memory_note(need_mb):
    return f"Not enough memory right now (needs about {_size(need_mb)}). Close something or try again later."


# ---------- the worker process ----------
def _prepare(model):
    """Load the pinned runtime's DLLs (quiet) before any picture is decoded: winrt brings an older MSVCP140, and
    whichever loads first wins (ocr._load)."""
    from . import llama_api
    llama_api.load(model["runtime"], quiet=True)


def _open_session(model, settings, gpu_layers, progress=None):
    """The real model: the pinned runtime from its folder, logging off, then Session (vlm/session.py)."""
    from . import llama_api, session
    lib = llama_api.load(model["runtime"], quiet=True)
    llama_api.silence_logs(lib)                         # again: a no-op unless the runtime was loaded without quiet
    return session.Session(lib, model["model"], model["mmproj"], settings, gpu_layers, progress=progress)


def _decode(path, side):
    """(rgb, w, h) of the photo at `path`, decoded by Windows (photo.decode_rgb), or a plain reason (str)."""
    from .. import photo
    try:
        if os.path.getsize(path) > photo.MAX_PHOTO_BYTES:
            return "This photo is too big to look at."
        with open(path, "rb") as f:
            data = f.read(photo.MAX_PHOTO_BYTES + 1)
    except FileNotFoundError:
        return GONE
    except OSError:
        return "Windows couldn't open this photo."
    got = photo.decode_rgb(data, side)
    return got if got else "This picture can't be read (damaged, too small, or a format Windows can't open)."


class _Watch:
    """One job's progress hook (session.Session's `progress`): sends each phase as it starts and what really moved
    in it (a load fraction only when it grew; "still computing" at most every PING_EVERY), and answers False once
    a Stop came (it looks at the pipe at most every POLL_EVERY, so llama's per-tensor and per-node calls stay
    cheap)."""

    def __init__(self, send, cancelled, jid, clock=time.monotonic):
        self.send, self.cancelled, self.jid, self.clock = send, cancelled, jid, clock
        self.phase, self.frac, self.sent, self.looked, self.cut = "", -1.0, 0.0, -1.0, False

    def __call__(self, phase, frac=None):
        now = self.clock()
        if phase != self.phase:
            self.phase, self.frac, self.sent = phase, -1.0, now
            self.send(t="phase", job=self.jid, phase=phase)
        elif frac is not None:
            if frac > self.frac and (frac >= 1.0 or now - self.sent >= SEND_EVERY):
                self.frac, self.sent = frac, now
                self.send(t="progress", job=self.jid, phase=phase, frac=round(min(float(frac), 1.0), 4))
        elif now - self.sent >= PING_EVERY:
            self.sent = now
            self.send(t="progress", job=self.jid, phase=phase, frac=None)
        if not self.cut and now - self.looked >= POLL_EVERY:
            self.looked = now
            self.cut = bool(self.cancelled())
        return not self.cut


class _Serve:
    def __init__(self, conn, open_session, decode, prepare=None, activity=None):
        self.conn, self.open, self.decode = conn, open_session, decode
        self.prepare = prepare or (lambda model: None)
        self.activity = activity or (lambda active: None)
        self.session, self.loaded = None, ""
        self.pending, self.stop = None, False
        self._cut, self._unload_after = False, False

    def send(self, **msg):
        try:
            self.conn.send(msg)
        except (OSError, EOFError, ValueError):
            self.stop = True                                # the engine is gone

    def _active(self, on):
        try:
            self.activity(on)
        except Exception:
            pass                                            # a priority Windows refused never stops a job

    def run(self):
        while not self.stop:
            msg, self.pending = self.pending, None
            if msg is None:
                try:
                    msg = self.conn.recv()
                except (EOFError, OSError):
                    break
            op = msg.get("op") if isinstance(msg, dict) else None
            if op == "quit":
                break
            if op == "unload":
                self.unload()
            elif op in OPS:
                self._active(True)                          # normal memory and I/O priority while it runs ...
                try:
                    self.job(msg)
                finally:
                    if self.pending is None:
                        self._active(False)                 # ... and low again when nothing else is waiting
            # a "cancel" with nothing streaming: nothing to stop
        self.unload(tell=False)

    def unload(self, tell=True):
        if self.session is not None:
            s, self.session = self.session, None
            self.loaded = ""
            try:
                s.close()
            finally:
                if tell:
                    self.send(t="state", job=None, loaded="")

    def _check(self, jid):
        """The cancelled() callback of a job: reads what came in meanwhile, without waiting."""
        def cancelled():
            try:
                while not self._cut and self.conn.poll(0):
                    m = self.conn.recv()
                    op = m.get("op") if isinstance(m, dict) else None
                    if op == "cancel" and m.get("job") == jid:
                        self._cut = True
                    elif op == "quit":
                        self.stop = self._cut = True
                    elif op == "unload":
                        self._cut = self._unload_after = True
                    elif op in OPS:
                        self.pending, self._cut = m, True     # the newer question wins
            except (EOFError, OSError):
                self.stop = self._cut = True
            return self._cut
        return cancelled

    def job(self, msg):
        jid = msg.get("job")
        self._cut = self._unload_after = False

        def fail(why):
            self.send(t="error", job=jid, why=why)

        op = msg["op"]
        paths = list(msg.get("paths") or [])
        if not 1 <= len(paths) <= MAX_IMAGES or (op == "compare") != (len(paths) == 2):
            return fail("At most two photos at a time: one to describe or ask about, two to compare.")
        model = msg.get("model") or {}
        settings = dict(msg.get("settings") or {})
        try:
            prompt = BUILD[op](msg.get("question") or "")
        except ValueError:
            return fail("Type a question.")
        cancelled = self._check(jid)
        watch = _Watch(self.send, cancelled, jid)
        load = self.session is None or self.loaded != model.get("id")
        if load:
            self.send(t="state", job=jid, state="loading")
            watch("prepare")
            try:
                self.prepare(model)                         # the runtime's DLLs before winrt (MSVCP140 order)
            except Exception as e:
                return fail(f"The picture model could not start ({type(e).__name__}).")
        # the photo first: one that is gone or unreadable costs no model load
        watch("photo")
        images = []
        for p in paths:
            got = self.decode(p, int(settings.get("side") or 512))
            if isinstance(got, str):
                return fail(got)
            images.append(got)
        if cancelled():
            return self._stopped(jid)
        if load:
            self.unload()                                   # one model resident: the other one leaves first
            try:
                self.session = self.open(model, settings, int(msg.get("gpu_layers") or 0), watch)
            except Cancelled:                               # stopped while loading: nothing stays loaded
                return self._stopped(jid)
            except AllocFailed as e:
                return fail(memory_note(e.need_mb))
            except FileNotFoundError:
                return fail("The model's files are missing. Download it again in Settings > Models.")
            except Exception as e:                          # a runtime that won't load, a damaged model file
                return fail(f"The picture model could not start ({type(e).__name__}).")
            self.loaded = model.get("id") or ""
            self.send(t="state", job=None, loaded=self.loaded)
            if cancelled():
                return self._stopped(jid)
        self.send(t="state", job=jid, state="answering")
        try:
            text = self.session.answer(images, prompt, prompts.max_tokens(op),
                                       lambda s: self.send(t="token", job=jid, s=s), cancelled, progress=watch)
        except Cancelled:                                   # stopped while the photo was read: the model stays
            return self._stopped(jid)
        except AllocFailed as e:                            # possibly after some tokens: a failed answer
            self.unload()
            return fail(memory_note(e.need_mb))
        except ValueError as e:
            return fail("The question is too long for this model. Ask something shorter."
                        if "too long" in str(e) else "The model couldn't take this photo.")
        except Exception as e:
            self.unload()
            return fail(f"The picture model failed ({type(e).__name__}).")
        if self._cut:
            return self._stopped(jid)
        self.send(t="done", job=jid, text=text)

    def _stopped(self, jid):
        self.send(t="state", job=jid, state="cancelled")
        if self._unload_after:
            self.unload()


def serve(conn, open_session=None, decode=None, prepare=None, activity=None):
    """The worker's loop until quit or the engine's end of the pipe closes (tests run it on a thread with fakes)."""
    real = open_session is None
    _Serve(conn, open_session or _open_session, decode or _decode, prepare or (_prepare if real else None),
           activity).run()


def main(conn):
    """The child process's entry (multiprocessing spawn)."""
    from .. import jobs, winapi
    jobs.join_workers()                 # into Find's worker group (memory/CPU caps, ends with the app)
    winapi.worker_priority()
    try:
        serve(conn, activity=winapi.worker_activity)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def start_process():
    """(engine's end of the pipe, the worker process)."""
    ctx = multiprocessing.get_context("spawn")
    mine, theirs = ctx.Pipe(duplex=True)
    p = ctx.Process(target=main, args=(theirs,), name="talk worker", daemon=True)
    p.start()
    theirs.close()
    return mine, p


# ---------- the engine side ----------
class Talker:
    """Drives the worker. `emit(event)` gets every `vision` event; `start()` -> (conn, process) (tests: a thread).
    `on_budget(mb)` is told the memory the talk worker may use now (the loaded or loading model's measured need,
    0 when none): the engine raises Find's memory limits by it (engine.run, watchdog talk_mb). `trace(msg, now)`
    (dev tools only, tools/measure_talk.py) sees every message of the worker as it arrives."""

    def __init__(self, emit, start=None, clock=time.monotonic, idle=IDLE, on_budget=None, trace=None):
        self._emit, self._start, self._clock, self.idle = emit, start or start_process, clock, idle
        self._on_budget, self._trace = on_budget, trace
        self._lock = threading.RLock()          # also held while emitting: no event of a job after it was replaced
        self._conn = self._proc = None
        self._job = None                        # {"job", "model", "name", "text", "files", "op", "need", "since"}
        self._work = None                       # what the worker is doing: {"job", "phase", "since", "deadline", ...}
        self._loaded = ""
        self._need = {}                         # model id -> its measured need (MB), from the jobs sent
        self._jneed = {}                        # job number -> its model's need, until the worker ended that job
        self._budget = 0
        self._exiting = {}                      # id(process) -> MB it may still hold until it has really exited
        self._used = clock()
        self._ids = itertools.count(1)
        self.answers = deque(maxlen=16)         # (file ids, op, text, model id) of finished answers (vision_keep)

    def next_id(self):
        with self._lock:
            return next(self._ids)

    @staticmethod
    def _event(cur, state, text="", note=""):
        return {"job": cur["job"], "state": state, "text": text, "model": cur["model"], "note": note}

    def _emit_safe(self, ev):
        try:
            self._emit(ev)
        except Exception:
            pass                                # a UI that went away never stops the worker's reader

    # -- memory budget --
    def budget_mb(self):
        """MB the talk worker may hold now: the loaded model's need, or the need of the model being loaded."""
        with self._lock:
            return self._budget

    def _update_budget(self):
        """The loaded model's need (until the worker says it unloaded it), the followed job's, and the need of the
        job the WORKER is still in (a Stop or a newer question during a load: the worker may still be allocating
        that model, in a step that can't be stopped, until it reports the job ended)."""
        b = self._need.get(self._loaded, 0) if self._loaded else 0
        if self._job is not None:
            b = max(b, self._job["need"])
        if self._work is not None:
            b = max(b, self._jneed.get(self._work["job"], 0))
        b = max([b, *self._exiting.values()])      # an ended worker keeps its allowance until it is gone
        if b != self._budget:
            self._budget = b
            if self._on_budget is not None:
                try:
                    self._on_budget(b)
                except Exception:
                    pass

    # -- jobs --
    def submit(self, job, name=""):
        """Start `job` (the worker message, with "job" from next_id()); the one running is cancelled first."""
        with self._lock:
            self._cancel_current()
            need = int((job.get("settings") or {}).get("need_mb") or 0)
            self._need[job["model"]["id"]] = need
            self._jneed[job["job"]] = need
            now = self._clock()
            self._job = {"job": job["job"], "model": job["model"]["id"], "name": name, "text": "",
                         "files": tuple(job.get("files") or ()), "op": job["op"], "need": need, "since": now,
                         "pct": -1, "told": False}
            if self._work is None:              # else the worker is still ending the last job: its bound holds
                self._work = self._fresh(job["job"], "start", now)
            self._used = now
            self._update_budget()               # before the worker starts loading: the limits are raised first
            msg = {k: v for k, v in job.items() if k != "files"}
            try:
                if self._conn is None:
                    self._spawn()
                self._conn.send(msg)
            except Exception:                   # could not start or reach the worker: say so for this job
                cur, self._job = self._job, None
                self._kill_locked()
                self._emit_safe(self._event(cur, "error", note="The picture model could not start. Try again."))

    def cancel(self):
        with self._lock:
            self._cancel_current()
            self._update_budget()

    def _cancel_current(self, note=""):
        cur, self._job = self._job, None
        if cur is None:
            return
        if self._conn is not None:
            try:
                self._conn.send({"op": "cancel", "job": cur["job"]})
            except (OSError, ValueError):
                pass
        self._emit_safe(self._event(cur, "cancelled", note=note))

    def emit_now(self, ev):
        """An event that isn't the worker's (stored OCR text shown first): it replaces the job followed."""
        with self._lock:
            self._cancel_current()
            self._update_budget()
            self._emit_safe(ev)

    # -- what the worker is doing (the hang deadline) --
    @staticmethod
    def _fresh(jid, phase, now):
        stall, _cap = PHASES[phase]
        return {"job": jid, "phase": phase, "since": now, "deadline": now + stall, "frac": -1.0, "pings": 0,
                "last": now}

    def _track(self, msg, now):
        """Moves the deadline only on real progress of the phase the worker is in (see the module docstring).
        Returns the work record when this message changed what the followed job shows, else None."""
        jid, t = msg.get("job"), msg.get("t")
        if jid is None:
            return None
        if t in ("done", "error") or (t == "state" and msg.get("state") == "cancelled"):
            cur = self._job
            self._work = self._fresh(cur["job"], "start", now) if cur is not None and cur["job"] != jid else None
            self._jneed.pop(jid, None)
            self._update_budget()               # the worker let go of that job: its allowance may go
            return None
        w = self._work
        if w is None or w["job"] != jid:
            w = self._work = self._fresh(jid, "start", now)
        if t == "progress":
            if msg.get("phase") != w["phase"]:
                return None                     # progress of another phase never counts for this one
            stall, cap = PHASES[w["phase"]]
            frac = msg.get("frac")
            if frac is not None:
                if w["phase"] in FRACTION_PHASES and float(frac) > w["frac"]:
                    w["frac"], w["deadline"], w["last"] = float(frac), now + stall, now
                    return w
            elif cap is not None:               # "still computing": bounded by the phase's cap
                w["pings"] += 1
                w["deadline"] = max(w["deadline"], min(now + stall, w["since"] + cap))
                w["last"] = now
            return None
        phase = {"phase": msg.get("phase"), "token": "answer",
                 "state": {"loading": "prepare", "answering": "image"}.get(msg.get("state"))}.get(t)
        if phase in PHASES and PHASE_ORDER.index(phase) > PHASE_ORDER.index(w["phase"]):
            w = self._work = self._fresh(jid, phase, now)       # phases only go forward
            if t == "phase":
                return w
        if t == "token" and w["phase"] == "answer":
            w["deadline"], w["last"] = now + ANSWER_S, now
        return None

    def _loading_note(self, cur, w):
        """The `loading` note of the followed job's phase: what loads and how far, "" when nothing new to say."""
        name = cur["name"] or cur["model"]
        if w["phase"] == "vision" and w["frac"] < 0:
            cur["pct"] = -1
            return f"Loading the vision part of {name}…"
        if w["phase"] in FRACTION_PHASES and w["frac"] >= 0:
            pct = int(w["frac"] * 100)
            if pct == cur["pct"]:
                return ""
            cur["pct"] = pct
            what = name if w["phase"] == "model" else f"the vision part of {name}"
            return f"Loading {what}… {pct} %"
        return ""

    # -- the worker's messages --
    def _spawn(self):
        conn, proc = self._start()
        self._conn, self._proc, self._loaded = conn, proc, ""
        threading.Thread(target=self._read, args=(conn,), daemon=True, name="talk-reader").start()

    def _read(self, conn):
        while True:
            try:
                msg = conn.recv()
            except Exception:                   # EOFError / OSError: the worker ended
                break
            if isinstance(msg, dict):
                self._on(conn, msg)
        with self._lock:
            if self._conn is not conn:
                return                          # stopped on purpose (or replaced): nothing to say
            cur, proc = self._job, self._proc
            self._job = None
            self._drop()
            if cur is not None:
                self._emit_safe(self._event(cur, "error", note="The picture model stopped unexpectedly. Try again."))
        if proc is not None:                    # its pipe closed: wait for the process itself, then the limits
            try:
                proc.join(10)
            finally:
                self._gone(proc)

    def _on(self, conn, msg):
        with self._lock:
            if conn is not self._conn:
                return
            now = self._clock()
            if self._trace is not None:
                try:
                    self._trace(msg, now)
                except Exception:
                    pass
            if msg.get("job") is None and "loaded" in msg:
                self._loaded = msg.get("loaded") or ""
                self._update_budget()
                return
            moved = self._track(msg, now)
            cur = self._job
            if cur is None or msg.get("job") != cur["job"]:
                return                          # a job that was replaced or cancelled: never shown
            t = msg.get("t")
            if moved is not None:
                note = self._loading_note(cur, moved)
                if note:
                    self._emit_safe(self._event(cur, "loading", note=note))
            elif t == "token":
                cur["text"] += str(msg.get("s") or "")
                self._emit_safe(self._event(cur, "answering", cur["text"]))
            elif t == "state":
                st = msg.get("state")
                if st == "loading":
                    self._emit_safe(self._event(cur, "loading", note=f"Loading {cur['name'] or cur['model']}"))
                elif st == "answering":
                    self._emit_safe(self._event(cur, "answering", cur["text"]))
                elif st == "cancelled":
                    self._end()
                    self._emit_safe(self._event(cur, "cancelled"))
            elif t == "done":
                self._end()
                text = str(msg.get("text") or "")
                self.answers.append((cur["files"], cur["op"], text, cur["model"]))
                self._emit_safe(self._event(cur, "done", text,
                                            "may not be exact" if prompts.flag_unverified(text) else ""))
            elif t == "error":
                self._end()                     # the UI drops any partial answer it showed
                self._emit_safe(self._event(cur, "error", note=str(msg.get("why") or "The answer failed.")))

    def _end(self):
        self._job = None
        self._used = self._clock()
        self._update_budget()

    # -- lifetime --
    def _drop(self):
        """Forget the worker. Its memory allowance stays (in _exiting) until _gone() says the process ended, so
        Find's limits never drop while it still holds the model (the worker group would be over its normal limit,
        and a photo or text worker allocating then would fail)."""
        if self._proc is not None and self._budget:
            self._exiting[id(self._proc)] = self._budget
        self._conn = self._proc = None
        self._work = None
        self._jneed.clear()                     # what the gone worker held stays in _exiting until it exited
        self._loaded = ""
        self._update_budget()

    def _gone(self, proc):
        with self._lock:
            if self._exiting.pop(id(proc), None) is not None:
                self._update_budget()

    def _kill_locked(self):
        """End the worker at once (it may be hung): TerminateProcess, no waiting for it to read a quit (a thread
        waits for its exit, then gives its allowance back)."""
        conn, proc = self._conn, self._proc
        self._drop()
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass

            def reap():
                try:
                    proc.join(10)
                finally:
                    self._gone(proc)
            threading.Thread(target=reap, daemon=True, name="talk-reap").start()
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self, why="", timeout=5.0, only_if_idle=None):
        """End the worker (and its model). A job still streaming ends as cancelled with `why` as its note. The
        worker gets the same cancel as a Stop first (so a load or an encode in progress ends at its next callback),
        then quit; one that hasn't exited after `timeout` is terminated.
        only_if_idle (seconds): only when no job is followed and none came for that long (checked under the lock,
        so a question arriving at that moment is never killed)."""
        with self._lock:
            if only_if_idle is not None and (self._job is not None or self._clock() - self._used < only_if_idle):
                return False
            conn, proc = self._conn, self._proc
            self._cancel_current(why)
            self._drop()
        if conn is None:
            return False
        try:
            conn.send({"op": "quit"})
        except (OSError, ValueError):
            pass
        if proc is not None:
            try:
                proc.join(timeout)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(2)
            finally:
                self._gone(proc)            # the limits come back down only now
        try:
            conn.close()
        except OSError:
            pass
        return True

    def release_if_idle(self, idle=None):
        """The governor's tick: no question for `idle` (IDLE) seconds -> the worker and its model go."""
        with self._lock:
            if self._proc is None:
                return False
        return self.stop(only_if_idle=self.idle if idle is None else idle)

    def check_deadline(self):
        """The governor's tick: the worker made no progress in its phase past that phase's bound (PHASES), so it
        hangs (a driver stall, a load that stopped reading): it is ended, the job followed gets an error, and the
        next question starts a fresh worker. True when it did. A question still waiting for the last one to stop
        gets the note STOPPING (once) after STOPPING_NOTE_S."""
        with self._lock:
            w, cur, now = self._work, self._job, self._clock()
            if w is None:
                return False
            if now < w["deadline"]:
                if (cur is not None and w["job"] != cur["job"] and not cur["told"]
                        and now - cur["since"] >= STOPPING_NOTE_S):
                    cur["told"] = True
                    self._emit_safe(self._event(cur, "loading", note=STOPPING))
                return False
            self._job = None
            self._kill_locked()
            self._used = now
            if cur is not None:
                self._emit_safe(self._event(cur, "error", note=HUNG))
            return True

    def work(self):
        """What the worker is doing now (a copy): {"job", "phase", "since", "deadline", "frac", "pings", "last"},
        or None (dev tools and tests)."""
        with self._lock:
            return dict(self._work) if self._work is not None else None

    def state(self):
        with self._lock:
            return {"loaded": self._loaded, "busy": self._job is not None,
                    "job": self._job["job"] if self._job else 0, "running": self._proc is not None}

    def pids(self):
        with self._lock:
            pid = getattr(self._proc, "pid", None)
            return {pid: "talk worker"} if pid else {}

    def kept_model(self, file_id, text):
        """The model that wrote `text` as a description of this photo (for vdesc), or ""."""
        with self._lock:
            for files, op, said, mid in reversed(self.answers):
                if files == (file_id,) and op == "describe" and said.strip() == text.strip():
                    return mid
        return ""
