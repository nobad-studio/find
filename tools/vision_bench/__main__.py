"""python -m tools.vision_bench --set <folder with set.json> --models-dir <dir> --tools-dir <dir> --out <dir>
                             [--download] [--only ID,...] [--devices cpu,directml,vulkan,cuda] [--tasks ocr,...]

Dev only (see README.md). Nothing is downloaded without --download; then only the pinned files in models.json for
the chosen candidates and devices, each checked by size and SHA-256.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

from . import probe, run

BACKEND_DEVICES = {"ort": ("cpu", "directml", "cuda"), "llama": ("cpu", "vulkan", "cuda")}


def pairs(candidates, devices, models):
    out = []
    for c in candidates:
        backend = models[c]["backend"]
        out += [(c, d, backend) for d in BACKEND_DEVICES[backend] if d in devices]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tools.vision_bench")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--set")
    ap.add_argument("--models-dir")
    ap.add_argument("--tools-dir")
    ap.add_argument("--out")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--only", default=",".join(run.ADAPTERS))
    ap.add_argument("--devices", default="cpu,directml,vulkan,cuda")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--variant", default="", help="a speed-up from adapters.VARIANTS (llama.cpp candidates)")
    a = ap.parse_args(argv)
    if a.child:
        return run.child_main(a.child)
    for need in ("set", "models_dir", "tools_dir", "out"):
        if not getattr(a, need):
            ap.error(f"--{need.replace('_', '-')} is required")
    models = run.models_json()["models"]
    cands = [c for c in a.only.split(",") if c]
    unknown = [c for c in cands if c not in run.ADAPTERS]
    if unknown:
        ap.error(f"unknown candidate(s): {', '.join(unknown)}")
    devices = [d for d in a.devices.split(",") if d]
    os.makedirs(a.out, exist_ok=True)
    info = probe.probe(a.tools_dir)
    if a.download:
        run.download(cands, devices, a.models_dir, a.tools_dir)
        info = probe.probe(a.tools_dir)
    from .evalset import load_set
    items = load_set(os.path.join(a.set, "set.json"))
    tasks = [t for t in a.tasks.split(",") if t]
    cfg_dir = tempfile.mkdtemp(prefix="vbench-cfg-")

    def child_cmd(cand, device):
        p = os.path.join(cfg_dir, f"{cand}-{device}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"set": os.path.join(a.set, "set.json"), "candidate": cand, "device": device,
                       "models_dir": a.models_dir, "tools_dir": a.tools_dir, "tasks": tasks,
                       "variant": a.variant or None}, f)
        return [sys.executable, "-m", "tools.vision_bench", "--child", p]
    try:
        results = run.bench([i for i in items if not tasks or i["task"] in tasks], pairs(cands, devices, models),
                            info["devices"], child_cmd, models_dir=a.models_dir)
    finally:
        shutil.rmtree(cfg_dir, ignore_errors=True)
    with open(os.path.join(a.out, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"probe": info, "results": results}, f, ensure_ascii=False, indent=1, default=str)
    try:
        from .report import summary
    except ImportError:
        return 0
    text = summary(results, info)
    with open(os.path.join(a.out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
