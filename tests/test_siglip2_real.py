"""Real SigLIP 2 files, real loading path: photo vectors must match the fp32 reference.

Skipped unless NOBAD_FIND_SIGLIP2_DIR points at a folder with the pinned files (vision.onnx, text.onnx,
tokenizer.json); CI doesn't download 481 MB. Measured 2026-11-22 on three drawn pictures: the re-pinned fp16
vision gives cosine 1.000 to the fp32 export, the old 8-bit vision file 0.88-0.92 (it blurred photo search:
held-out nDCG@10 -0.18). tests/data/siglip2_ref.npy holds the fp32 vectors (float16, 3 x 768).
Re-make them (only after a deliberate model change): NOBAD_FIND_SIGLIP2_DIR=<fp32 folder> SIGLIP2_WRITE_REF=1.
"""
import importlib
import os

import numpy as np
import pytest

REF = os.path.join(os.path.dirname(__file__), "data", "siglip2_ref.npy")
DRAWINGS = ("stripes", "circle", "grid")
pytestmark = pytest.mark.skipif(not os.environ.get("NOBAD_FIND_SIGLIP2_DIR"),
                                reason="needs the SigLIP 2 files: set NOBAD_FIND_SIGLIP2_DIR to their folder")


def draw(name, folder):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (320, 240), (240, 240, 235))
    d = ImageDraw.Draw(im)
    if name == "stripes":
        for x in range(0, 320, 20):
            d.rectangle([x, 0, x + 9, 240], fill=(20, 20, 160))
    elif name == "circle":
        d.ellipse([90, 50, 230, 190], fill=(200, 30, 30))
    else:
        for x in range(0, 320, 40):
            for y in range(0, 240, 40):
                if (x // 40 + y // 40) % 2:
                    d.rectangle([x, y, x + 39, y + 39], fill=(0, 0, 0))
    p = os.path.join(folder, name + ".png")
    im.save(p)
    return p


def _vectors(folder, tmp):
    importlib.import_module("onnxruntime")          # before winrt (the MSVCP140 load-order trap)
    from nobadfind import photo
    photo._vision.clear()
    out = []
    for n in DRAWINGS:
        _f, _m, blob, err = photo.embed_photo((1, draw(n, tmp), 1.0, folder))
        assert not err, err
        out.append(np.frombuffer(blob, np.float16).astype(np.float32))
    return np.stack(out)


def test_siglip2_photo_vectors_match_the_fp32_reference(tmp_path):
    got = _vectors(os.environ["NOBAD_FIND_SIGLIP2_DIR"], str(tmp_path))
    if os.environ.get("SIGLIP2_WRITE_REF"):
        os.makedirs(os.path.dirname(REF), exist_ok=True)
        np.save(REF, got.astype(np.float16))
    ref = np.load(REF).astype(np.float32)
    cos = (got * ref).sum(1) / np.linalg.norm(got, axis=1) / np.linalg.norm(ref, axis=1)
    assert cos.min() >= 0.995, dict(zip(DRAWINGS, cos.round(4)))


def test_siglip2_questions_find_the_matching_drawing(tmp_path):
    from nobadfind import photo
    d = os.environ["NOBAD_FIND_SIGLIP2_DIR"]
    vecs = _vectors(d, str(tmp_path))
    enc = photo.TextEncoder(d, style="siglip2")
    for i, q in enumerate(("blue vertical stripes", "a red circle", "a black and white checkerboard")):
        scores = vecs @ enc.encode_question(q)
        assert int(np.argmax(scores)) == i, (q, scores.round(3))
