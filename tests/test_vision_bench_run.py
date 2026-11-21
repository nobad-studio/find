"""tools/vision_bench/run.py: one supervised process per candidate x device; a crash, hang or bad photo is recorded,
never the end of the run."""
import os
import subprocess

import pytest
import sys
import time

from tools.vision_bench import run
from tools.vision_bench.adapters import Adapter, DecodeError

FAKE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vbench_fake_child.py")


def _alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def test_supervise_timeout_kills():
    pids = []
    t0 = time.monotonic()
    code, out = run.supervise([sys.executable, FAKE, "sleep"], 1.0, sample=lambda p: pids.extend(p))
    assert code is None and time.monotonic() - t0 < 15
    assert pids and not _alive(pids[0])


def test_supervise_returns_last_json_line():
    code, out = run.supervise([sys.executable, FAKE, "ok"], 30)
    assert code == 0 and run.last_json(out)["status"] == "ok"


def test_tree_pids():
    rows = [(10, 1, "python.exe"), (11, 10, "llama-mtmd-cli.exe"), (12, 11, "conhost.exe"), (20, 1, "x.exe")]
    assert sorted(run.tree_pids(10, rows)) == [10, 11, 12]


def _devs(cuda=False):
    return [{"device": "cpu", "backend": "ort", "available": True, "why": ""},
            {"device": "cpu", "backend": "llama", "available": True, "why": ""},
            {"device": "cuda", "backend": "llama", "available": cuda, "why": "CUDA needs an NVIDIA graphics card"}]


def test_crash_recorded_and_next_runs():
    modes = {"a": "crash", "b": "ok"}
    res = run.bench([], [("a", "cpu", "ort"), ("b", "cpu", "ort")], _devs(),
                    child_cmd=lambda c, d: [sys.executable, FAKE, modes[c]], timeout_s=30)
    assert [r["status"] for r in res] == ["crash", "ok"]
    assert res[0]["exit_code"] == 3 and res[1]["candidate"] == "b"


def test_timeout_recorded():
    res = run.bench([], [("a", "cpu", "ort")], _devs(), child_cmd=lambda c, d: [sys.executable, FAKE, "sleep"],
                    timeout_s=1)
    assert res[0]["status"] == "timeout"


def test_unavailable_device_not_run():
    started = []
    res = run.bench([], [("q", "cuda", "llama")], _devs(cuda=False),
                    child_cmd=lambda c, d: started.append(c) or [sys.executable, FAKE, "ok"], timeout_s=30)
    assert res[0]["status"] == "not available" and "NVIDIA" in res[0]["why"] and not started


class _Fake(Adapter):
    candidate = "fake"

    def load(self, models_dir, device):
        pass

    def run(self, task, image, image2, question):
        if "bad" in image:
            raise DecodeError("corrupt")
        self.last_ms = 7.0
        return "a dog"


def test_decode_error_item_does_not_stop_run():
    items = [{"id": i, "image": f"{i}.jpg", "image2": None, "task": "detect", "question": None, "kind": "objects",
              "expect": ["dog"]} for i in ("one", "bad", "three")]
    r = run.run_one("fake", "cpu", items, "M", "T", adapters={"fake": lambda tools_dir=None: _Fake()})
    assert [i["status"] for i in r["items"]] == ["ok", "error: decode", "ok"]
    assert r["status"] == "ok" and r["ms_per_item"] == 7.0
    assert r["scores"]["objects"] == 1.0          # a photo that can't be decoded isn't the model's fault
    assert r["errors"] == 1


class _Flaky(_Fake):
    def run(self, task, image, image2, question):
        if "boom" in image:
            raise RuntimeError("out of memory")
        if "hang" in image:
            raise subprocess.TimeoutExpired("llama", 120)
        return super().run(task, image, image2, question)


def _items(*names, expect=("dog",), kind="objects"):
    return [{"id": n, "image": f"{n}.jpg", "image2": None, "task": "detect", "question": None, "kind": kind,
             "expect": list(expect) if kind == "objects" else expect} for n in names]


def test_model_errors_and_timeouts_score_zero():
    r = run.run_one("fake", "cpu", _items("one", "boom", "hang"), "M", "T",
                    adapters={"fake": lambda tools_dir=None: _Flaky()})
    st = [i["status"] for i in r["items"]]
    assert st[0] == "ok" and st[1].startswith("error: RuntimeError") and st[2] == "timeout"
    assert r["scores"]["objects"] == pytest.approx(1 / 3)
    assert r["timeouts"] == 1


def test_scoring_error_is_per_item(monkeypatch):
    monkeypatch.setattr(run, "score_item", lambda it, a: 1 / 0 if it["id"] == "two" else 1.0)
    r = run.run_one("fake", "cpu", _items("one", "two"), "M", "T", adapters={"fake": lambda tools_dir=None: _Fake()})
    assert [i["status"] for i in r["items"]] == ["ok", "error: score"]


class _NoGpu(_Fake):
    def run(self, task, image, image2, question):
        from tools.vision_bench.adapters import GpuNotUsed
        raise GpuNotUsed("llama.cpp ran on the CPU (offloaded 0/29 layers)")


def test_gpu_not_used_makes_the_run_not_available():
    r = run.run_one("fake", "vulkan", _items("one", "two"), "M", "T",
                    adapters={"fake": lambda tools_dir=None: _NoGpu()})
    assert r["status"] == "not available" and "CPU" in r["why"]


def test_crash_reason_comes_from_stderr():
    res = run.bench([], [("a", "cpu", "ort")], _devs(),
                    child_cmd=lambda c, d: [sys.executable, FAKE, "crash_msg"], timeout_s=30)
    assert res[0]["status"] == "crash" and "model file missing" in res[0]["why"]
