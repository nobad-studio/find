"""capability.assess: what this PC can run RIGHT NOW (free memory, commit, graphics memory, load, battery), not
what is installed. Table tests over a small catalog with round numbers, plus the real catalog."""
import pytest

from nobadfind import capability, models
from nobadfind.governor import Sample


def smp(**kw):
    base = dict(t=0.0, cpu=20.0, gpu=10.0, mem_load=40, free_mb=8000, find_cpu=0.0, foreground="", game=False,
                presentation=False, hung=False, battery=False, call=False, idle_s=0.0)
    base.update(kw)
    return Sample(**base)


PC16 = {"ram_gb": 15.7, "cores": 8, "threads": 16, "directml": False, "vram_gb": 0.1, "disk_free_gb": 100.0}
PC_GPU = dict(PC16, directml=True, vram_gb=8.0)


def model(mid, ram_mb, tier="balanced", feature="text"):
    return {"id": mid, "feature": feature, "tier": tier, "ram_mb": ram_mb, "builtin": False, "dim": 384,
            "files": {"model.onnx": ("x", 10 * 1048576, "0" * 64)}}


CAT = [model("small", 100, "light"), model("mid", 900), model("big4g", 4096, "best"),
       model("pic", 400, "balanced", "photo"),
       {"id": "ocr", "feature": "ocr", "tier": "light", "ram_mb": 0, "builtin": True, "files": {}}]


def run(sample, pc=PC16, measured=None):
    return capability.assess(sample, pc, measured, catalog=CAT)


@pytest.mark.parametrize("sample, can, cannot, word", [
    # the maintainer's example: a 16 GB PC with 3 GB free must NOT get a model that needs 4 GB
    (smp(free_mb=3000), {"small", "mid", "pic", "ocr"}, {"big4g"}, "free"),
    (smp(free_mb=12000), {"small", "mid", "big4g", "pic", "ocr"}, set(), ""),
    (smp(free_mb=1800), {"ocr"}, {"small", "mid", "big4g", "pic"}, "free"),     # 300 MB over the reserve
    (smp(free_mb=12000, commit_pct=91.0), {"ocr"}, {"small", "mid", "big4g"}, "commit 91%"),
    (smp(free_mb=12000, commit_pct=60.0, commit_free_mb=2000), {"small", "mid", "ocr"}, {"big4g"}, "promise"),
    (smp(free_mb=12000, battery_saver=True), {"small", "ocr"}, {"mid", "big4g", "pic"}, "battery saver"),
    (smp(free_mb=12000, battery=True), {"small", "mid", "pic"}, {"big4g"}, "charger"),
    (smp(free_mb=12000, cpu=95.0, find_cpu=2.0), {"small", "ocr"}, {"mid", "big4g"}, "processor (93%)"),
    (smp(free_mb=12000, cpu=95.0, find_cpu=40.0), {"small", "mid", "big4g"}, set(), ""),   # that's Find itself
])
def test_live_capability_table(sample, can, cannot, word):
    r = run(sample)
    assert {m for m in can if r["can_run"][m]} == can
    assert {m for m in cannot if not r["can_run"][m]} == cannot
    for m in cannot:
        assert word in r["why"][m]


def test_installed_ram_alone_would_say_yes_but_live_says_no():
    big = model("big4g", 4096, "best")
    assert models.capable(big, PC16) == (True, "")                      # the old, installed-only answer
    r = capability.assess(smp(free_mb=3000), PC16, {}, catalog=[big])
    assert r["can_run"]["big4g"] is False
    assert r["why"]["big4g"] == ("Not now: it needs about 4.0 GB plus 1.2 GB to spare, and 2.9 GB of memory is "
                                 "free (NOBAD Find leaves 1.5 GB to Windows)")
    assert r["budget"]["free_mb"] == 3000 and r["budget"]["usable_mb"] == 1500


def test_measured_ram_and_speed_win_over_the_catalog():
    r = run(smp(free_mb=3000), measured={"mid": {"ram_mb": 3000}})
    assert r["can_run"]["mid"] is False                                 # measured here: bigger than the catalog
    r = run(smp(free_mb=12000), measured={"big4g": {"ram_mb": 500}})
    assert r["can_run"]["big4g"] is True
    r = run(smp(free_mb=12000), measured={"mid": {"items_s": 0.5}, "pic": {"items_s": 1.0}})
    assert r["can_run"]["mid"] is False and "Too slow" in r["why"]["mid"] and r["can_run"]["pic"] is True
    assert run(smp(free_mb=12000), measured={"mid": {"items_s": None, "ram_mb": "x"}})["can_run"]["mid"] is True


def test_unknown_readings_never_count_against_a_model():
    for s in (None, smp(free_mb=0, cpu=None, gpu=None)):
        r = run(s)
        assert all(r["can_run"].values())
        assert r["budget"]["usable_mb"] is None
        assert "unknown" in r["why"]["mid"]
    assert run(None)["budget"]["live"] is False


def test_the_installed_pc_still_counts():
    small_pc = {"ram_gb": 3.8, "cores": 2, "disk_free_gb": 100.0}
    r = run(smp(free_mb=3000), pc=small_pc)
    assert r["can_run"]["small"] is True and r["can_run"]["mid"] is False and "8 GB" in r["why"]["mid"]


def test_device_follows_free_graphics_memory():
    shared = {"kind": "shared", "free_mb": 7000, "used_mb": 1000, "budget_mb": 8000}       # Intel iGPU
    r = run(smp(free_mb=12000, gpu_mem=shared), pc=PC_GPU)
    assert r["device"]["big4g"] == "gpu" and r["budget"]["gpu_kind"] == "shared"
    tight = dict(shared, free_mb=2000)              # mid: 1381 MB fits in 2000 - 512; big4g: 5376 doesn't
    r = run(smp(free_mb=12000, gpu_mem=tight), pc=PC_GPU)
    assert r["device"]["mid"] == "gpu" and r["device"]["big4g"] == "cpu" and r["can_run"]["big4g"] is True
    assert run(smp(free_mb=12000, gpu=95.0), pc=PC_GPU)["device"]["mid"] == "cpu"          # the GPU is busy
    assert run(smp(free_mb=12000), pc=PC16)["device"]["mid"] == "cpu"                       # no DirectML


def test_the_real_catalog_is_assessed_and_dict_samples_work():
    r = capability.assess({"free_mb": 3000, "commit_pct": 50.0}, PC16, {})
    assert set(r["can_run"]) == set(models.ids())
    assert r["can_run"]["windows-ocr"] is True and r["can_run"]["gte-small"] is True
    assert set(r) == {"can_run", "why", "device", "budget"}
