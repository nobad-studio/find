"""tools/vision_bench/report.py: the tables the maintainer picks 1.0's defaults from."""
from tools.vision_bench.report import deep_pass_hours, summary

PROBE = {"hardware": {"gpu": "Intel(R) Iris(R) Xe Graphics", "vram_gb": 0.1, "ram_gb": 15.7, "cores": 12,
                      "threads": 16}, "devices": []}
OK = {"candidate": "qwen3vl-2b-q4", "device": "cpu", "backend": "llama", "status": "ok", "load_s": 3.2,
      "ms_per_item": 6000.0, "peak_private_mb": 2100.0, "peak_gpu_mb": None, "errors": 0,
      "scores": {"count": 0.8, "text": 0.6, "all": 0.7}, "items": []}
FL = {"candidate": "florence2-base-ft", "device": "cpu", "backend": "ort", "status": "ok", "load_s": 1.0,
      "ms_per_item": 900.0, "peak_private_mb": 600.0, "peak_gpu_mb": None, "errors": 1,
      "scores": {"objects": 0.5, "all": 0.5}, "items": []}
NA = {"candidate": "qwen3vl-2b-q4", "device": "cuda", "backend": "llama", "status": "not available",
      "why": "CUDA needs an NVIDIA graphics card"}


def test_summary_has_pc_line_and_tables():
    text = summary([FL, OK, NA], PROBE)
    assert "Intel(R) Iris(R) Xe Graphics" in text and "15.7 GB" in text and "12 cores" in text
    assert "### L1: see and read" in text and "### L2: talk" in text
    l1, l2 = text.split("### L2: talk")
    assert "florence2-base-ft" in l1 and "qwen3vl-2b-q4" in l2


def test_not_available_rows_show_why():
    assert "CUDA needs an NVIDIA graphics card" in summary([NA], PROBE)


def test_deep_pass_hours():
    assert deep_pass_hours(6000) == "16.7 h"
    assert deep_pass_hours(None) == "-"
    assert "16.7 h" in summary([OK], PROBE)


def test_errors_column():
    assert "| 1 |" in summary([FL], PROBE)
