"""Can this PC run each model RIGHT NOW? A live capability assessment (maintainer request 2026-11-21): what is free
now, not what is installed. A 16 GB PC with 3 GB free is not allowed a model that needs 4 GB.

assess(sample, hardware, measured) is pure: `sample` is the governor's last Sample (free RAM, commit, graphics
memory, CPU/GPU load, battery, battery saver; None before its first tick), `hardware` is hardware.scan() (installed
facts, still used for cores and disk), `measured` is {model_id: {"ram_mb", "items_s"}} from this PC (an in-app
benchmark, later; {} is fine: the catalog's measured numbers are used). Unknown readings never count against a
model: then only the installed facts decide, as before.

A model is runnable now when, in this order:
  1. the installed PC can run it at all (models.capable: cores, memory size, disk);
  2. its RAM need (measured here, else the catalog's) plus a margin fits in free RAM, after the memory the governor
     keeps for Windows (governor LIMITS LOW_FREE_MB, where it pauses);
  3. Windows isn't close to its commit limit and can still promise that much;
  4. battery saver is off (else light models only), and on battery the best tier waits for the charger;
  5. the processor isn't busy with other apps (heavier than light models wait);
  6. its speed measured on this PC isn't too slow to be useful.
device: "gpu" when DirectML is there, the graphics card isn't busy, and its free memory now less the reserve
(governor.gpu_fit: max(512 MB or the user's minimum, 15% of free); an integrated GPU's shared memory counts) holds
the model; else "cpu". Unknown free graphics memory never counts as fits: "cpu".
"""
from . import models
from .governor import LIMITS, gpu_fit

MARGIN_MB = 256          # every model gets this much on top of its need ...
MARGIN_SHARE = 0.25      # ... plus a quarter of it (tokenizers, batches, the allocator)
MIN_SPEED = {"text": 2.0, "photo": 0.3}      # items a second measured here below which a model isn't useful


def _get(sample, key):
    if sample is None:
        return None
    return sample.get(key) if isinstance(sample, dict) else getattr(sample, key, None)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def margin_mb(need):
    return int(MARGIN_MB + MARGIN_SHARE * need)


def need_mb(m, measured=None):
    got = _num(((measured or {}).get(m["id"]) or {}).get("ram_mb"))
    return int(got) if got and got > 0 else int(m.get("ram_mb") or 0)


def _size(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{int(mb)} MB"


def budget(sample, hardware=None):
    """The live numbers assess uses, for the UI ("Your PC, now"). None = unknown."""
    free = _num(_get(sample, "free_mb")) or None              # 0 means Windows couldn't say
    reserve = LIMITS["LOW_FREE_MB"]
    cpu, find = _num(_get(sample, "cpu")), _num(_get(sample, "find_cpu")) or 0.0
    gm = _get(sample, "gpu_mem") or {}
    ram_gb = _num((hardware or {}).get("ram_gb"))
    return {"live": sample is not None, "installed_mb": int(ram_gb * 1024) if ram_gb else None,
            "free_mb": int(free) if free else None, "reserve_mb": reserve,
            "usable_mb": max(0, int(free) - reserve) if free else None,
            "commit_pct": _num(_get(sample, "commit_pct")), "commit_free_mb": _num(_get(sample, "commit_free_mb")),
            "gpu_kind": gm.get("kind") or None, "gpu_free_mb": _num(gm.get("free_mb")),
            "gpu_budget_mb": _num(gm.get("budget_mb")),
            "cpu": None if cpu is None else round(max(0.0, cpu - find), 1), "gpu": _num(_get(sample, "gpu")),
            "battery": bool(_get(sample, "battery")), "battery_saver": _get(sample, "battery_saver") is True}


def _one(m, pc, b, measured, settings=None):
    """(can run now, why, device)."""
    if m.get("builtin"):
        return True, "Built into Windows", "cpu"
    ok, why = models.capable(m, pc)
    if not ok:
        return False, why, "cpu"
    need = need_mb(m, measured)
    total = need + margin_mb(need)
    if b["usable_mb"] is not None and total > b["usable_mb"]:
        return False, (f"Not now: it needs about {_size(need)} plus {_size(margin_mb(need))} to spare, and "
                       f"{_size(b['free_mb'])} of memory is free (NOBAD Find leaves {_size(b['reserve_mb'])} "
                       "to Windows)"), "cpu"
    if b["commit_pct"] is not None and b["commit_pct"] >= LIMITS["HIGH_COMMIT"]:
        return False, (f"Not now: Windows is close to the memory it can promise programs "
                       f"(commit {round(b['commit_pct'])}%)"), "cpu"
    if b["commit_free_mb"] is not None and total > b["commit_free_mb"]:
        return False, (f"Not now: Windows can promise only {_size(b['commit_free_mb'])} more memory, and it needs "
                       f"about {_size(total)}"), "cpu"
    if b["battery_saver"] and m.get("tier") != "light":
        return False, "Not now: battery saver is on, so only light models run", "cpu"
    if b["battery"] and m.get("tier") == "best":
        return False, "Not now: on battery, the best models wait for the charger", "cpu"
    if b["cpu"] is not None and b["cpu"] >= LIMITS["HOT_CPU"] and m.get("tier") != "light":
        return False, f"Not now: other apps are using the processor ({round(b['cpu'])}%)", "cpu"
    speed = _num(((measured or {}).get(m["id"]) or {}).get("items_s"))
    low = MIN_SPEED.get(m.get("feature"))
    if speed is not None and low is not None and speed < low:
        unit = "photos" if m.get("feature") == "photo" else "pieces of text"
        return False, f"Too slow on this PC: measured {speed:g} {unit} a second", "cpu"
    gpu = bool(pc.get("directml")) and not b["battery_saver"] and (b["gpu"] is None or b["gpu"] < LIMITS["HOT_GPU"]) \
        and gpu_fit({"free_mb": b["gpu_free_mb"]}, total, settings)[0]
    if b["usable_mb"] is None:
        return True, "Fits this PC (free memory unknown right now)", "gpu" if gpu else "cpu"
    return True, f"Fits now: needs about {_size(need)}, {_size(b['free_mb'])} free", "gpu" if gpu else "cpu"


def assess(sample, hardware, measured=None, catalog=None, settings=None):
    """{"can_run": {model_id: bool}, "why": {model_id: str}, "device": {model_id: "gpu" | "cpu"},
    "budget": budget(...)} for every model in the catalog. settings: for the user's graphics reserve minimum."""
    pc = hardware or {}
    b = budget(sample, pc)
    out = {"can_run": {}, "why": {}, "device": {}, "budget": b}
    for m in (models.CATALOG if catalog is None else catalog):
        ok, why, device = _one(m, pc, b, measured or {}, settings)
        out["can_run"][m["id"]], out["why"][m["id"]], out["device"][m["id"]] = ok, why, device
    return out
