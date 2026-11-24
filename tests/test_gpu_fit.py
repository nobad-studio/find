"""The graphics-memory reserve and fit check guard the work that really uses the graphics card (final review,
Important 1): meaning on DirectML, talk on Vulkan with a graphics card of its own, and capability's device. The
reserve is R = max(512 MB or the user's higher minimum, 15% of the free graphics memory); a model goes to the
graphics card only when free - R >= its need. Unknown free graphics memory never counts as "fits", also for a
forced backend (safety limits beat user overrides): the processor, with the reason."""
import concurrent.futures as cf

import numpy as np

from nobadfind import capability, indexer, performance
from nobadfind import governor as g
from nobadfind.activity import Activity
from nobadfind.governor import Sample


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def smp(gpu_mem=None, **kw):
    base = dict(t=0.0, cpu=20.0, gpu=10.0, mem_load=40, free_mb=8000, find_cpu=0.0, foreground="", game=False,
                presentation=False, hung=False, battery=False, call=False, idle_s=0.0, gpu_mem=gpu_mem)
    base.update(kw)
    return Sample(**base)


def dedicated(free):
    return {"kind": "dedicated", "free_mb": free, "used_mb": 8192 - free, "budget_mb": 8192}


FULL = g.Decision(g.FULL, "")


# ---------- the one fit check ----------
def test_gpu_fit_leaves_the_reserve_and_says_why():
    assert g.gpu_fit(dedicated(4000), 500) == (True, "")        # R = max(512, 600) = 600: 3400 usable
    ok, why = g.gpu_fit(dedicated(1000), 600)                   # R = 512: 488 usable < 600
    assert ok is False and "1000 MB" in why and "512 MB" in why and "600 MB" in why
    ok, why = g.gpu_fit(dedicated(4000), 500, S(gpu_reserve_min_mb=3600))     # the user leaves more
    assert ok is False and "3600 MB" in why
    for unknown in (None, {}, {"kind": "dedicated"}):
        ok, why = g.gpu_fit(unknown, 100)
        assert ok is False and "isn't known" in why


# ---------- meaning on DirectML ----------
def test_forced_directml_at_full_with_little_free_graphics_memory_uses_the_processor():
    st = S(backend_text="directml", gpu_background="on")
    gpu, why = indexer.text_gpu_choice(g.FULL, FULL, st, smp(dedicated(700)), 400)
    assert gpu is False and "processor" in why and "700 MB" in why
    assert indexer.text_gpu(g.FULL, FULL, st, smp(dedicated(700)), 400) is False


def test_enough_graphics_memory_keeps_directml():
    st = S(backend_text="directml", gpu_background="on")
    assert indexer.text_gpu_choice(g.FULL, FULL, st, smp(dedicated(4000)), 400) == (True, "")
    assert indexer.text_gpu_choice(g.FULL, FULL, S(backend_text="auto"), smp(dedicated(4000)), 400) == (True, "")


def test_unknown_graphics_memory_never_fits_a_forced_directml():
    st = S(backend_text="directml", gpu_background="on")
    for sample in (None, smp(None)):
        gpu, why = indexer.text_gpu_choice(g.FULL, FULL, st, sample, 400)
        assert gpu is False and "isn't known" in why


def test_the_user_choices_still_say_processor_without_a_reason():
    # the processor because the user or the level said so: nothing to explain on the graphics side
    assert indexer.text_gpu_choice(g.GENTLE, FULL, S(backend_text="directml"), smp(dedicated(4000)), 400) == \
        (False, "")
    assert indexer.text_gpu_choice(g.FULL, FULL, S(backend_text="cpu"), smp(dedicated(4000)), 400) == (False, "")


def test_text_need_comes_from_the_catalog():
    assert indexer.text_gpu_need("multilingual-e5-small") == 385       # no DirectML measurement: its RAM need
    assert indexer.text_gpu_need(None) == 0 and indexer.text_gpu_need("nope") == 0


class _Pool:
    made = []

    def __init__(self, *a, **k):
        self.gpu = k["initargs"][2]
        self._processes = {}
        _Pool.made.append(self)

    def submit(self, fn, *args):
        f = cf.Future()
        f.set_result(np.zeros((len(args[0]), 4), np.float32).tobytes())
        return f

    def shutdown(self, **k):
        pass


class _Gov:
    def __init__(self, sample):
        self.decision = g.Decision(g.FULL, "why")
        self.sample = sample


def test_the_meaning_worker_starts_on_the_processor_when_the_card_is_short(monkeypatch):
    _Pool.made = []
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)
    monkeypatch.setattr(indexer.models, "model_dir", lambda mid: "dir")
    monkeypatch.setattr(indexer, "log", lambda msg, lvl="info": None)
    gov = _Gov(smp(dedicated(700)))
    ix = indexer.Indexer(None, S(backend_text="directml", gpu_background="on", text_model="multilingual-e5-small"),
                         governor=gov, activity=Activity())
    ix._vectors_in_worker = True
    ix.status["plan"] = {"model_threads": 4, "text_workers": 4, "text_workers_idle": 4}
    assert ix._encode(["a"], "multilingual-e5-small") is not None
    assert _Pool.made[-1].gpu is False and "700 MB" in ix.text_gpu_why
    # Settings > Performance shows it where the meaning backend is explained
    pc = {"backends": {"onnx": ["cpu", "directml"], "llamacpp": ["cpu"]}}
    rows = performance.state(ix.settings, pc, {"cpu": 8}, "llama-cpu", gpu_now={"text": ix.text_gpu_why})["rows"]
    assert "700 MB" in rows["backend_text"]["note"]
    # the card has room again
    gov.sample = smp(dedicated(6000))
    ix._clock = lambda: 10_000.0
    ix._encode(["a"], "multilingual-e5-small")
    ix._clock = lambda: 20_000.0
    ix._encode(["a"], "multilingual-e5-small")
    assert _Pool.made[-1].gpu is True and ix.text_gpu_why == ""


def _two_gb(free):
    return {"kind": "dedicated", "free_mb": free, "used_mb": 2048 - free, "budget_mb": 2048}


def test_the_meaning_worker_on_the_card_counts_its_own_memory_as_allowed(monkeypatch):
    """Re-review I1: the governor's free graphics memory is all apps together, so once the meaning worker runs on
    the card its own memory is in "used". Its need is credited back, so staying needs what starting needed and
    the worker doesn't flap between the card and the processor; a real further drop still moves it."""
    _Pool.made = []
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", _Pool)
    monkeypatch.setattr(indexer.models, "model_dir", lambda mid: "dir")
    monkeypatch.setattr(indexer, "log", lambda msg, lvl="info": None)
    mid = "multilingual-e5-small"
    need = indexer.text_gpu_need(mid)                           # 385
    gov = _Gov(smp(_two_gb(1100)))                              # 1100 - 512 = 588 >= 385: the card
    ix = indexer.Indexer(None, S(backend_text="directml", gpu_background="on", text_model=mid),
                         governor=gov, activity=Activity())
    ix._vectors_in_worker = True
    ix.status["plan"] = {"model_threads": 4, "text_workers": 4, "text_workers_idle": 4}
    ix._encode(["a"], mid)
    assert len(_Pool.made) == 1 and _Pool.made[-1].gpu is True
    gov.sample = smp(_two_gb(1100 - need))                      # the worker's own model is now in "used"
    for t in (100.0, 1000.0, 5000.0):
        ix._clock = lambda t=t: t
        assert ix._encode(["a"], mid) is not None              # no restart reason: the same worker
    assert len(_Pool.made) == 1 and ix.text_gpu_why == ""
    gov.sample = smp(_two_gb(1100 - need - 300))                # another app took 300 MB: below the reserve
    ix._encode(["a"], mid)
    assert len(_Pool.made) == 2 and _Pool.made[-1].gpu is False and "processor" in ix.text_gpu_why
    # unknown is still the processor, whatever the worker holds
    assert indexer.text_gpu_choice(g.FULL, FULL, ix.settings, smp(None), need, resident_mb=need)[0] is False


def test_the_directml_need_is_said_to_be_unmeasured():
    """Re-review m3: no DirectML row is measured, so the need is the processor's; the reason says so."""
    st = S(backend_text="directml", gpu_background="on")
    assert indexer.text_gpu_need_measured("multilingual-e5-small") is False
    gpu, why = indexer.text_gpu_choice(g.FULL, FULL, st, smp(dedicated(700)), 385, need_measured=False)
    assert gpu is False and "this needs about" not in why
    assert "the model needs about 385 MB on the processor; its graphics need isn't measured yet" in why
    ok, why = g.gpu_fit(dedicated(1000), 600)                   # a measured need (talk's vram_mb) keeps its words
    assert "this needs about 600 MB" in why


# ---------- capability's device ----------
PC_GPU = {"ram_gb": 15.7, "cores": 8, "threads": 16, "directml": True, "vram_gb": 8.0, "disk_free_gb": 100.0}
MID = {"id": "mid", "feature": "text", "tier": "balanced", "ram_mb": 900, "builtin": False, "dim": 384,
       "files": {"model.onnx": ("x", 10 * 1048576, "0" * 64)}}       # need 900 + margin 481 = 1381 MB


def test_capability_device_leaves_the_graphics_reserve():
    def device(gm, settings=None):
        return capability.assess(smp(gm, free_mb=12000), PC_GPU, {}, catalog=[MID], settings=settings)["device"]["mid"]
    assert device(dedicated(1500)) == "cpu"          # 1500 >= 1381, but 1500 - 512 = 988 isn't
    assert device(dedicated(2000)) == "gpu"          # 2000 - 512 = 1488
    assert device(dedicated(2000), S(gpu_reserve_min_mb=1024)) == "cpu"
    assert device(None) == "cpu"                     # unknown never counts as fits


# ---------- final review minors ----------
def test_performance_notes_say_what_the_settings_change_now():
    pc = {"backends": {"onnx": ["cpu", "directml"], "llamacpp": ["cpu"]}}
    rows = performance.state(S(), pc, {"cpu": 8}, "llama-cpu")["rows"]
    for axis in ("gpu", "cpu", "storage", "memory"):
        note = rows[f"profile_override_{axis}"]["note"]
        assert "later update" not in note and "Not used yet" not in note and "model suggestions" in note
    note = rows["gpu_reserve_min_mb"]["note"]
    assert "only" not in note and "model suggestions" in note and "graphics card" in note


def test_the_vulkan_runtime_has_a_neutral_name():
    from nobadfind import models
    assert models.get("llama-vulkan")["name"] == "llama.cpp runtime (Vulkan)"


def test_no_way_left_to_drop_the_working_photo_vectors():
    from nobadfind.store import Store
    assert not hasattr(Store, "drop_photo_vectors")
