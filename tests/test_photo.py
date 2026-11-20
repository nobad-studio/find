"""Photo meaning (decode, store, search) and the one-click Windows Search switch."""
import numpy as np
import pytest

from nobadfind import embed, ocr, photo, search, winapi
from nobadfind.store import Store


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


@pytest.mark.skipif(not ocr.available(), reason="needs Windows' imaging (winrt)")
def test_decode_224_makes_the_models_picture():
    img = ocr.gray_bmp(300, 200, bytes([0] * 300 * 100 + [255] * 300 * 100))      # black top, white bottom
    px = photo.decode_224(img)
    assert px.shape == (3, 224, 224) and px.dtype == np.float32
    assert px.min() >= -1.0 and px.max() <= 1.0
    assert px[:, 10, :].mean() < -0.9 and px[:, 214, :].mean() > 0.9             # the right way up
    assert photo.decode_224(ocr.gray_bmp(40, 40, bytes(1600))) is None             # too small to be a photo


def test_embed_photo_never_raises(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\xff\xd8 nope" * 3000)
    import faulthandler
    on = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        fid, mt, blob, err = photo.embed_photo((7, str(p), 1.0, str(tmp_path)))
    finally:
        if on:
            faulthandler.enable()
    assert (fid, mt, blob) == (7, 1.0, b"") and err


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    rows = [("C:\\p\\IMG_0042.jpg", "IMG_0042.jpg", "C:\\p", ".jpg", "image", 50_000, 1.0, 1.0, 1),
            ("C:\\p\\IMG_0043.jpg", "IMG_0043.jpg", "C:\\p", ".jpg", "image", 50_000, 2.0, 2.0, 1),
            ("C:\\p\\icon.png", "icon.png", "C:\\p", ".png", "image", 900, 3.0, 3.0, 1),
            ("C:\\p\\lease.pdf", "lease.pdf", "C:\\p", ".pdf", "pdf", 50_000, 4.0, 4.0, 1)]
    s.upsert_files(rows)
    return s


def test_photo_rows_follow_the_files(tmp_path):
    s = _store(tmp_path)
    todo = s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES)
    assert sorted(r[1] for r in todo) == ["C:\\p\\IMG_0042.jpg", "C:\\p\\IMG_0043.jpg"]   # not the tiny icon
    for fid, _p, mt in todo:
        s.set_photo_vector(fid, mt, _unit(np.ones(photo.PHOTO_DIM)).astype(np.float16).tobytes())
    assert s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES) == []
    s.upsert_files([("C:\\p\\IMG_0042.jpg", "IMG_0042.jpg", "C:\\p", ".jpg", "image", 50_000, 9.0, 9.0, 1)])
    assert [r[1] for r in s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES)] == \
        ["C:\\p\\IMG_0042.jpg"]                                                     # changed: read again
    s.remove_paths(["C:\\p\\IMG_0043.jpg"])
    assert s.stats()["photo_vectors"] == 1                                         # gone with its file
    s.close()


class _Text:
    """Dimension 0 = dog, 1 = beach."""
    def encode(self, text):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[2] = ("dog" in text), ("beach" in text), 1.0
        return _unit(v)


def _pindex(s):
    ids = dict(s.q("SELECT name, id FROM files"))
    vi = embed.VectorIndex(photo.PHOTO_DIM, ())

    def at(dog, beach):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[1], v[3] = dog, beach, 1.0
        return _unit(v)
    vi.add([ids["IMG_0042.jpg"], ids["IMG_0043.jpg"]], np.stack([at(1.0, 0.0), at(0.0, 1.0)]))
    return vi


def test_photos_found_by_what_they_show(tmp_path):
    s = _store(tmp_path)
    vi = _pindex(s)
    r = search.search(s, "dog", photo_text=_Text(), pindex=vi)["results"]
    assert r[0]["name"] == "IMG_0042.jpg" and any("picture" in w for w in r[0]["why"])
    assert search.search(s, "beach", photo_text=_Text(), pindex=vi)["results"][0]["name"] == "IMG_0043.jpg"
    assert search.search(s, "dog pdf", photo_text=_Text(), pindex=vi)["results"] == []   # not asking for photos
    s.close()


def test_switch_to_nobad_find(monkeypatch, tmp_path):
    from nobadfind import api as api_mod, settings
    st = settings.Settings(str(tmp_path / "s.json"))
    calls = []
    monkeypatch.setattr(api_mod.wsearch, "state", lambda: {"start": "delayed-auto", "running": True})
    monkeypatch.setattr(api_mod.wsearch, "request", lambda start: calls.append(start) or True)
    monkeypatch.setattr(api_mod, "set_autostart", lambda on: calls.append(("autostart", on)))

    class Ix:
        embedder = None
        photo_text = None
    a = api_mod.Api(None, st, Ix(), None)
    assert a.use_instead_of_windows_search(True)["ok"]
    assert calls == ["disabled", ("autostart", True)] and st.get("wsearch_prev") == "delayed-auto"
    assert st.get("autostart") is True
    calls.clear()
    assert a.use_instead_of_windows_search(False)["ok"] and calls == ["delayed-auto"]   # back as it was


def test_photo_files_are_pinned():
    for name, (path, size, sha) in photo.PHOTO_FILES.items():
        assert path and size > 1000 and len(sha) == 64 and int(sha, 16) >= 0
    assert photo.PHOTO_URL.startswith("https://huggingface.co/") and len(photo.PHOTO_REV) == 40
    assert winapi  # imported for the skip markers' module


def test_a_filtered_photo_search_ranks_the_photos_that_fit(tmp_path):
    """0.9.0: "dog in downloads" on a big PC. Hundreds of better dog photos elsewhere used to fill the photo
    search's top few hundred before the Downloads filter was applied, leaving none from Downloads; now a filtered
    photo search ranks only the photos that fit."""
    import os
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    rows = [(f"C:\Pics\dog{i}.jpg", f"dog{i}.jpg", "C:\Pics", ".jpg", "image", 50_000, 1.0, 1.0, 1)
            for i in range(400)]
    rows.append((os.path.join(dl, "IMG_7.jpg"), "IMG_7.jpg", dl, ".jpg", "image", 50_000, 1.0, 1.0, 1))
    s.upsert_files(rows)
    ids = dict(s.q("SELECT name, id FROM files"))
    vi = embed.VectorIndex(photo.PHOTO_DIM, ())

    def at(dog):
        v = np.zeros(photo.PHOTO_DIM, np.float32)
        v[0], v[3] = dog, 1.0
        return _unit(v)
    strong, weak = at(3.0), at(1.0)
    for name, fid in ids.items():
        vec = weak if name == "IMG_7.jpg" else strong
        s.set_photo_vector(fid, 1.0, vec.astype(np.float16).tobytes())
    vi.add(list(ids.values()), np.stack([weak if n == "IMG_7.jpg" else strong for n in ids]))
    r = search.search(s, "dog image in downloads", photo_text=_Text(), pindex=vi)["results"]
    assert [x["name"] for x in r][:1] == ["IMG_7.jpg"]
    s.close()


def test_a_photo_search_says_what_it_needs(tmp_path, monkeypatch):
    """0.9.0 `needs`: the photo model missing, switched off, or photos still being looked at."""
    from nobadfind import api as api_mod, models, settings
    s = _store(tmp_path)
    st = settings.Settings(str(tmp_path / "s.json"))

    class Ix:
        embedder = None
        photo_text = None
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ())
        drive_list = []
        photo_model = None

        def roots(self, drives):
            return []
    a = api_mod.Api(s, st, Ix(), None)
    ready = {"on": False}
    monkeypatch.setattr(api_mod.models, "ready", lambda mid, d=None: ready["on"])
    need = a.search("black shirt image")["needs"][0]
    assert need["model"] == "photo" and need["state"] == "missing" and need["size_mb"] > 0
    assert "photo model" in need["text"]
    ready["on"] = True
    st.update({"photo_meaning": False})
    assert a.search("black shirt image")["needs"][0]["state"] == "off"
    st.update({"photo_meaning": True})
    a._totals = (0.0, None, {"photos": (8400, 8280)})
    n = a.search("black shirt image")["needs"][0]
    assert (n["state"], n["done"], n["total"]) == ("analyzing", 0, 8400)
    assert "needs" not in a.search("lease.pdf")                     # nothing photo about it, and it's found
    a._totals = (0.0, None, {"photos": (8400, 0)})
    Ix.pindex.add([1], np.stack([_unit(np.ones(photo.PHOTO_DIM))]))
    assert "needs" not in a.search("black shirt image")             # every photo looked at: nothing to say
    assert models.size_mb(models.get(models.DEFAULT_PHOTO)) > 0
    s.close()
