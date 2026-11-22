"""tools/measure_talk.py (dev only): the talk timings in the catalog come from it, so it is kept runnable."""
import importlib.util
import os

import pytest

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "measure_talk.py")
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


def test_refuses_to_start_without_free_memory_for_the_model(tmp_path):
    with pytest.raises(SystemExit, match="MB free"):
        measure_talk.main(["--model", "qwen3vl-2b", "--model-dir", str(tmp_path), "--runtime-dir", str(tmp_path),
                           "--device", "vulkan", "--images", str(tmp_path), "--level", "full",
                           "--out", str(tmp_path / "x.json"), "--margin-mb", "100000000"])
