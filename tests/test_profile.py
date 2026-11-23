"""Per-axis classes (spec 4.1) from synthetic hardware facts, and the per-adapter facts (spec 3) from fake adapters.
Nothing here depends on this PC's real graphics card."""
from nobadfind import hardware, profile


def gpu(vendor, name, dedicated, shared, integrated):
    return {"vendor": vendor, "name": name, "dedicated_mb": dedicated, "shared_mb": shared, "integrated": integrated}


def facts(**kw):
    base = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "ssd": True,
            "gpus": [gpu("intel", "Intel(R) Iris(R) Xe Graphics", 128, 8000, True)],
            "backends": {"onnx": ["cpu"], "llamacpp": ["vulkan", "cpu"]}}
    base.update(kw)
    return base


def test_reference_pc_classes():
    c = profile.classify(facts())
    assert c["gpu"] == {"onnx": "compatibility", "llamacpp": "efficiency"}
    assert (c["cpu"], c["storage"], c["memory"]) == ("performance", "performance", "efficiency")
    assert set(c["why"]) >= {"gpu_onnx", "gpu_llamacpp", "cpu", "storage", "memory"}
    assert all(isinstance(v, str) and v for v in c["why"].values())


def test_strong_gpu_hdd():                                  # A17: the HDD only paces the storage axis
    c = profile.classify(facts(ram_gb=32.0, ssd=False,
                               gpus=[gpu("nvidia", "RTX 4070", 12000, 16000, False)],
                               backends={"onnx": ["cpu", "directml"], "llamacpp": ["vulkan", "cpu"]}))
    assert c["gpu"]["onnx"] == "performance" and c["gpu"]["llamacpp"] == "performance"
    assert c["cpu"] == "performance" and c["memory"] == "performance"
    assert c["storage"] == "efficiency"


def test_unknown_backend_is_not_available():
    strong = [gpu("nvidia", "RTX 4070", 12000, 16000, False)]
    assert profile.classify(facts(gpus=strong, backends={"onnx": ["cpu"], "llamacpp": ["cpu"]}))["gpu"] == \
        {"onnx": "compatibility", "llamacpp": "compatibility"}
    c = profile.classify({})                                # nothing known: the lowest class, never a guess
    assert c["gpu"] == {"onnx": "compatibility", "llamacpp": "compatibility"}
    assert c["cpu"] == "compatibility" and c["memory"] == "compatibility" and c["storage"] == "efficiency"


def test_gpu_thresholds():
    be = {"onnx": ["cpu", "directml"], "llamacpp": ["vulkan"]}
    mid = profile.classify(facts(gpus=[gpu("nvidia", "GTX 1650", 4096, 8000, False)], backends=be))
    assert mid["gpu"]["onnx"] == "balanced"
    big = profile.classify(facts(gpus=[gpu("amd", "x", 8192, 8000, False)], backends=be))
    assert big["gpu"]["onnx"] == "performance"
    just = profile.classify(facts(gpus=[gpu("amd", "x", 8191, 8000, False)], backends=be))
    assert just["gpu"]["onnx"] == "balanced"
    shared_only = profile.classify(facts(gpus=[gpu("intel", "x", 100, 30000, True)], backends=be))
    assert shared_only["gpu"]["onnx"] == "efficiency"       # shared memory is never VRAM


def test_cpu_memory_thresholds():
    assert profile.classify(facts(cores=8))["cpu"] == "performance"
    assert profile.classify(facts(cores=8, avx2=False))["cpu"] != "performance"
    assert [profile.classify(facts(cores=n))["cpu"] for n in (7, 6, 5, 4, 3)] == \
        ["balanced", "balanced", "efficiency", "efficiency", "compatibility"]
    assert [profile.classify(facts(ram_gb=g))["memory"] for g in (32, 31.9, 16, 15.9, 8, 7.9)] == \
        ["performance", "balanced", "balanced", "efficiency", "efficiency", "compatibility"]
    assert profile.classify(facts(ssd=None))["storage"] == "efficiency"


def test_hybrid_laptop_lists_every_adapter(monkeypatch):
    fake = [{"name": "Intel(R) UHD Graphics", "flags": 0, "dedicated_mb": 128, "shared_mb": 8000, "luid": "a",
             "vendor_id": 0x8086},
            {"name": "NVIDIA GeForce RTX 3060 Laptop GPU", "flags": 0, "dedicated_mb": 6144, "shared_mb": 8000,
             "luid": "b", "vendor_id": 0x10DE},
            {"name": "Microsoft Basic Render Driver", "flags": 2, "dedicated_mb": 0, "shared_mb": 0, "luid": "c",
             "vendor_id": 0x1414}]
    monkeypatch.setattr(hardware, "adapters", lambda full=False: fake)
    gpus = hardware.gpu_list()
    assert [(g["vendor"], g["integrated"]) for g in gpus] == [("intel", True), ("nvidia", False)]
    assert gpus[1]["dedicated_mb"] == 6144 and gpus[1]["shared_mb"] == 8000
    assert set(gpus[0]) == {"vendor", "name", "dedicated_mb", "shared_mb", "integrated"}
    c = profile.classify(facts(gpus=gpus, backends={"onnx": ["cpu", "directml"], "llamacpp": ["vulkan"]}))
    assert c["gpu"]["onnx"] == "balanced"                   # the best adapter counts, not the first


def test_backends_fail_safe(monkeypatch):
    monkeypatch.setattr(hardware, "_dml", lambda: False)
    monkeypatch.setattr(hardware, "_llama_ready", lambda rid: rid == "llama-cpu")
    assert hardware.backends() == {"onnx": ["cpu"], "llamacpp": ["cpu"]}
    monkeypatch.setattr(hardware, "_dml", lambda: True)
    monkeypatch.setattr(hardware, "_llama_ready", lambda rid: True)
    assert hardware.backends() == {"onnx": ["cpu", "directml"], "llamacpp": ["vulkan", "cpu"]}

    def boom(rid):
        raise OSError
    monkeypatch.setattr(hardware, "_llama_ready", boom)
    assert hardware.backends()["llamacpp"] == []
