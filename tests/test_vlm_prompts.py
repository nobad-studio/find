"""Prompts, question rules and the picture input for talk about a photo."""

import importlib
import importlib.util
importlib.import_module("onnxruntime")      # must load before winrt (MSVCP140)
import pytest

from nobadfind import ocr, photo
from nobadfind.vlm import prompts


def test_question_is_cleaned_and_capped():
    assert len(prompts.clean_question("a" * 10000)) == 500
    assert prompts.clean_question("\x00\x1b[31mhi") == "hi"
    assert prompts.clean_question("  a \n\t b  ") == "a b"


def test_text_questions_are_recognised():
    assert prompts.is_text_question("what's written here?")
    assert prompts.is_text_question("हिंदी में क्या लिखा है")
    assert not prompts.is_text_question("how many dogs?")


def test_devanagari_answers_are_flagged():
    assert prompts.flag_unverified("यह एक कुत्ता है")
    assert not prompts.flag_unverified("a dog")


def test_templates_and_limits():
    assert "two photos" in prompts.compare(None) and "Question:" not in prompts.compare(None)
    assert "how many?" in prompts.ask("how many?") and "how many?" in prompts.compare("how many?")
    assert prompts.describe()
    assert [prompts.max_tokens(k) for k in ("describe", "ask", "compare")] == [200, 120, 160]


needs_winrt = pytest.mark.skipif(not ocr.available(), reason="needs Windows' imaging (winrt)")


@needs_winrt
def test_decode_for_vlm_refuses_unusable(monkeypatch):
    assert photo.decode_rgb(b"", 512) is None
    assert photo.decode_rgb(ocr.gray_bmp(40, 63, bytes(40 * 63)), 512) is None
    big = ocr.gray_bmp(100, 100, bytes(10000))
    assert photo.decode_rgb(big, 512) is not None
    monkeypatch.setattr(photo, "MAX_PIXELS", 5000)
    assert photo.decode_rgb(big, 512) is None
    assert photo.decode_rgb(b"not an image" * 2000, 512) is None


@needs_winrt
def test_decode_rgb_keeps_aspect():
    img = ocr.gray_bmp(2000, 1000, bytes([0] * 2000 * 500 + [255] * 2000 * 500))
    rgb, w, h = photo.decode_rgb(img, 512)
    assert (w, h) == (512, 256) and len(rgb) == 512 * 256 * 3
    assert rgb[10 * 512 * 3] < 5 and rgb[250 * 512 * 3] > 250        # black above, white below
    small = ocr.gray_bmp(300, 200, bytes(300 * 200))
    assert photo.decode_rgb(small, 512)[1:] == (300, 200)           # never enlarged


needs_pil = pytest.mark.skipif(importlib.util.find_spec("PIL") is None,
                               reason="Pillow (dev dependency) not installed")


def _jpeg(orientation):
    """A stored 400 x 200 JPEG: left quarter red, the rest blue, with an EXIF orientation tag."""
    import io
    from PIL import Image
    im = Image.new("RGB", (400, 200), (0, 0, 255))
    im.paste((255, 0, 0), (0, 0, 100, 200))
    ex = im.getexif()
    ex[274] = orientation
    b = io.BytesIO()
    im.save(b, "JPEG", exif=ex, quality=95, subsampling=0)
    return b.getvalue()


def _px(rgb, w, x, y):
    return tuple(rgb[(y * w + x) * 3:(y * w + x) * 3 + 3])


@needs_winrt
@needs_pil
@pytest.mark.parametrize("orientation, size, red_at, blue_at", [
    (1, (200, 100), (10, 50), (190, 50)),        # as stored: red on the left
    (6, (100, 200), (50, 10), (50, 190)),        # turned clockwise: red at the top
    (8, (100, 200), (50, 190), (50, 10)),        # turned anticlockwise: red at the bottom
])
def test_decode_rgb_turns_a_photo_upright_without_squeezing(orientation, size, red_at, blue_at):
    rgb, w, h = photo.decode_rgb(_jpeg(orientation), 200)
    assert (w, h) == size
    r, g, b = _px(rgb, w, *red_at)
    assert r > 200 and g < 60 and b < 60
    r, g, b = _px(rgb, w, *blue_at)
    assert b > 200 and r < 60 and g < 60
