"""summary.md for a benchmark run: this PC, then one table per layer (dev only)."""

L1 = ("florence2-base-ft",)
DEEP_PASS_PHOTOS = 10_000
KIND_ORDER = ("objects", "text", "count", "yesno", "describe")


def deep_pass_hours(ms_per_item, photos=DEEP_PASS_PHOTOS):
    return "-" if ms_per_item is None else f"{ms_per_item * photos / 3_600_000:.1f} h"


def _num(v, fmt="{:.0f}"):
    return "-" if v is None else fmt.format(v)


def _name(r):
    v = r.get("variant")
    return r["candidate"] + (f" [{v}]" if v and v != "base" else "")


def _row(r):
    if r["status"] != "ok":
        return f"| {_name(r)} | {r['device']} | {r['status']}: {r.get('why', '')} |" + " - |" * 8
    sc = r.get("scores", {})
    kinds = ", ".join(f"{k} {sc[k]:.2f}" for k in KIND_ORDER if k in sc) or "-"
    return (f"| {_name(r)} | {r['device']} | ok | {_num(r.get('load_s'), '{:.1f}')} | "
            f"{_num(r.get('ms_per_item'))} | {_num(r.get('peak_private_mb'))} | {_num(r.get('peak_gpu_mb'))} | "
            f"{r.get('errors', 0)} | {kinds} | {sc.get('all', 0):.2f} | {deep_pass_hours(r.get('ms_per_item'))} |")


HEAD = ("| candidate | device | status | load s | ms per photo | peak RAM MB | peak GPU MB | errors | score per kind "
        f"| overall | {DEEP_PASS_PHOTOS:,} photos |\n|---|---|---|---|---|---|---|---|---|---|---|")


def summary(results, probe):
    hw = probe.get("hardware", {})
    gpu = hw.get("gpu") or "no graphics card"
    lines = [f"PC: {hw.get('cores', '?')} cores / {hw.get('threads', '?')} threads, {hw.get('ram_gb', '?')} GB RAM, "
             f"{gpu} ({hw.get('vram_gb', '?')} GB own memory)", ""]
    for title, pick in (("### L1: see and read (objects, text, captions)", lambda c: c in L1),
                        ("### L2: talk (ask, compare, describe)", lambda c: c not in L1)):
        rows = [r for r in results if pick(r["candidate"])]
        lines += [title, "", HEAD] + [_row(r) for r in rows] + [""]
    lines.append(f"Time for {DEEP_PASS_PHOTOS:,} photos = ms per photo x {DEEP_PASS_PHOTOS:,} (compute only, model "
                 "loaded once). GPU MB counts dedicated + shared GPU memory; '-' = Windows had no counter for it.")
    return "\n".join(lines) + "\n"
