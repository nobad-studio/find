"""The Index page's Processes: which processes are Find's own, what each one is, and the notes. All fakes: no
snapshot of this PC, no command lines read, nothing started."""
import os

import pytest

from nobadfind import api as api_mod, procs

MAIN = 100
EXE = "NobadFind.exe"
FORK = '"C:\\\\Find\\\\NobadFind.exe" "--multiprocessing-fork" "parent_pid=100" "pipe_handle=3664"'


class World:
    """A fake PC: rows (pid, parent, exe), start times, command lines, CPU seconds and memory per pid."""

    def __init__(self):
        self.rows = [(MAIN, 4, EXE), (4, 0, "explorer.exe")]
        self.started = {MAIN: 1000.0, 4: 10.0}
        self.cmd, self.cpu, self.unreadable = {}, {}, set()
        self.cmd_reads = []

    def add(self, pid, parent, exe, cmd="", started=1100.0):
        self.rows.append((pid, parent, exe))
        self.started[pid] = started
        self.cmd[pid] = cmd

    def info(self, pid):
        ok = pid in self.started and pid not in self.unreadable
        return {"pid": pid, "cpu_seconds": self.cpu.get(pid, 0.0), "memory_mb": 50 if ok else 0,
                "private_mb": 70 if ok else 0, "started": self.started.get(pid, 0.0) if ok else 0.0, "ok": ok}

    def command_line(self, pid):
        self.cmd_reads.append(pid)
        return self.cmd.get(pid, "")


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(procs, "snapshot", lambda: list(w.rows))
    monkeypatch.setattr(procs, "command_line", w.command_line)
    monkeypatch.setattr(procs.jobs, "process_info", w.info)
    return w


def roles(rows):
    return {r["pid"]: r["role"] for r in rows}


def test_classify_by_what_the_engine_knows_then_the_command_line():
    c = procs.classify
    assert c(5, EXE, FORK, {5: "text"}, set()) == "text"
    assert c(5, "nobad_find.exe", '"x\\\\nobad_find.exe" --bar', {}, set()) == "bar"
    assert c(5, "nobad_find.exe", '"x\\\\nobad_find.exe" --page index', {}, set()) == "window"
    assert c(5, EXE, FORK, {}, set()) == "ending"
    assert c(5, "python.exe", '-c "from multiprocessing.resource_tracker import main;main(5)"', {}, set()) == "mp_helper"
    assert c(5, EXE, f"{EXE} --open-with C:\\\\a.txt", {}, set()) == "open_with"
    assert c(5, EXE, f"{EXE} --turbo serve", {}, set()) == "turbo"
    assert c(5, "python.exe", "measure.py", {}, {5}) == "client"
    assert c(5, "conhost.exe", "", {}, set()) == "other"


def test_family_leaves_out_a_reused_process_id():
    rows = [(MAIN, 1, EXE), (200, MAIN, EXE), (300, 200, "x.exe"), (400, MAIN, "stranger.exe"), (500, 9, "y.exe")]
    at = {MAIN: 1000.0, 200: 1001.0, 300: 1002.0, 400: 900.0, 500: 1003.0}
    assert procs.family(MAIN, rows, lambda p: at.get(p, 0.0)) == {200, 300}       # 400 started before its "parent"


def test_sampler_lists_find_own_processes_only(world):
    world.add(201, MAIN, EXE, FORK)                       # a text reader (the engine knows it)
    world.add(202, MAIN, EXE, FORK)                       # meaning worker
    world.add(203, MAIN, "nobad_find.exe", '"C:\\\\Find\\\\nobad_find.exe" --bar')
    world.add(204, MAIN, "nobad_find.exe", '"C:\\\\Find\\\\nobad_find.exe" --page search')
    world.add(205, MAIN, EXE, FORK)                       # no pool holds it: ending
    world.add(900, 4, "notepad.exe", "notepad.exe")       # the user's own program: not Find's
    world.add(901, 77, "other.exe", "other.exe")          # another program altogether
    rows = procs.Sampler(wall=lambda: 1200.0).sample(0.0, MAIN, job_pids=[MAIN, 201, 202],
                                                     known={201: "text", 202: "meaning"}, ui_pids={203, 204})
    assert roles(rows) == {MAIN: "engine", 201: "text", 202: "meaning", 203: "bar", 204: "window", 205: "ending"}
    assert [r["role"] for r in rows] == ["engine", "window", "bar", "text", "meaning", "ending"]   # a stable order
    assert 900 not in world.cmd_reads and 901 not in world.cmd_reads                             # never read
    assert set(world.cmd_reads) == {203, 204, 205}                     # only children the engine didn't know
    by = {r["pid"]: r for r in rows}
    assert by[201]["name"] == "Text reader worker" and "Windows OCR" in by[201]["about"]
    assert by[202]["name"] == "Meaning worker" and "AI model for text" in by[202]["about"]
    assert by[205]["note"].startswith("Ending")
    assert by[MAIN]["age_s"] == 200 and by[201]["age_s"] == 100
    assert by[201]["memory_mb"] == 50 and by[201]["private_mb"] == 70 and by[201]["readable"]
    assert by[201]["in_job"] and not by[203]["in_job"]


def test_sampler_cpu_idle_note_and_two_second_reuse(world):
    world.add(201, MAIN, EXE, FORK)
    world.add(202, MAIN, EXE, FORK)
    s = procs.Sampler(wall=lambda: 1200.0)
    known = {201: "text", 202: "photo"}
    first = s.sample(0.0, MAIN, [MAIN, 201, 202], known)
    assert all(r["cpu"] == 0.0 and r["note"] == "" for r in first)          # no rate yet: not called idle
    world.cpu[201] = 2.0 * (os.cpu_count() or 1) * 0.5                       # 50 % of the PC over 2 s
    assert s.sample(1.0, MAIN, [MAIN, 201, 202], known) is first             # asked again within EVERY: reused
    by = {r["pid"]: r for r in s.sample(2.0, MAIN, [MAIN, 201, 202], known)}
    assert by[201]["cpu"] == 50.0 and by[201]["note"] == ""
    assert by[202]["cpu"] == 0.0 and by[202]["note"].startswith("Idle")


def test_sampler_command_lines_read_once_per_process(world):
    world.add(205, MAIN, EXE, FORK)
    s = procs.Sampler(wall=lambda: 1200.0)
    for t in (0.0, 2.0, 4.0):
        s.sample(t, MAIN)
    assert world.cmd_reads == [205]


def test_turbo_helper_unreadable_and_ui_starting(world):
    world.add(300, MAIN, "nobad_find.exe", '"x\\\\nobad_find.exe" --page index', started=1195.0)
    world.unreadable.add(301)
    world.started[301] = 1100.0                           # the elevated helper: known by id, can't be opened
    by = {r["pid"]: r for r in procs.Sampler(wall=lambda: 1200.0).sample(0.0, MAIN, [MAIN], {301: "turbo"})}
    assert by[301]["role"] == "turbo" and not by[301]["readable"] and "administrator" in by[301]["note"]
    assert by[301]["age_s"] is None
    assert by[300]["role"] == "window" and by[300]["note"] == "Starting"      # 5 s old, not on the pipe yet


class _Turbo:
    def helper_pid(self):
        return 301


class _Ix:
    def worker_names(self):
        return {201: "text reader", 202: "meaning worker", 203: "photo worker"}


def test_api_knows_its_workers_turbo_and_ui(world, monkeypatch):
    a = api_mod.Api.__new__(api_mod.Api)
    a._indexer, a._turbo, a._prev = _Ix(), _Turbo(), None
    a._sampler = procs.Sampler(wall=lambda: 1200.0)
    a._ui_pids = lambda: {204}
    monkeypatch.setattr(api_mod.jobs, "OUTER", None)
    monkeypatch.setattr(api_mod.os, "getpid", lambda: MAIN)
    for pid in (201, 202, 203, 301):
        world.add(pid, MAIN, EXE, FORK)
    world.add(204, MAIN, "nobad_find.exe", '"x\\\\nobad_find.exe" --page search')
    r = a._resources(0.0, None)
    got = roles(r["processes"])
    assert got == {MAIN: "engine", 201: "text", 202: "meaning", 203: "photo", 204: "window", 301: "turbo"}
    assert all("in_job" not in p for p in r["processes"])
    assert {p["pid"]: p["note"] for p in r["processes"]}[204] == ""              # connected
    assert r["memory_mb"] == 50 * 6
