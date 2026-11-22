"""tools/vision_bench/probe.py: which devices a run may use, and an honest reason for each one it can't."""
from tools.vision_bench.probe import devices, vendor

INTEL = {"gpu": "Intel(R) Iris(R) Xe Graphics", "vram_gb": 0.1}
NVIDIA = {"gpu": "NVIDIA GeForce RTX 3060", "vram_gb": 12.0}
NO_GPU = {"gpu": None, "vram_gb": None}
CPU_ONLY = ["CPUExecutionProvider"]


def _by(devs):
    return {(d["device"], d["backend"]): d for d in devs}


def test_vendor_from_name():
    assert vendor("NVIDIA GeForce RTX 3060") == "nvidia"
    assert vendor("AMD Radeon RX 6600") == "amd"
    assert vendor("Intel(R) Iris(R) Xe Graphics") == "intel"
    assert vendor(None) is None
    assert vendor("Microsoft Basic Render Driver") is None


def test_cpu_always_available():
    d = _by(devices(NO_GPU, CPU_ONLY, {"cpu": "llama-cpu"}))
    assert d[("cpu", "ort")]["available"] and d[("cpu", "llama")]["available"]


def test_cuda_needs_nvidia_and_provider():
    d = _by(devices(NVIDIA, CPU_ONLY, {"cuda": "llama-cuda"}))
    assert not d[("cuda", "ort")]["available"]
    assert "CUDAExecutionProvider" in d[("cuda", "ort")]["why"]
    assert d[("cuda", "llama")]["available"]
    d = _by(devices(INTEL, ["CUDAExecutionProvider", "CPUExecutionProvider"], {"cuda": "llama-cuda"}))
    assert not d[("cuda", "ort")]["available"] and not d[("cuda", "llama")]["available"]
    assert "NVIDIA" in d[("cuda", "llama")]["why"]


def test_directml_needs_provider():
    d = _by(devices(INTEL, CPU_ONLY, {}))
    assert not d[("directml", "ort")]["available"]
    assert "DmlExecutionProvider" in d[("directml", "ort")]["why"]
    d = _by(devices(INTEL, ["DmlExecutionProvider", "CPUExecutionProvider"], {}))
    assert d[("directml", "ort")]["available"]


def test_vulkan_needs_llama_vulkan_build():
    d = _by(devices(INTEL, CPU_ONLY, {"cpu": "llama-cpu"}))
    assert not d[("vulkan", "llama")]["available"]
    assert "Vulkan build" in d[("vulkan", "llama")]["why"]
    d = _by(devices(INTEL, CPU_ONLY, {"vulkan": "llama-vulkan"}))
    assert d[("vulkan", "llama")]["available"]


def test_no_gpu_means_no_gpu_devices_available():
    allp = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    d = devices(NO_GPU, allp, {"cuda": "a", "vulkan": "b", "cpu": "c"})
    assert [x["device"] for x in d if x["available"]] == ["cpu", "cpu"]
    assert all(x["why"] for x in d if not x["available"])


def test_cpu_llama_needs_cpu_build():
    d = _by(devices(NO_GPU, CPU_ONLY, {}))
    assert not d[("cpu", "llama")]["available"]
