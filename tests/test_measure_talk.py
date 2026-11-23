"""tools/measure_talk.py (dev only): the talk timings in the catalog come from it, so it is kept runnable."""
import importlib.util
import os

import pytest

# the tool measures memory with psutil, a dev-only dependency (not in requirements-lock.txt, not in CI)
pytestmark = pytest.mark.skipif(importlib.util.find_spec("psutil") is None,
                                reason="psutil (dev dependency) not installed")

PATH =os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "measure_talk.py")
_spec = importlib.util.spec_from_file_location("measure_talk", PATH)
measure_talk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(measure_talk)


def test_no_personal_paths_and_every_level_of_the_catalog():
    src = open(PATH, encoding="utf-8").read()
    assert "Users\\" not in src and "Users/" not in src
    from nobadfind import governor, models
    assert set(models.TALK_LEVELS) <= set(governor.CPU_CAP)
    assert [op for op, _i, _q in measure_talk.JOBS] == ["describe", "ask", "compare", "describe"]


def test_refuses_a_model_that_is_not_a_talk_model(tmp_path):
    with pytest.raises(SystemExit, match="not a talk model"):
        measure_talk.main(["--model", "minilm-l6-v2", "--model-dir", str(tmp_path), "--runtime-dir", str(tmp_path),
                           "--device", "cpu", "--images", str(tmp_path), "--level", "light",
                           "--out", str(tmp_path / "x.json")])


def test_the_hog_never_targets_below_the_floor(tmp_path):
    with pytest.raises(SystemExit, match="under the floor"):
        measure_talk.main(["--model", "qwen3vl-2b", "--model-dir", str(tmp_path), "--runtime-dir", str(tmp_path),
                           "--device", "cpu", "--images", str(tmp_path), "--level", "gentle",
                           "--out", str(tmp_path / "x.json"), "--leave-free-mb", "1000"])


@pytest.mark.parametrize("floor", ["0", "1000"])
def test_the_floor_has_a_hard_minimum(tmp_path, floor):
    with pytest.raises(SystemExit, match="hard minimum 1024"):
        measure_talk.main(["--model", "qwen3vl-2b", "--model-dir", str(tmp_path), "--runtime-dir", str(tmp_path),
                           "--device", "cpu", "--images", str(tmp_path), "--level", "gentle",
                           "--out", str(tmp_path / "x.json"), "--leave-free-mb", "3800", "--floor-mb", floor])
    with pytest.raises(ValueError, match="hard minimum"):
        measure_talk.start_hog(3800, int(floor), [])


def test_ctrl_c_while_the_hog_settles_still_leaves_it_to_the_finally(monkeypatch):
    """Review M5: the Popen is handed out before the settle wait, so main's finally kills it."""
    started = []

    class FakePopen:
        def __init__(self, args):
            started.append(self)
    monkeypatch.setattr(measure_talk.subprocess, "Popen", FakePopen)

    def interrupt(s):
        raise KeyboardInterrupt
    monkeypatch.setattr(measure_talk.time, "sleep", interrupt)
    held = []
    with pytest.raises(KeyboardInterrupt):
        measure_talk.start_hog(3800, 1536, held)
    assert held == started and len(held) == 1


def test_phase_stats_count_progress_as_the_talker_does():
    tr = [(1.0, {"t": "state", "job": 1, "state": "loading"}), (1.5, {"t": "phase", "job": 1, "phase": "model"}),
          (2.0, {"t": "progress", "job": 1, "phase": "model", "frac": 0.2}),
          (9.0, {"t": "progress", "job": 1, "phase": "model", "frac": 0.2}),       # not growing: no progress
          (10.0, {"t": "progress", "job": 1, "phase": "model", "frac": 1.0}),
          (10.5, {"t": "phase", "job": 1, "phase": "image"}),
          (11.0, {"t": "progress", "job": 1, "phase": "image", "frac": None}),
          (13.0, {"t": "phase", "job": 1, "phase": "answer"}), (13.2, {"t": "token", "job": 1, "s": "A"}),
          (14.0, {"t": "token", "job": 2, "s": "other job"}), (13.5, {"t": "done", "job": 1, "text": "A"})]
    st = measure_talk.phase_stats(tr, 0.0, 13.5, 1)
    assert st["start"] == {"s": 1.0, "longest_no_progress_s": 1.0, "progress": 0}
    assert st["model"] == {"s": 9.0, "longest_no_progress_s": 8.0, "progress": 2}
    assert st["image"] == {"s": 2.5, "longest_no_progress_s": 2.0, "progress": 1}
    assert st["answer"] == {"s": 0.5, "longest_no_progress_s": 0.3, "progress": 1}


def test_refuses_to_start_without_free_memory_for_the_model(tmp_path):
    with pytest.raises(SystemExit, match="MB free"):
        measure_talk.main(["--model", "qwen3vl-2b", "--model-dir", str(tmp_path), "--runtime-dir", str(tmp_path),
                           "--device", "vulkan", "--images", str(tmp_path), "--level", "full",
                           "--out", str(tmp_path / "x.json"), "--margin-mb", "100000000"])


@pytest.mark.parametrize("runtime", ["llama-cpu", "llama-vulkan"])
def test_assess_says_what_the_app_says_for_both_models(runtime):
    """assess() runs in every measurement (and --assess-only): both talk models through api.talk_assess
    (capability.assess) on the runtime measured. A fake hardware scan; no model is loaded."""
    import types
    from nobadfind import api, models
    pc = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "avx512_vnni": False, "gpu": "", "vram_gb": 0.0,
          "directml": False, "disk_free_gb": 200.0, "ssd": True}
    hw = types.SimpleNamespace(scan=lambda: dict(pc))
    low = measure_talk.assess(3000, api, hw, models, runtime)
    assert low["free_mb"] == 3000 and low["runtime"] == runtime
    assert low["deeper"][0] is False and low["deeper"][1].startswith("Not now: it needs about 2.4 GB")
    assert low["quick"][0] is False and low["quick"][1].startswith("Not now: it needs about 1.0 GB")
    high = measure_talk.assess(6000, api, hw, models, runtime)
    assert high["deeper"][0] is True and high["quick"][0] is True
