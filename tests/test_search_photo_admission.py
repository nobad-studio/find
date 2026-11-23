"""Photo admission policy D (Experiment A, docs/measurements.md): on a keyword-style search ("lease", "dog") a
photo found only by its look must be close to the best photo; weaker ones stay only with other evidence (a name,
words inside it, meaning). Visual descriptions are unchanged. Rollback: NOBAD_FIND_PHOTO_ADMIT=off, or the
"admit_all" variant in the eval tools."""
import numpy as np
import pytest

from nobadfind import embed, photo, search
from nobadfind.query import parse
from nobadfind.store import Store


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


class _Text:
    """Dimension 0 = dog, 1 = beach."""
    def encode(self, text):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[2] = ("dog" in text), ("beach" in text), 1.0
        return _unit(v)


@pytest.fixture
def photos(tmp_path, monkeypatch):
    """IMG_0042 shows a dog; IMG_0043 and dog_walk.jpg show a beach, but dog_walk.jpg is named for the dog."""
    monkeypatch.delenv("NOBAD_FIND_PHOTO_ADMIT", raising=False)
    monkeypatch.delenv("NOBAD_FIND_PHOTO_V2", raising=False)
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(f"C:\\p\\{n}", n, "C:\\p", ".jpg", "image", 50_000, t, t, 1)
                    for t, n in enumerate(("IMG_0042.jpg", "IMG_0043.jpg", "dog_walk.jpg"), 1)])
    ids = dict(s.q("SELECT name, id FROM files"))

    def at(dog, beach):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[3] = dog, beach, 1.0
        return _unit(v)
    vi = embed.VectorIndex(photo.PHOTO_DIM, ())
    vi.add([ids["IMG_0042.jpg"], ids["IMG_0043.jpg"], ids["dog_walk.jpg"]],
           np.stack([at(1.0, 0.0), at(0.0, 1.0), at(0.0, 1.0)]))
    yield lambda text: [x["name"] for x in search.search(s, text, photo_text=_Text(), pindex=vi)["results"]]
    s.close()


def test_keyword_searches_admit_photos_only_with_evidence(photos):
    found = photos("dog")
    assert "IMG_0042.jpg" in found                           # the photo that shows it: near the best, kept
    assert "dog_walk.jpg" in found                           # looks wrong, but its name says dog: kept
    assert "IMG_0043.jpg" not in found                       # only a weak look-alike, nothing else: dropped


def test_described_searches_are_unchanged(photos, monkeypatch):
    for text in ("my dog at home", "photos of my dog"):     # a description; asking for photos
        found = photos(text)
        assert "IMG_0043.jpg" in found, text                 # the weak look-alike stays (shown as less sure)
        monkeypatch.setenv("NOBAD_FIND_PHOTO_ADMIT", "off")
        assert photos(text) == found, text
        monkeypatch.delenv("NOBAD_FIND_PHOTO_ADMIT")


def test_the_flag_and_the_admit_all_variant_roll_back(photos, monkeypatch):
    monkeypatch.setenv("NOBAD_FIND_PHOTO_ADMIT", "off")
    today = photos("dog")
    assert "IMG_0043.jpg" in today                           # before D: every photo the look channel found
    monkeypatch.delenv("NOBAD_FIND_PHOTO_ADMIT")
    monkeypatch.setattr(search, "VARIANTS", {"admit_all"})
    assert photos("dog") == today
    monkeypatch.setattr(search, "VARIANTS", {"admit_query"})
    monkeypatch.setenv("NOBAD_FIND_PHOTO_ADMIT", "off")
    assert "IMG_0043.jpg" not in photos("dog")               # the eval tools' explicit variant wins


def test_photo_admission_is_on_by_default():
    assert search.photo_admission()


def test_keyword_style_means_one_content_word_and_no_picture_words():
    assert search._keywordish(parse("invoice")) and search._keywordish(parse("invoice march"))
    assert not search._keywordish(parse("a red car"))
    assert not search._keywordish(parse("photos of my dog"))
