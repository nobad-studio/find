"""Which of NOBAD Find's own processes are running, what each one is and what it uses (the Index page's Processes).

Only Find's own processes are listed, never another program's or another user's:
- the engine (this process) and the processes in its job (jobs.OUTER: the workers);
- its children and their children, by parent process id in one Toolhelp snapshot. A child has to have started after
  its parent, so a process id Windows handed out again can't pull a stranger in;
- the UIs connected to its pipe (the pipe's DACL lets only this user in) and the turbo helper it started.

What each one is comes first from what the engine knows (the pools' process ids, the turbo helper's id, the pipe's
clients), then from the program and command line of its own children only (read once per process): the Flutter UI
with --bar is the search bar, a `--multiprocessing-fork` child no pool holds is a worker that is ending, Python's
resource tracker is named as such.

Cost: one snapshot and one OpenProcess per listed process, at most every EVERY seconds, and only while something
asks for the full status (the Index page subscribes to status_full only while it is open).
"""
import ctypes
import os
import time
from ctypes import wintypes

from . import jobs, winapi

EVERY = 1.9             # seconds: reuse the last sample when asked again sooner (status_full comes every 2 s)
STARTING_S = 15.0       # a UI that hasn't connected within this long since it started isn't "starting" any more
IDLE_CPU = 0.5          # percent of the PC: below it a worker is called idle
UI_EXE = "nobad_find.exe"

# role id -> (name, one line about it). Plain words: the Index page shows them as they are.
ROLES = {
    "engine": ("NOBAD Find engine", "The main process: the index, searching, watching folders and choosing the pace."),
    "text": ("Text reader worker", "Reads the words inside documents, and inside pictures with Windows OCR."),
    "meaning": ("Meaning worker", "Runs the AI model for text, so you can search by what files mean."),
    "photo": ("Photo worker", "Runs the AI model for photos; Windows' own decoders open the pictures."),
    "talk": ("Photo talk worker", "Runs the model that describes and answers questions about a photo you asked "
             "about; it ends 3 minutes after the last question."),
    "window": ("The window", "NOBAD Find's window. Closing it ends this process."),
    "bar": ("The search bar", "The quick find bar you open with the hotkey."),
    "turbo": ("Turbo index helper (elevated)",
              "Reads file names and changes from the NTFS file table, never file contents. Runs as administrator."),
    "open_with": ("Open with helper", "Shows Windows' Open with list for one file, then ends."),
    "ending": ("Worker ending", "A worker from a pool NOBAD Find closed; it ends on its own."),
    "mp_helper": ("Python multiprocessing helper", "Started by Python's multiprocessing for NOBAD Find's workers."),
    "client": ("Connected program", "A program of yours connected to NOBAD Find's private pipe."),
    "other": ("Helper", "A program NOBAD Find started."),
}
ORDER = ("engine", "window", "bar", "text", "meaning", "photo", "talk", "turbo", "open_with", "ending", "mp_helper",
         "client", "other")
WORKER_ROLES = ("text", "meaning", "photo")
# indexer.worker_names() -> role id
WORKER_NAMES = {"text reader": "text", "meaning worker": "meaning", "photo worker": "photo", "talk worker": "talk"}


# ---------- reading Windows (every function returns something empty when it can't) ----------
class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


class _UString(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]


_D = {}


def _dlls():
    if not _D:
        k = ctypes.WinDLL("kernel32", use_last_error=True)       # own instances: argtypes don't leak elsewhere
        nt = ctypes.WinDLL("ntdll")
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, ctypes.c_void_p
        k.CreateToolhelp32Snapshot.restype, k.CreateToolhelp32Snapshot.argtypes = H, [D, D]
        k.Process32FirstW.restype, k.Process32FirstW.argtypes = B, [H, ctypes.POINTER(_PE32)]
        k.Process32NextW.restype, k.Process32NextW.argtypes = B, [H, ctypes.POINTER(_PE32)]
        k.OpenProcess.restype, k.OpenProcess.argtypes = H, [D, B, D]
        k.CloseHandle.restype, k.CloseHandle.argtypes = B, [H]
        nt.NtQueryInformationProcess.restype = ctypes.c_long
        nt.NtQueryInformationProcess.argtypes = [H, ctypes.c_int, P, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        _D["k"], _D["nt"] = k, nt
    return _D["k"], _D["nt"]


def snapshot():
    """[(pid, parent pid, program file name)] for every process now (one Toolhelp snapshot); [] when it fails."""
    if not winapi.WIN:
        return []
    k, _nt = _dlls()
    snap = k.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out = []
    try:
        e = _PE32()
        e.dwSize = ctypes.sizeof(_PE32)
        ok = k.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), int(e.th32ParentProcessID), e.szExeFile))
            ok = k.Process32NextW(snap, ctypes.byref(e))
    finally:
        k.CloseHandle(snap)
    return out


def command_line(pid):
    """The command line of one process ("" when it can't be read). Only called for Find's own children."""
    if not winapi.WIN:
        return ""
    k, nt = _dlls()
    h = k.OpenProcess(0x1000, False, int(pid))                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = 65536 + ctypes.sizeof(_UString)                 # a command line is at most 32767 characters
        buf = ctypes.create_string_buffer(size)
        got = wintypes.ULONG()
        if nt.NtQueryInformationProcess(h, 60, buf, size, ctypes.byref(got)) != 0:   # ProcessCommandLineInformation
            return ""
        us = _UString.from_buffer(buf)
        return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer and us.Length else ""
    finally:
        k.CloseHandle(h)


# ---------- deciding (pure: the tests give it fakes) ----------
def classify(pid, exe, cmd, known, ui_pids):
    """The role id of one of Find's own processes. known: {pid: role id} the engine is sure of."""
    if pid in known:
        return known[pid]
    exe, cmd = (exe or "").lower(), cmd or ""
    if exe == UI_EXE:
        return "bar" if "--bar" in cmd.split() else "window"
    if "--multiprocessing-fork" in cmd:
        if "resource_tracker" in cmd:
            return "mp_helper"
        return "ending"                     # a Python worker that no pool holds now: its pool was closed
    if "multiprocessing.resource_tracker" in cmd or "multiprocessing.forkserver" in cmd:
        return "mp_helper"
    if "--open-with" in cmd:
        return "open_with"
    if "--turbo" in cmd:
        return "turbo"
    return "client" if pid in ui_pids else "other"


def family(main, rows, started):
    """The process ids of main's children, their children and so on. started(pid) -> Unix start time (0 unknown):
    a child that didn't start after its parent is a stranger that got a reused process id, and is left out."""
    kids = {}
    for pid, ppid, _exe in rows:
        if pid != ppid:
            kids.setdefault(ppid, []).append(pid)
    out, todo = set(), [main]
    while todo:
        parent = todo.pop()
        p_at = started(parent)
        for c in kids.get(parent, ()):
            if c in out or c == main:
                continue
            c_at = started(c)
            if p_at and c_at and c_at >= p_at:
                out.add(c)
                todo.append(c)
    return out


def note_for(role, cpu, age_s, readable, connected, sampled_before):
    """A short note when there is something to say: idle, starting, ending, not readable."""
    if not readable:
        if role == "turbo":
            return "Runs as administrator: Windows doesn't let NOBAD Find read its numbers"
        return "Windows doesn't let NOBAD Find read its numbers"
    if role == "ending":
        return "Ending: its pool was closed"
    if role in ("window", "bar") and not connected:
        if age_s is not None and age_s < STARTING_S:
            return "Starting"
        return "Not connected to the engine: starting or ending"
    if role in WORKER_ROLES and sampled_before and cpu < IDLE_CPU:
        return "Idle: waiting for work"
    return ""


class Sampler:
    """sample(): one row per process of Find's own (see the module docstring), reused for EVERY seconds."""

    def __init__(self, wall=time.time):
        self._wall = wall
        self._cpu = {}                     # pid -> (time, cpu seconds)
        self._cmd = {}                     # (pid, started) -> command line
        self._at, self._rows = None, []

    def sample(self, now, main, job_pids=(), known=None, ui_pids=()):
        if self._at is not None and 0 <= now - self._at < EVERY:
            return self._rows
        known, ui_pids, job = dict(known or {}), set(ui_pids or ()), set(job_pids or ())
        known[main] = "engine"
        try:
            rows = snapshot()
        except Exception:
            rows = []
        exe = {pid: name for pid, _pp, name in rows}
        infos = {}

        def info(pid):
            if pid not in infos:
                try:
                    infos[pid] = jobs.process_info(pid)
                except Exception:
                    infos[pid] = {"pid": pid, "cpu_seconds": 0.0, "memory_mb": 0, "private_mb": 0, "started": 0.0,
                                  "ok": False}
            return infos[pid]

        mine = family(main, rows, lambda p: info(p).get("started") or 0.0)
        mine |= job | set(known) | ui_pids
        mine.add(main)
        cores = os.cpu_count() or 1
        out, seen = [], {}
        for pid in mine:
            i = info(pid)
            started = i.get("started") or 0.0
            if pid in known:
                role = known[pid]
            else:
                key = (pid, started)
                if key not in self._cmd:
                    try:
                        self._cmd[key] = command_line(pid)
                    except Exception:
                        self._cmd[key] = ""
                role = classify(pid, exe.get(pid, ""), self._cmd[key], known, ui_pids)
            if role not in ROLES:
                role = "other"
            last = self._cpu.get(pid)
            cpu = 0.0
            if last and now > last[0]:
                cpu = max(0.0, min(100.0, (i["cpu_seconds"] - last[1]) / (now - last[0]) / cores * 100))
            seen[pid] = (now, i["cpu_seconds"])
            age = max(0, int(self._wall() - started)) if started else None
            readable = bool(i.get("ok", True))
            name, about = ROLES[role]
            if role == "other" and exe.get(pid):
                name = f"Helper ({exe[pid]})"
            out.append({"name": name, "role": role, "about": about, "pid": int(pid), "cpu": round(cpu, 1),
                        "memory_mb": int(i.get("memory_mb") or 0), "private_mb": int(i.get("private_mb") or 0),
                        "age_s": age, "readable": readable, "in_job": pid in job or pid == main,
                        "note": note_for(role, cpu, age, readable, pid in ui_pids, bool(last))})
        live = {(p, s) for p, s in self._cmd if p in mine}
        self._cmd = {k: v for k, v in self._cmd.items() if k in live}
        self._cpu = seen
        out.sort(key=lambda r: (ORDER.index(r["role"]), r["pid"]))
        self._at, self._rows = now, out
        return out
