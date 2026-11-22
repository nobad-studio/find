"""tools/vision_bench/evalset.py: the maintainer's local photo set (never in the repo) and the committed example."""
import json
import os

import pytest

from tools.vision_bench.evalset import load_set

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "vision_bench",
                       "evalset.example.json")


def _write(tmp_path, items, images=("a.jpg", "b.jpg")):
    for name in images:
        (tmp_path / name).write_bytes(b"x")
    p = tmp_path / "set.json"
    p.write_text(json.dumps({"version": 1, "items": items}), encoding="utf-8")
    return str(p)


def test_loads_and_resolves_paths(tmp_path):
    p = _write(tmp_path, [{"id": "sign-01", "image": "a.jpg", "task": "ocr", "kind": "text", "expect": "EXIT"},
                          {"id": "same-01", "image": "a.jpg", "image2": "b.jpg", "task": "compare",
                           "question": "Same place?", "kind": "yesno", "expect": True}])
    items = load_set(p)
    assert [i["id"] for i in items] == ["sign-01", "same-01"]
    assert all(os.path.isabs(i["image"]) and os.path.isfile(i["image"]) for i in items)
    assert items[0]["image2"] is None and items[0]["question"] is None
    assert os.path.isfile(items[1]["image2"])


def test_missing_image_names_item(tmp_path):
    p = _write(tmp_path, [{"id": "sign-01", "image": "nope.jpg", "task": "ocr", "kind": "text", "expect": "EXIT"}])
    with pytest.raises(ValueError, match="sign-01"):
        load_set(p)


def test_compare_needs_image2(tmp_path):
    p = _write(tmp_path, [{"id": "c1", "image": "a.jpg", "task": "compare", "question": "Same?", "kind": "yesno",
                           "expect": True}])
    with pytest.raises(ValueError, match="c1"):
        load_set(p)


def test_ask_needs_question(tmp_path):
    p = _write(tmp_path, [{"id": "q1", "image": "a.jpg", "task": "ask", "kind": "count", "expect": 2}])
    with pytest.raises(ValueError, match="q1"):
        load_set(p)


def test_path_outside_set_folder_refused(tmp_path):
    sub = tmp_path / "set"
    sub.mkdir()
    (tmp_path / "x.jpg").write_bytes(b"x")
    p = _write(sub, [{"id": "out", "image": "..\\x.jpg", "task": "ocr", "kind": "text", "expect": "A"}])
    with pytest.raises(ValueError, match="out"):
        load_set(p)


def test_unknown_kind_refused(tmp_path):
    p = _write(tmp_path, [{"id": "k", "image": "a.jpg", "task": "ocr", "kind": "vibes", "expect": "A"}])
    with pytest.raises(ValueError, match="k"):
        load_set(p)


def test_duplicate_id_refused(tmp_path):
    item = {"id": "d", "image": "a.jpg", "task": "ocr", "kind": "text", "expect": "A"}
    with pytest.raises(ValueError, match="d"):
        load_set(_write(tmp_path, [item, item]))


def test_example_file_is_valid_shape():
    items = load_set(EXAMPLE, check_files=False)
    assert len(items) == 50
    tasks = [i["task"] for i in items]
    assert tasks.count("detect") == 15 and tasks.count("ocr") == 15 and tasks.count("ask") == 10
    assert tasks.count("caption") == 5 and tasks.count("compare") == 5


def test_expect_type_checked_per_kind(tmp_path):
    bad = [("count", "three"), ("yesno", "yes"), ("text", 5), ("objects", "dog"), ("describe", [3])]
    for kind, expect in bad:
        p = _write(tmp_path, [{"id": f"e-{kind}", "image": "a.jpg", "task": "detect", "kind": kind, "expect": expect}])
        with pytest.raises(ValueError, match=f"e-{kind}"):
            load_set(p)
