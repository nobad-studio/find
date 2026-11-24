"""The named pipe the UI connects to: `\\\\.\\pipe\\NOBADFind-<user SID>` (ctypes only, overlapped I/O).

Security:
- DACL from SDDL `D:P(D;;GA;;;NU)(A;;GA;;;<user SID>)`: only this user, network logons denied, nothing inherited.
- `PIPE_REJECT_REMOTE_CLIENTS`: no connections from other machines.
- `FILE_FLAG_FIRST_PIPE_INSTANCE` on the first instance: if any process already holds the name, the engine
  refuses to serve instead of sharing it. The next listening instance is created before a connected one is handed
  off, so the name is never free while the engine runs. (The Flutter client also checks the pipe's owner is the
  current user, that the process serving it is NobadFind.exe next to it at medium integrity outside any
  AppContainer, and allows identification-level impersonation only: pipe_client.dart engineProblem.)
- Each connected client's own process token is checked (client_problem): below medium integrity or in an
  AppContainer, it is dropped before anything is read (the DACL and the default label already stop them; this
  fails closed if they ever don't). Security review 2026-11-22, M1.
- Lines are capped at protocol.MAX_MESSAGE; a client that sends more is dropped. A client that stops reading is
  dropped after WRITE_TIMEOUT_MS, so it can't stall the engine.

One reader thread per client; requests run on a small thread pool so a slow thumbnail doesn't hold up a search.
Methods in `slow` (they wait for the user: a folder dialog, a permission prompt) get a thread of their own, so
they can never use up the pool; each of them lets only one call wait at a time (the handlers say "busy").
"""
import ctypes
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ctypes import wintypes

from ..log import log
from .protocol import (INTERNAL_ERROR, INVALID_REQUEST, MAX_MESSAGE, LineBuffer, encode, error, handle_line, method_of,
                       run_after)

SLOW_LOG_MS = 300                    # answers slower than this are logged (method name, time)


MAX_CLIENTS = 8
# Requests one client may have waiting or running at once (security review 2026-11-22, L2): past this, the engine
# stops reading from that client until some are answered, so a client writing as fast as it can doesn't queue
# without bound. The UI has a handful in flight (a search, previews of the rows on screen, a status).
MAX_INFLIGHT = 32
# The status lane (1.2.0 S2): state reports (handlers.STATUS_LANE) run on STATUS_WORKERS threads of their own. One
# client may have STATUS_WORKERS running + STATUS_WAITING waiting there; the next gets a "busy: try again" error at
# once (the UI retries it, rpc.dart), so the lane's queue is bounded. `inline` methods skip all of this.
STATUS_WORKERS = 2
STATUS_WAITING = 4
BUF = 64 * 1024
WRITE_TIMEOUT_MS = 5000

PIPE_ACCESS_DUPLEX = 0x3
FILE_FLAG_OVERLAPPED = 0x40000000
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = PIPE_READMODE_BYTE = PIPE_WAIT = 0
PIPE_REJECT_REMOTE_CLIENTS = 0x8
ERROR_IO_PENDING, ERROR_PIPE_CONNECTED, ERROR_PIPE_BUSY = 997, 535, 231
WAIT_OBJECT_0, INFINITE = 0, 0xFFFFFFFF
INVALID_HANDLE = ctypes.c_void_p(-1).value


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t), ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]


class _SA(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


_dll = {}


def _dlls():
    if not _dll:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        POV = ctypes.POINTER(_OVERLAPPED)
        for dll, specs in ((k, (("CreateNamedPipeW", H, [wintypes.LPCWSTR, D, D, D, D, D, D, ctypes.POINTER(_SA)]),
                                ("ConnectNamedPipe", B, [H, POV]),
                                ("DisconnectNamedPipe", B, [H]),
                                ("CreateEventW", H, [P, B, B, wintypes.LPCWSTR]),
                                ("SetEvent", B, [H]),
                                ("ResetEvent", B, [H]),
                                ("CloseHandle", B, [H]),
                                ("ReadFile", B, [H, P, D, P, POV]),
                                ("WriteFile", B, [H, P, D, P, POV]),
                                ("GetOverlappedResult", B, [H, POV, ctypes.POINTER(D), B]),
                                ("CancelIoEx", B, [H, POV]),
                                ("WaitForMultipleObjects", D, [D, ctypes.POINTER(H), B, D]),
                                ("WaitForSingleObject", D, [H, D]),
                                ("GetNamedPipeClientProcessId", B, [H, ctypes.POINTER(D)]),
                                ("GetCurrentProcess", H, []),
                                ("LocalFree", P, [P]))),
                           (a, (("OpenProcessToken", B, [H, D, ctypes.POINTER(H)]),
                                ("GetTokenInformation", B, [H, ctypes.c_int, P, D, ctypes.POINTER(D)]),
                                ("ConvertSidToStringSidW", B, [P, ctypes.POINTER(wintypes.LPWSTR)]),
                                ("ConvertStringSecurityDescriptorToSecurityDescriptorW", B,
                                 [wintypes.LPCWSTR, D, ctypes.POINTER(P), ctypes.POINTER(D)])))):
            for name, res, args in specs:
                f = getattr(dll, name)
                f.restype, f.argtypes = res, args
        _dll.update(k=k, a=a)
    return _dll["k"], _dll["a"]


def user_sid():
    """The current user's SID as a string (S-1-5-21-...)."""
    k, a = _dlls()
    tok = wintypes.HANDLE()
    if not a.OpenProcessToken(k.GetCurrentProcess(), 0x8, ctypes.byref(tok)):     # TOKEN_QUERY
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        need = wintypes.DWORD()
        a.GetTokenInformation(tok, 1, None, 0, ctypes.byref(need))                   # TokenUser
        buf = ctypes.create_string_buffer(need.value)
        if not a.GetTokenInformation(tok, 1, buf, need, ctypes.byref(need)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = _SID_AND_ATTRIBUTES.from_buffer(buf).Sid
        s = wintypes.LPWSTR()
        if not a.ConvertSidToStringSidW(sid, ctypes.byref(s)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return s.value
        finally:
            k.LocalFree(s)
    finally:
        k.CloseHandle(tok)


def pipe_name(sid=None):
    return "\\\\.\\pipe\\NOBADFind-" + (sid or user_sid())


def sddl_for(sid):
    """Protected DACL: network logons denied, full access for this user only."""
    if not (sid.startswith("S-1-") and all(c.isdigit() or c in "S-" for c in sid)):
        raise ValueError("not a SID")
    return f"D:P(D;;GA;;;NU)(A;;GA;;;{sid})"


class Conn:
    """One connected client: its pipe handle, a write lock, what it subscribed to, which of its windows are up
    (ui_shown / ui_hidden) and its process id."""

    def __init__(self, k, handle):
        self._k, self.handle = k, handle
        self.events = set()
        self.shown = set()
        self.alive = True
        self._wlock = threading.Lock()
        self._wov = _OVERLAPPED()
        self._wov.hEvent = k.CreateEventW(None, True, False, None)
        pid = wintypes.DWORD()
        self.pid = pid.value if k.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)) else 0
        self._closed = False
        self.inflight = threading.BoundedSemaphore(MAX_INFLIGHT)
        self.lane_pending = 0                # status-lane calls running or waiting (Server._lane_take / _lane_done)

    def send(self, obj):
        data = encode(obj)
        if len(data) > MAX_MESSAGE + 1:
            data = encode(error(obj.get("id"), INTERNAL_ERROR, "Reply too big"))
        k = self._k
        with self._wlock:
            if not self.alive:
                return False
            buf = ctypes.create_string_buffer(data, len(data))
            k.ResetEvent(self._wov.hEvent)
            if not k.WriteFile(self.handle, buf, len(data), None, ctypes.byref(self._wov)) \
                    and ctypes.get_last_error() != ERROR_IO_PENDING:
                self.alive = False
                return False
            if k.WaitForSingleObject(self._wov.hEvent, WRITE_TIMEOUT_MS) != WAIT_OBJECT_0:
                k.CancelIoEx(self.handle, ctypes.byref(self._wov))           # not reading: give up on it
                self.alive = False
            n = wintypes.DWORD()
            if not k.GetOverlappedResult(self.handle, ctypes.byref(self._wov), ctypes.byref(n), True) \
                    or n.value != len(data):
                self.alive = False
            return self.alive

    def close(self, linger=False):
        """linger=True: let the client still read what was already written (e.g. the "Message too big" error).
        DisconnectNamedPipe throws away anything the client hasn't read yet; closing the handle alone doesn't
        (the client reads it, then gets end-of-file) and never blocks, unlike FlushFileBuffers."""
        k = self._k
        with self._wlock:
            self.alive = False
            if self._closed:
                return
            self._closed = True
        k.CancelIoEx(self.handle, None)
        if not linger:
            k.DisconnectNamedPipe(self.handle)
        k.CloseHandle(self.handle)
        k.CloseHandle(self._wov.hEvent)


MEDIUM = 0x2000


def client_verdict(integrity, app_container):
    """Why a client process may not talk to the engine, or None (security review 2026-11-22, M1, the engine's half):
    the pipe's DACL and its default medium label already keep out other users, AppContainers and low-integrity
    writers; this checks the connected process's own token again and fails closed."""
    if integrity is None or integrity < 0 or app_container is None:
        return "Windows can't say who the client is"
    if app_container:
        return "the client runs in an AppContainer"
    if integrity < MEDIUM:
        return "the client runs at low integrity"
    return None


def client_problem(pid):
    """client_verdict for the process pid, from its token (ntfs's token readers)."""
    from .. import ntfs
    if not pid:
        return "Windows can't say who the client is"
    k, a = ntfs._k32(), ntfs._advapi()
    hp = k.OpenProcess(0x1000, False, pid)                       # PROCESS_QUERY_LIMITED_INFORMATION
    if not hp:
        return "the client process can't be opened"
    try:
        tok = wintypes.HANDLE()
        if not a.OpenProcessToken(hp, 0x8, ctypes.byref(tok)):  # TOKEN_QUERY
            return "the client's token can't be read"
        try:
            return client_verdict(ntfs.integrity_of(tok), ntfs.token_dword(tok, 29))   # TokenIsAppContainer
        finally:
            k.CloseHandle(tok)
    finally:
        k.CloseHandle(hp)


def _request_id(line):
    """The id of a request line, or None (a notification, or not JSON: nobody waits for an answer)."""
    try:
        rid = json.loads(line).get("id")
    except Exception:
        return None
    return rid if isinstance(rid, (int, str)) and not isinstance(rid, bool) else None


class Server:
    """Serves `methods` (name -> fn(params, conn)) on the user's pipe. start() is False if the pipe can't be made.
    check_client(pid) -> a reason or None: a connected client with a reason is dropped before it is read."""

    def __init__(self, methods=None, name=None, workers=4, check_client=client_problem):
        self._k, self._a = _dlls()
        self.check_client = check_client
        self.methods = methods or {}
        self.on_drop = None                  # fn(conn) after a client is gone (pipe liveness: Rpc._dropped)
        self.slow = set()                    # method names answered on a thread of their own
        self.status_lane = set()             # state reports, answered on the small status pool
        self.inline = set()                  # dict-read-only reports (the status beat), answered on the reader thread
        self.sid = user_sid()
        self.name = name or pipe_name(self.sid)
        self._stop = threading.Event()
        self._stop_evt = self._k.CreateEventW(None, True, False, None)
        self._conns = set()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc")
        self._status_pool = ThreadPoolExecutor(max_workers=STATUS_WORKERS, thread_name_prefix="rpc-status")
        self._lane_lock = threading.Lock()
        self._sd = ctypes.c_void_p()
        if not self._a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl_for(self.sid), 1, ctypes.byref(self._sd), None):          # SDDL_REVISION_1
            raise ctypes.WinError(ctypes.get_last_error())
        self._sa = _SA(ctypes.sizeof(_SA), self._sd, False)
        self._first = True
        self._next = None
        self.thread = None

    def start(self):
        try:
            self._next = self._make_instance()
        except OSError as e:
            log(f"rpc pipe not available (error {e.winerror}): another NOBAD Find engine may be running", "warn")
            return False
        self.thread = threading.Thread(target=self._accept_loop, daemon=True, name="rpc-accept")
        self.thread.start()
        log("rpc pipe ready")
        return True

    def stop(self):
        self._stop.set()
        self._k.SetEvent(self._stop_evt)
        if self.thread:
            self.thread.join(3)
        with self._lock:
            conns = list(self._conns)
            self._conns.clear()
        for c in conns:
            c.close(linger=True)             # a client still reads what was written (quit's reply, quitting)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._status_pool.shutdown(wait=False, cancel_futures=True)
        self._k.LocalFree(self._sd)
        self._sd = None

    def clients(self):
        with self._lock:
            return [c for c in self._conns if c.alive]

    def drop(self, conn, linger=False):
        with self._lock:
            if conn not in self._conns:
                return
            self._conns.discard(conn)
        conn.close(linger)
        if self.on_drop is not None:
            try:
                self.on_drop(conn)
            except Exception as e:
                log(f"rpc client end hook failed: {type(e).__name__}", "warn")

    def allow_foreground(self):
        """A hotkey press gives the engine the right to bring a window to the front: pass it on to the UIs."""
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        for c in self.clients():
            if c.pid and not user32.AllowSetForegroundWindow(wintypes.DWORD(c.pid)):
                # Windows' foreground rules: the window may open behind others, which looks like "it didn't open"
                log(f"could not let the UI (pid {c.pid}) take the front (error {ctypes.get_last_error()})", "warn")

    # ----- pipe -----
    def _make_instance(self):
        mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (FILE_FLAG_FIRST_PIPE_INSTANCE if self._first else 0)
        h = self._k.CreateNamedPipeW(self.name, mode, PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT |
                                     PIPE_REJECT_REMOTE_CLIENTS, MAX_CLIENTS, BUF, BUF, 0, ctypes.byref(self._sa))
        if not h or h == INVALID_HANDLE:
            raise ctypes.WinError(ctypes.get_last_error())
        self._first = False
        return h

    def _wait(self, event):
        """Wait for an overlapped operation or stop(). True = the operation finished."""
        arr = (wintypes.HANDLE * 2)(event, self._stop_evt)
        return self._k.WaitForMultipleObjects(2, arr, False, INFINITE) == WAIT_OBJECT_0

    def _accept_loop(self):
        k = self._k
        ov = _OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        n = wintypes.DWORD()
        try:
            while not self._stop.is_set():
                h = self._next
                k.ResetEvent(ov.hEvent)
                ok = k.ConnectNamedPipe(h, ctypes.byref(ov))
                err = ctypes.get_last_error()
                if not ok and err == ERROR_IO_PENDING:
                    if not self._wait(ov.hEvent):              # stopping
                        k.CancelIoEx(h, ctypes.byref(ov))
                        k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), True)
                        k.CloseHandle(h)
                        return
                    ok = k.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(n), False)
                elif not ok and err == ERROR_PIPE_CONNECTED:
                    ok = True
                if not ok:                                     # gone before we got it: reuse the instance
                    k.DisconnectNamedPipe(h)
                    continue
                self._next = None
                while not self._stop.is_set():                 # the next instance first: the name stays ours
                    try:
                        self._next = self._make_instance()
                        break
                    except OSError as e:
                        if e.winerror != ERROR_PIPE_BUSY:      # busy = MAX_CLIENTS in use: wait for one to end
                            log(f"rpc pipe instance failed (error {e.winerror})", "warn")
                        if self._stop.wait(0.5):
                            break
                conn = Conn(k, h)
                try:
                    problem = self.check_client(conn.pid)
                except Exception as e:
                    problem = f"the client check failed ({type(e).__name__})"
                if problem:
                    log(f"rpc client refused: {problem}", "warn")
                    conn.close()
                else:
                    with self._lock:
                        self._conns.add(conn)
                    threading.Thread(target=self._serve, args=(conn,), daemon=True, name="rpc-conn").start()
                if self._next is None:
                    return
        finally:
            k.CloseHandle(ov.hEvent)
            if self._next is not None and self._stop.is_set():
                k.CloseHandle(self._next)
                self._next = None

    def _serve(self, conn):
        k = self._k
        ov = _OVERLAPPED()
        ov.hEvent = k.CreateEventW(None, True, False, None)
        buf = ctypes.create_string_buffer(BUF)
        lines = LineBuffer()
        n = wintypes.DWORD()
        linger = False
        try:
            while not self._stop.is_set() and conn.alive:
                k.ResetEvent(ov.hEvent)
                if not k.ReadFile(conn.handle, buf, BUF, None, ctypes.byref(ov)) \
                        and ctypes.get_last_error() != ERROR_IO_PENDING:
                    break                                      # the client closed its end
                if not self._wait(ov.hEvent):
                    k.CancelIoEx(conn.handle, ctypes.byref(ov))
                    k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), True)
                    break
                if not k.GetOverlappedResult(conn.handle, ctypes.byref(ov), ctypes.byref(n), False):
                    break
                try:
                    got = lines.feed(buf.raw[:n.value])
                except ValueError:
                    linger = conn.send(error(None, INVALID_REQUEST, "Message too big"))   # it must get to read it
                    break
                for line in got:
                    while not conn.inflight.acquire(timeout=0.5):     # backpressure: wait for answers first
                        if self._stop.is_set() or not conn.alive:
                            return
                    if method_of(line) in self.slow:
                        threading.Thread(target=self._answer, args=(conn, line), daemon=True,
                                         name="rpc-slow").start()
                        continue
                    m = method_of(line)
                    if m in self.inline:                       # never refused, never queued behind slow reports
                        self._answer(conn, line)
                        continue
                    lane = m in self.status_lane
                    if lane and not self._lane_take(conn):
                        conn.inflight.release()
                        rid = _request_id(line)
                        if rid is not None and not conn.send(error(rid, INTERNAL_ERROR, "busy: try again")):
                            return
                        continue
                    try:
                        (self._status_pool if lane else self._pool).submit(self._answer, conn, line, lane)
                    except RuntimeError:                       # the pool is shut down: stopping
                        conn.inflight.release()
                        if lane:
                            self._lane_done(conn)
                        break
        except Exception as e:
            log(f"rpc connection ended: {type(e).__name__}", "warn")
        finally:
            k.CloseHandle(ov.hEvent)
            self.drop(conn, linger or self._stop.is_set())    # stopping: what was written stays readable

    def _lane_take(self, conn):
        with self._lane_lock:
            if conn.lane_pending >= STATUS_WORKERS + STATUS_WAITING:
                return False
            conn.lane_pending += 1
            return True

    def _lane_done(self, conn):
        with self._lane_lock:
            conn.lane_pending = max(0, conn.lane_pending - 1)

    def _answer(self, conn, line, lane=False):
        try:
            self._answer1(conn, line)
        except Exception as e:                                 # in a pool thread nobody would see it
            log(f"rpc answer failed: {type(e).__name__}", "warn")
        finally:
            if lane:
                self._lane_done(conn)
            try:
                conn.inflight.release()
            except (AttributeError, ValueError):               # a test's Conn without one
                pass

    def _answer1(self, conn, line):
        t0 = time.perf_counter()
        after = []
        reply = handle_line(line, self.methods, conn, after=after)
        if reply is not None and conn.alive and not conn.send(reply):
            self.drop(conn)
        run_after(after)                                       # e.g. quit: only now may the engine stop
        took = (time.perf_counter() - t0) * 1000
        m = method_of(line)
        if m != "search" and m not in self.slow and took >= SLOW_LOG_MS:   # 0.9.3: slow answers, by name only
            log(f"rpc {str(m)[:40]} {took:.0f} ms")
        if method_of(line) == "search":                       # how long it took, never the words searched for
            r = reply.get("result") if isinstance(reply, dict) else None
            log(f"rpc search {(time.perf_counter() - t0) * 1000:.1f} ms "
                f"(ranking {r.get('ms') if isinstance(r, dict) else '?'} ms)")
