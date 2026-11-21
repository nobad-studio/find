"""The benchmark's photo set: a set.json in a folder of the maintainer's own photos (dev only, never in the repo).

    {"version": 1, "items": [{"id", "image", "image2"?, "task", "question"?, "kind", "expect"}, ...]}

Image paths are relative to the set's folder and must stay inside it. `evalset.example.json` (committed) has the
50-item mix with image names only.
"""
import json
import os

from .score import KINDS

TASKS = ("detect", "ocr", "caption", "ask", "compare")


def _expect_ok(kind, e):
    """objects/describe: list of words or synonym lists; text: a string; count: an int; yesno: a bool."""
    if kind in ("objects", "describe"):
        return isinstance(e, list) and bool(e) and all(
            isinstance(g, str) or (isinstance(g, list) and g and all(isinstance(s, str) for s in g)) for g in e)
    if kind == "text":
        return isinstance(e, str) and bool(e.strip())
    if kind == "count":
        return isinstance(e, int) and not isinstance(e, bool) and e >= 0
    return isinstance(e, bool)


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
        if "expect" not in raw or not _expect_ok(kind, raw["expect"]):
            raise ValueError(f"item {iid}: expect doesn't fit kind {kind}")
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
