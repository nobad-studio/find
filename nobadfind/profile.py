"""One class per axis from the hardware facts (spec 4.1): pure, no I/O. A class is "performance", "balanced",
"efficiency" or "compatibility". A real PC is never put in one tier: each kind of work follows its own axes.
Missing or unknown facts give the lowest class (storage: efficiency), never a guess upward."""

PERFORMANCE, BALANCED, EFFICIENCY, COMPATIBILITY = "performance", "balanced", "efficiency", "compatibility"
_ORDER = (COMPATIBILITY, EFFICIENCY, BALANCED, PERFORMANCE)
FAMILIES = ("onnx", "llamacpp")


def _gpu_one(g, gpu_backends):
    """(class, why) of one adapter given the family's non-CPU backends."""
    name = g.get("name") or "graphics card"
    if not gpu_backends:
        return COMPATIBILITY, f"{name}: no graphics backend available"
    via = "/".join(gpu_backends)
    if g.get("integrated"):
        return EFFICIENCY, f"{name}: built-in graphics on shared memory, via {via}"
    mb = int(g.get("dedicated_mb") or 0)
    if mb >= 8192:
        return PERFORMANCE, f"{name}: {mb // 1024} GB dedicated, via {via}"
    if mb >= 4096:
        return BALANCED, f"{name}: {mb // 1024} GB dedicated, via {via}"
    # gap in spec 4.1: a discrete card under 4 GB with a GPU backend matches no rule; Efficiency
    return EFFICIENCY, f"{name}: only {mb} MB dedicated, via {via}"      # small discrete card: spec silent, see report


def _gpu(facts, family):
    # gap in spec 4.1: for llama.cpp, Vulkan counts as a GPU backend (the spec names only CUDA / DirectML)
    backs = [b for b in ((facts.get("backends") or {}).get(family) or []) if b != "cpu"]
    best = (COMPATIBILITY, f"{family}: no graphics card with a usable backend")
    for g in facts.get("gpus") or []:
        c = _gpu_one(g, backs)
        if _ORDER.index(c[0]) > _ORDER.index(best[0]):
            best = c
    return best


def _cpu(facts):
    cores = int(facts.get("cores") or 0)
    avx2 = bool(facts.get("avx2"))
    if cores >= 8 and avx2:
        c = PERFORMANCE
    elif cores >= 6:                    # gap in spec 4.1: 8+ cores without AVX2 land here (Balanced)
        c = BALANCED
    elif cores >= 4:
        c = EFFICIENCY
    else:
        c = COMPATIBILITY
    return c, f"{cores} physical cores, AVX2 {'yes' if avx2 else 'no or unknown'}"


def _memory(facts):
    gb = float(facts.get("ram_gb") or 0)
    c = PERFORMANCE if gb >= 32 else BALANCED if gb >= 16 else EFFICIENCY if gb >= 8 else COMPATIBILITY
    return c, f"{gb:g} GB installed memory"


def _storage(facts):
    ssd = facts.get("ssd")              # gap in spec 4.1: unknown (None) is treated as a hard disk (Efficiency)
    return (PERFORMANCE, "solid-state drive") if ssd is True else \
        (EFFICIENCY, "hard disk" if ssd is False else "drive type unknown, treated as a hard disk")


def classify(facts):
    """{"gpu": {"onnx": cls, "llamacpp": cls}, "cpu", "storage", "memory": cls, "why": {axis: text}} from
    hardware.scan() facts. why keys: gpu_onnx, gpu_llamacpp, cpu, storage, memory."""
    facts = facts or {}
    gpu, why = {}, {}
    for fam in FAMILIES:
        gpu[fam], why[f"gpu_{fam}"] = _gpu(facts, fam)
    out = {"gpu": gpu, "why": why}
    for axis, fn in (("cpu", _cpu), ("storage", _storage), ("memory", _memory)):
        out[axis], why[axis] = fn(facts)
    return out


def effective(classes, settings):
    """classify()'s classes with the user's profile_override_<axis> applied (spec 8b): an override redirects
    which class a kind of work plans for; it is not a resource, so the live budget and the safety limits still
    decide what runs. The gpu override applies to both families. why says which axes the user chose."""
    out = {"gpu": dict(classes.get("gpu") or {}), "why": dict(classes.get("why") or {})}
    for axis in ("cpu", "storage", "memory"):
        out[axis] = classes.get(axis)
    for axis in ("gpu", "cpu", "storage", "memory"):
        v = settings.get(f"profile_override_{axis}") if settings is not None else None
        if v not in _ORDER:
            continue
        if axis == "gpu":
            out["gpu"] = {fam: v for fam in FAMILIES}
            for fam in FAMILIES:
                out["why"][f"gpu_{fam}"] = f"you chose {v} (auto: {(classes.get('gpu') or {}).get(fam)})"
        else:
            out[axis] = v
            out["why"][axis] = f"you chose {v} (auto: {classes.get(axis)})"
    return out
