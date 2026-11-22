"""Which devices this PC can really run a candidate on (dev only). A device that isn't there is reported as not
available with the reason, never measured as something else.

Backends: "ort" (ONNX Runtime in this Python: CPU, DirectML, CUDA by provider) and "llama" (a llama.cpp release
build in --tools-dir: cpu, vulkan, cuda).
"""
import os

GPU_DEVICES = ("directml", "cuda", "vulkan")
_ORT_PROVIDER = {"cpu": "CPUExecutionProvider", "directml": "DmlExecutionProvider", "cuda": "CUDAExecutionProvider"}
_VENDORS = (("nvidia", ("nvidia", "geforce", "quadro", "rtx ", "gtx ")), ("amd", ("amd", "radeon")),
            ("intel", ("intel",)))


def vendor(gpu_name):
    """"nvidia" / "amd" / "intel" from the adapter name (hardware.scan has no vendor id), else None."""
    n = (gpu_name or "").lower()
    for v, keys in _VENDORS:
        if any(k in n for k in keys):
            return v
    return None


def _dev(device, backend, why=""):
    return {"device": device, "backend": backend, "available": not why, "why": why}


def devices(hw, ort_providers, llama_builds):
    """[{device, backend, available, why}] for every device x backend pair the bench knows."""
    v = vendor(hw.get("gpu"))
    out = []
    for device in ("cpu", "directml", "cuda"):
        why = ""
        if device != "cpu" and v is None:
            why = "no graphics card found"
        elif device == "cuda" and v != "nvidia":
            why = "CUDA needs an NVIDIA graphics card"
        elif _ORT_PROVIDER[device] not in ort_providers:
            why = f"this ONNX Runtime has no {_ORT_PROVIDER[device]} (install the matching onnxruntime build)"
        out.append(_dev(device, "ort", why))
    for device in ("cpu", "vulkan", "cuda"):
        why = ""
        if device != "cpu" and v is None:
            why = "no graphics card found"
        elif device == "cuda" and v != "nvidia":
            why = "CUDA needs an NVIDIA graphics card"
        elif device not in llama_builds:
            why = f"no llama.cpp {device.upper() if device == 'cpu' else device.capitalize()} build in --tools-dir"
        out.append(_dev(device, "llama", why))
    return out


def llama_builds(tools_dir):
    """{"cpu"|"vulkan"|"cuda": folder} for the llama.cpp builds unpacked in tools_dir (folder names llama-<device>)."""
    found = {}
    for device in ("cpu", "vulkan", "cuda"):
        d = os.path.join(tools_dir or "", f"llama-{device}")
        if tools_dir and os.path.isfile(os.path.join(d, "llama-mtmd-cli.exe")):
            found[device] = d
    return found


def probe(tools_dir=None):
    """{"hardware": hardware.scan(), "devices": devices(...)} for this PC and this Python's ONNX Runtime."""
    from nobadfind import hardware
    try:
        import onnxruntime
        providers = list(onnxruntime.get_available_providers())
    except Exception:
        providers = []
    hw = hardware.scan()
    return {"hardware": hw, "devices": devices(hw, providers, llama_builds(tools_dir))}
