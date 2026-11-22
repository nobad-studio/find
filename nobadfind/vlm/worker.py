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
    {"t": "token", "job": n, "s": text}  ·  {"t": "done", "job": n, "text": answer}  ·  {"t": "error", "job": n, "why"}

- One model resident: a job for another model unloads the current one first.
- A new job (or cancel / quit) arriving while an answer streams stops that answer at its next token; the model
  stays loaded. The engine drops anything still arriving for a job it no longer follows.
- Out of memory (session.AllocFailed), loading or in the middle of an answer: the model is unloaded, the job ends
  with an error naming the catalog's measured need, and the worker keeps serving (nothing is retried).
- llama.cpp's logging is switched off before any model loads (llama_api.silence_logs): its prompt echo carries
  the user's question.

The engine side (`Talker`) starts the worker on the first job, follows ONE job at a time, turns the worker's
messages into `vision` events ({"job", "state", "text", "model", "note"}; "text" is the whole answer so far) and
stops the worker after IDLE seconds without a question (governor tick, engine.worker_hooks), on memory pressure,
before a runtime reinstall and when the engine stops.
"""
import itertools
import multiprocessing
import os
import threading
import time
from collections import deque

from . import prompts
from .session import AllocFailed

IDLE = 180                      # = embed.Lazy.IDLE (tests keep them equal): the talk model leaves after 3 min idle
MAX_IMAGES = 2                  # compare is two photos; more is refused
OPS = ("describe", "ask", "compare")
GONE = "This photo is no longer there."
BUILD = {"describe": lambda q: prompts.describe(), "ask": prompts.ask, "compare": lambda q: prompts.compare(q or None)}


def _size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


def memory_note(need_mb):
    return f"Not enough memory right now (needs about {_size(need_mb)}). Close something or try again later."


# ---------- the worker process ----------
def _open_session(model, settings, gpu_layers):
    """The real model: the pinned runtime from its folder, logging off, then Session (vlm/session.py)."""
    from . import llama_api, session
    lib = llama_api.load(model["runtime"], quiet=True)
    llama_api.silence_logs(lib)                         # again: a no-op unless the runtime was loaded without quiet
    return session.Session(lib, model["model"], model["mmproj"], settings, gpu_layers)


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


class _Serve:
    def __init__(self, conn, open_session, decode):
        self.conn, self.open, self.decode = conn, open_session, decode
        self.session, self.loaded = None, ""
        self.pending, self.stop = None, False
        self._cut, self._unload_after = False, False

    def send(self, **msg):
        try:
            self.conn.send(msg)
        except (OSError, EOFError, ValueError):
            self.stop = True                                # the engine is gone

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
                self.job(msg)
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
        """The cancelled() callback of an answer: reads what came in meanwhile, without waiting."""
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
        if self.session is None or self.loaded != model.get("id"):
            self.unload()                                   # one model resident: the other one leaves first
            self.send(t="state", job=jid, state="loading")
            try:
                self.session = self.open(model, settings, int(msg.get("gpu_layers") or 0))
            except AllocFailed as e:
                return fail(memory_note(e.need_mb))
            except FileNotFoundError:
                return fail("The model's files are missing. Download it again in Settings > Models.")
            except Exception as e:                          # a runtime that won't load, a damaged model file
                return fail(f"The picture model could not start ({type(e).__name__}).")
            self.loaded = model.get("id") or ""
            self.send(t="state", job=None, loaded=self.loaded)
        cancelled = self._check(jid)
        if cancelled():
            return self._stopped(jid)
        images = []
        for p in paths:
            got = self.decode(p, int(settings.get("side") or 512))
            if isinstance(got, str):
                return fail(got)
            images.append(got)
        if cancelled():
            return self._stopped(jid)
        self.send(t="state", job=jid, state="answering")
        try:
            text = self.session.answer(images, prompt, prompts.max_tokens(op),
                                       lambda s: self.send(t="token", job=jid, s=s), cancelled)
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


def serve(conn, open_session=None, decode=None):
    """The worker's loop until quit or the engine's end of the pipe closes (tests run it on a thread with fakes)."""
    _Serve(conn, open_session or _open_session, decode or _decode).run()


def main(conn):
    """The child process's entry (multiprocessing spawn)."""
    from .. import jobs, winapi
    jobs.join_workers()                 # into Find's worker group (memory/CPU caps, ends with the app)
    winapi.worker_priority()
    try:
        serve(conn)
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
    """Drives the worker. `emit(event)` gets every `vision` event; `start()` -> (conn, process) (tests: a thread)."""

    def __init__(self, emit, start=None, clock=time.monotonic, idle=IDLE):
        self._emit, self._start, self._clock, self.idle = emit, start or start_process, clock, idle
        self._lock = threading.RLock()          # also held while emitting: no event of a job after it was replaced
        self._conn = self._proc = None
        self._job = None                        # {"job", "model", "name", "text", "files", "op"}: the one followed
        self._loaded = ""
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

    # -- jobs --
    def submit(self, job, name=""):
        """Start `job` (the worker message, with "job" from next_id()); the one running is cancelled first."""
        with self._lock:
            self._cancel_current()
            if self._conn is None:
                self._spawn()
            self._job = {"job": job["job"], "model": job["model"]["id"], "name": name, "text": "",
                         "files": tuple(job.get("files") or ()), "op": job["op"]}
            self._used = self._clock()
            msg = {k: v for k, v in job.items() if k != "files"}
            try:
                self._conn.send(msg)
            except (OSError, ValueError):
                cur, self._job = self._job, None
                self._drop()
                self._emit_safe(self._event(cur, "error", note="The picture model stopped unexpectedly. Try again."))

    def cancel(self):
        with self._lock:
            self._cancel_current()

    def _cancel_current(self):
        cur, self._job = self._job, None
        if cur is None:
            return
        if self._conn is not None:
            try:
                self._conn.send({"op": "cancel", "job": cur["job"]})
            except (OSError, ValueError):
                pass
        self._emit_safe(self._event(cur, "cancelled"))

    def emit_now(self, ev):
        """An event that isn't the worker's (stored OCR text shown first): it replaces the job followed."""
        with self._lock:
            self._cancel_current()
            self._emit_safe(ev)

    # -- the worker's messages --
    def _spawn(self):
        conn, proc = self._start()
        self._conn, self._proc, self._loaded = conn, proc, ""
        threading.Thread(target=self._read, args=(conn,), daemon=True, name="talk-reader").start()

    def _read(self, conn):
        while True:
            try:
                msg = conn.recv()
            except (EOFError, OSError):
                break
            except Exception:
                break
            if isinstance(msg, dict):
                self._on(conn, msg)
        with self._lock:
            if self._conn is not conn:
                return                          # stopped on purpose (or replaced): nothing to say
            cur = self._job
            self._job = None
            self._drop()
            if cur is not None:
                self._emit_safe(self._event(cur, "error", note="The picture model stopped unexpectedly. Try again."))

    def _on(self, conn, msg):
        with self._lock:
            if conn is not self._conn:
                return
            if msg.get("job") is None and "loaded" in msg:
                self._loaded = msg.get("loaded") or ""
                return
            cur = self._job
            if cur is None or msg.get("job") != cur["job"]:
                return                          # a job that was replaced or cancelled: never shown
            t = msg.get("t")
            if t == "token":
                cur["text"] += str(msg.get("s") or "")
                self._emit_safe(self._event(cur, "answering", cur["text"]))
            elif t == "state":
                st = msg.get("state")
                if st == "loading":
                    self._emit_safe(self._event(cur, "loading", note=f"Loading {cur['name'] or cur['model']}"))
                elif st == "answering":
                    self._emit_safe(self._event(cur, "answering", cur["text"]))
                elif st == "cancelled":
                    self._job = None
                    self._used = self._clock()
                    self._emit_safe(self._event(cur, "cancelled"))
            elif t == "done":
                self._job = None
                self._used = self._clock()
                text = str(msg.get("text") or "")
                self.answers.append((cur["files"], cur["op"], text, cur["model"]))
                self._emit_safe(self._event(cur, "done", text,
                                            "may not be exact" if prompts.flag_unverified(text) else ""))
            elif t == "error":
                self._job = None                # the UI drops any partial answer it showed
                self._used = self._clock()
                self._emit_safe(self._event(cur, "error", note=str(msg.get("why") or "The answer failed.")))

    # -- lifetime --
    def _drop(self):
        self._conn = self._proc = None
        self._loaded = ""

    def stop(self, why="", timeout=5.0):
        """End the worker (and its model). A job still streaming ends with `why` as its error (else cancelled)."""
        with self._lock:
            conn, proc, cur = self._conn, self._proc, self._job
            self._job = None
            self._drop()
            if cur is not None:
                self._emit_safe(self._event(cur, "error", note=why) if why else self._event(cur, "cancelled"))
        if conn is None:
            return False
        try:
            conn.send({"op": "quit"})
        except (OSError, ValueError):
            pass
        if proc is not None:
            proc.join(timeout)
            if proc.is_alive():
                proc.terminate()
                proc.join(2)
        try:
            conn.close()
        except OSError:
            pass
        return True

    def release_if_idle(self, idle=None):
        """The governor's tick: no question for `idle` (IDLE) seconds -> the worker and its model go."""
        with self._lock:
            quiet = self._proc is not None and self._job is None and \
                self._clock() - self._used >= (self.idle if idle is None else idle)
        return self.stop() if quiet else False

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
