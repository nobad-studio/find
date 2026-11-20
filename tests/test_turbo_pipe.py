"""0.9.1 regression: the turbo helper's pipe must let a write through while a read is waiting.

The helper's main loop waits in read() for the engine; its scan thread writes rows. With a synchronous pipe
handle Windows ran those one at a time, so the first write waited for a message the engine never sent (it was
waiting for those rows): turbo read nothing and the engine's indexer hung. A real pipe, unelevated."""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named pipes")


def _server(name):
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateNamedPipeW.restype = wintypes.HANDLE
    k.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    # duplex, byte mode, blocking server end (the test reads it plainly)
    h = k.CreateNamedPipeW(name, 0x3, 0x0, 1, 65536, 65536, 0, None)
    assert h and h != ctypes.c_void_p(-1).value
    return k, h


def _client(name, overlapped):
    from nobadfind import ntfs
    k = ntfs._k32()
    flags = ntfs.FILE_FLAG_OVERLAPPED if overlapped else 0
    h = k.CreateFileW(name, 0x80000000 | 0x40000000, 0, None, 3, flags, None)       # GENERIC_READ|WRITE, OPEN_EXISTING
    assert h and h != ntfs.INVALID_HANDLE
    return h


def _write_while_reading(overlapped):
    from nobadfind import ntfs
    name = rf"\\.\pipe\NOBADFind-test-turbo-{os.getpid()}-{int(overlapped)}"
    k, srv = _server(name)
    ch = _client(name, overlapped)
    pipe = ntfs._Pipe(ch) if overlapped else _SyncPipe(ch)
    threading.Thread(target=pipe.read, daemon=True).start()       # the helper's main loop, waiting for the engine
    time.sleep(0.3)
    done = threading.Event()

    def write():
        pipe.send({"t": "rows", "drive": "C:\\", "rows": []})
        done.set()
    threading.Thread(target=write, daemon=True).start()
    ok = done.wait(3)
    if not ok:                                                     # unblock the old pipe so the test can end
        n = wintypes.DWORD()
        k.WriteFile(srv, b"x\n", 2, ctypes.byref(n), None)
        done.wait(3)
    k.CloseHandle(srv)
    return ok


class _SyncPipe:
    """The pre-0.9.1 pipe: synchronous ReadFile / WriteFile on one handle."""

    def __init__(self, h):
        self.h = h

    def send(self, obj):
        from nobadfind import ntfs
        data = ntfs.encode(obj)
        n = wintypes.DWORD()
        buf = ctypes.create_string_buffer(data, len(data))
        ntfs._k32().WriteFile(self.h, buf, len(data), ctypes.byref(n), None)

    def read(self):
        from nobadfind import ntfs
        buf = ctypes.create_string_buffer(65536)
        n = wintypes.DWORD()
        ntfs._k32().ReadFile(self.h, buf, 65536, ctypes.byref(n), None)


def test_the_helper_pipe_writes_while_a_read_waits():
    assert _write_while_reading(overlapped=True) is True


def test_the_old_synchronous_pipe_did_deadlock():
    """Keeps the reason on record: if this ever passes, Windows changed, not the bug."""
    assert _write_while_reading(overlapped=False) is False
