"""The benchmark's photo set: a set.json in a folder of the maintainer's own photos (dev only, never in the repo).

    {"version": 1, "items": [{"id", "image", "image2"?, "task", "question"?, "kind", "expect"}, ...]}

Image paths are relative to the set's folder and must stay inside it. `evalset.example.json` (committed) has the
50-item mix with image names only.
"""
import json
import os

from .score import KINDS

TASKS = ("detect", "ocr", "caption", "ask", "compare")


def _inside(folder, rel, item_id):
    if not isinstance(rel, str) or not rel or os.path.isabs(rel):
        raise ValueError(f"item {item_id}: image path must be relative to the set folder")
    p = os.path.realpath(os.path.join(folder, rel))
    if os.path.commonpath([p, folder]) != folder:
        raise ValueError(f"item {item_id}: image path leaves the set folder")
    return p


def load_set(path, check_files=True):
    """Items of the set at `path`, with absolute image paths; ValueError naming the item on anything wrong."""
    folder = os.path.realpath(os.path.dirname(os.path.abspath(path)))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != 1 or not isinstance(data.get("items"), list):
        raise ValueError("set.json: need version 1 and an items list")
    out, seen = [], set()
    for raw in data["items"]:
        iid = str(raw.get("id") or "")
        if not iid or iid in seen:
            raise ValueError(f"item {iid!r}: missing or duplicate id")
        seen.add(iid)
        task, kind = raw.get("task"), raw.get("kind")
        if task not in TASKS:
            raise ValueError(f"item {iid}: unknown task {task!r}")
        if kind not in KINDS:
            raise ValueError(f"item {iid}: unknown kind {kind!r}")
        if "expect" not in raw:
            raise ValueError(f"item {iid}: no expect")
        question = raw.get("question")
        if task in ("ask", "compare") and not question:
            raise ValueError(f"item {iid}: task {task} needs a question")
        image = _inside(folder, raw.get("image"), iid)
        image2 = _inside(folder, raw["image2"], iid) if raw.get("image2") else None
        if task == "compare" and not image2:
            raise ValueError(f"item {iid}: compare needs image2")
        if check_files:
            for p in (image, image2):
                if p and not os.path.isfile(p):
                    raise ValueError(f"item {iid}: no file {os.path.basename(p)}")
        out.append({"id": iid, "image": image, "image2": image2, "task": task, "question": question or None,
                    "kind": kind, "expect": raw["expect"]})
    return out
