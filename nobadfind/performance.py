"""Settings > Performance (1.2.0, spec 2026-11-22 §8b rule 5): for every override, its value, what "auto" would
pick on this PC right now and why, the values it may take here, and a note when the value isn't used now. Pure:
from the hardware facts (hardware.scan, cached), the indexer's plan and the talk runtime; nothing is measured."""
import os

from . import profile
from .const import DEFAULTS, FEATURE_BACKENDS, VARIANTS
from .settings import goal as goal_of


def state(st, pc, plan, talk_rid, gpu_now=None):
    """Settings > Performance: for every override, its value, what auto would pick on this PC right now and
    why, the values it may take here, and a note when the value isn't used now (spec 8b rule 5). Read from
    the cached hardware scan and the plan: nothing is measured for it. gpu_now: {"text", "talk"}: why that work
    runs on the processor right now though the graphics card was chosen (the graphics reserve and fit check,
    indexer.text_gpu_choice / Api._talk_gpu_fits); shown as the row's note."""
    now = gpu_now or {}
    goal = goal_of(st)
    pc = pc or {}
    backs = pc.get("backends") or {}
    onnx = [b for b in backs.get("onnx") or [] if b in FEATURE_BACKENDS["text"]] or ["cpu"]
    llama = [b for b in backs.get("llamacpp") or [] if b in FEATURE_BACKENDS["talk"]] or ["cpu"]
    name = {"directml": "DirectML", "vulkan": "Vulkan", "cpu": "the processor"}
    rows = {}

    def row(key, auto, why, options=None, note=""):
        rows[key] = {"value": st.get(key), "auto": auto, "why": why, "options": list(options or []),
                     "note": note}

    dml = "directml" in onnx
    if goal == "quiet":
        bg, why = "off", "The goal is Quiet, which keeps background work off the graphics card."
    elif not dml:
        bg, why = "off", "No graphics backend for background work is installed on this PC."
    else:
        bg, why = "on", ("Background work may use the graphics card at Full, not with battery saver on or a "
                         "creative app in front.")
    row("gpu_background", bg, why, ["auto", "on", "off"])

    def backend(key, avail, auto, why, instead, note=""):
        v = st.get(key)
        if v not in ("auto", None) and v not in avail:
            note = f"{name.get(v, v)} isn't available on this PC now, so {instead}."
        row(key, auto, why, ["auto"] + list(avail), note)

    backend("backend_photos", ["cpu"], "cpu", "Photos are looked at on the processor in this version.",
            "photos run on the processor")
    # the user's gpu_background beats the goal; "off" also beats a forced graphics backend (indexer.text_gpu)
    user_bg = st.get("gpu_background")
    off = user_bg == "off"
    text_auto = "directml" if dml and (user_bg if user_bg in ("on", "off") else bg) == "on" else "cpu"
    if text_auto != "cpu":
        text_why = "Meaning for documents uses DirectML at Full and the processor otherwise."
    elif off:
        text_why = "Meaning for documents runs on the processor: the graphics card for background work is Off."
    else:
        text_why = "Meaning for documents runs on the processor: " + why[0].lower() + why[1:]
    backend("backend_text", onnx, text_auto, text_why, "meaning runs on the processor",
            "The graphics card for background work is Off, and Off wins: meaning runs on the processor."
            if off and st.get("backend_text") not in ("auto", "cpu", None) else now.get("text") or "")
    talk = "vulkan" if talk_rid == "llama-vulkan" and "vulkan" in llama else "cpu"
    backend("backend_talk", llama, talk, "Talk about a photo uses the Vulkan runtime installed here."
            if talk == "vulkan" else "Talk about a photo uses the processor runtime.",
            "talk about a photo uses the processor", now.get("talk") or "")
    for mid, variants in VARIANTS.items():
        pick = variants[-1] if goal == "fast" else variants[0]
        row(f"variant_{mid}", pick,
            ("Fast takes the faster build." if goal == "fast" else "Quiet and Balanced take the lighter build.")
            + " Both made the same vectors on 50 test photos.", ["auto"] + list(variants),
            "Not used yet: this version downloads only the lighter build.")
    p = plan or {}
    cpu = p.get("cpu") or os.cpu_count() or 1
    # what auto picks, whatever number is set now (indexer.plan's own formula; the plan holds the chosen number)
    idle, busy = (cpu, cpu) if goal == "fast" else (max(1, min(16, cpu - 1)), max(1, min(8, cpu - 2)))
    if p.get("ssd") is False:
        idle, busy = min(idle, 2), min(busy, 2)
        why = f"{idle} at most: the indexed drive is a spinning disk, where more readers only seek."
    elif goal == "fast":
        why = f"Fast uses all {cpu} threads."
    else:
        why = f"{idle} while you're away and {busy} while you use the PC, from {cpu} threads."
    auto_w = idle
    row("workers", auto_w, why, [],
        "Fast uses every thread, so this number isn't used." if goal == "fast" else "")
    classes = profile.classify(pc)
    cw = classes["why"]
    g = classes["gpu"]
    used_by = ("Used by the model suggestions (Settings > Models and the first-run setup); it doesn't change how "
              "hard NOBAD Find works.")
    row("profile_override_gpu", g.get("onnx"),
        f"Background work: {cw.get('gpu_onnx')}. Talk about a photo: {cw.get('gpu_llamacpp')}.",
        ["auto"] + list(profile._ORDER[::-1]), used_by)
    for axis in ("cpu", "storage", "memory"):
        row(f"profile_override_{axis}", classes[axis], cw[axis][:1].upper() + cw[axis][1:] + ".",
            ["auto"] + list(profile._ORDER[::-1]), used_by)
    row("gpu_reserve_min_mb", DEFAULTS["gpu_reserve_min_mb"],
        "NOBAD Find leaves the larger of this and 15% of the free graphics memory to Windows and other apps. "
        "A higher number only leaves more.", [],
        "Used for work on the graphics card (meaning for documents, talk about a photo, the check under Index > "
        "Running at once now) and by the model suggestions.")
    return {"goal": goal, "rows": rows}
