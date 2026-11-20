"""0.9.1: the user's own folders first in every work queue; a folder a search just asked about first of all."""
import os

from nobadfind import photo
from nobadfind.store import Store

APP, PICS, DL = r"C:\Program Files\App", r"C:\Users\me\Pictures", r"C:\Users\me\Downloads"


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    rows = [(APP + rf"\p{i}.jpg", f"p{i}.jpg", APP, ".jpg", "image", 50_000, 100.0 + i, 1.0, 1) for i in range(5)]
    rows += [(PICS + r"\a.jpg", "a.jpg", PICS, ".jpg", "image", 50_000, 1.0, 1.0, 1),
             (DL + r"\shirt.jpg", "shirt.jpg", DL, ".jpg", "image", 50_000, 2.0, 1.0, 1),
             (DL + r"\notes.txt", "notes.txt", DL, ".txt", "text", 500, 3.0, 1.0, 1),
             (APP + r"\readme.txt", "readme.txt", APP, ".txt", "text", 500, 300.0, 1.0, 1)]
    s.upsert_files(rows)
    return s


def test_photos_your_folders_first_then_the_asked_folder(tmp_path):
    s = _store(tmp_path)

    def todo():
        return [os.path.basename(r[1]) for r in s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES,
                                                                 photo.MAX_PHOTO_BYTES, limit=3)]
    assert todo() == ["p4.jpg", "p3.jpg", "p2.jpg"]                      # no preference: newest anywhere
    s.prefer_roots = (PICS, DL)
    assert todo() == ["a.jpg", "shirt.jpg", "p4.jpg"]                    # yours first, then the rest, newest first
    s.asked_roots = (DL,)
    assert todo() == ["shirt.jpg", "a.jpg", "p4.jpg"]                    # the folder you just searched, first
    s.close()


def test_texts_and_names_too(tmp_path):
    s = _store(tmp_path)
    s.prefer_roots = (DL,)
    assert [os.path.basename(r[1]) for r in s.needs_text({".txt"}, 10_000, limit=2)] == ["notes.txt", "readme.txt"]
    names = [r[1] for r in s.names_without_vectors({"image"}, limit=2)]
    assert names[0] == "shirt.jpg"
    s.close()


def test_a_folder_like_the_preferred_one_isnt_mistaken_for_it(tmp_path):
    """C:\\Users\\me\\Downloads2 isn't inside Downloads (the range ends at Downloads\\)."""
    s = _store(tmp_path)
    s.upsert_files([(DL + r"2\x.jpg", "x.jpg", DL + "2", ".jpg", "image", 50_000, 0.5, 1.0, 1)])
    s.prefer_roots = (DL,)
    first = os.path.basename(s.photos_to_read(photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES,
                                              limit=1)[0][1])
    assert first == "shirt.jpg"
    s.close()


def test_a_photo_search_in_a_folder_looks_at_that_folder_now(tmp_path, monkeypatch):
    """0.9.1: "in downloads black shirt image" while photos aren't all looked at: the hint counts that folder's
    photos, and the indexer is told to do them first and now."""
    from nobadfind import api as api_mod, embed, settings, winapi
    real_dl = winapi.known_folder("downloads") or DL
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([(os.path.join(real_dl, f"IMG_{i}.jpg"), f"IMG_{i}.jpg", real_dl, ".jpg", "image", 50_000, 1.0,
                     1.0, 1) for i in range(3)]
                   + [(APP + rf"\p{i}.jpg", f"p{i}.jpg", APP, ".jpg", "image", 50_000, 1.0, 1.0, 1) for i in range(9)])
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"photo_meaning": True})
    hurried = []

    class Ix:
        embedder = None
        photo_text = None
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ())
        drive_list = []
        photo_model = None

        def roots(self, drives):
            return []

        def hurry_photos(self, roots):
            hurried.append(tuple(roots))
    monkeypatch.setattr(api_mod.models, "ready", lambda mid, d=None: True)
    a = api_mod.Api(s, st, Ix(), None)
    a._totals = (0.0, None, {"photos": (12, 12)})
    need = a.search("in downloads black shirt image")["needs"][0]
    assert (need["state"], need["done"], need["total"]) == ("analyzing", 0, 3)     # Downloads' 3, not all 12
    assert hurried == [(real_dl,)]
    hurried.clear()
    a.search("black shirt image")                                                  # no folder: nothing to hurry
    assert hurried == []
    s.close()


def test_new_files_jump_every_queue(tmp_path):
    """0.9.3: a file that just appeared (the live watcher) is read before your folders and the rest."""
    from nobadfind.store import Store
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    dl, other = r"C:\Users\me\Downloads", r"C:\Program Files\App"
    s.upsert_files([(other + r"\a.txt", "a.txt", other, ".txt", "text", 10, 3.0, 1.0, 1),
                    (dl + r"\b.txt", "b.txt", dl, ".txt", "text", 10, 2.0, 1.0, 1),
                    (other + r"\new.txt", "new.txt", other, ".txt", "text", 10, 1.0, 1.0, 1)])
    s.prefer_roots = (dl,)
    assert [r[1] for r in s.needs_text({".txt"}, 100, limit=3)][0].endswith("b.txt")
    s.mark_fresh([other + r"\new.txt"])
    got = [r[1] for r in s.needs_text({".txt"}, 100, limit=3)]
    assert got[0].endswith("new.txt") and got[1].endswith("b.txt") and len(got) == 3
    s.mark_fresh([other + r"\new.txt"], now=0)                     # long ago: no longer first
    assert [r[1] for r in s.needs_text({".txt"}, 100, limit=3)][0].endswith("b.txt")
    s.close()


def test_a_new_file_in_your_folders_cuts_the_turn_short(tmp_path):
    from nobadfind import indexer
    ix = indexer.Indexer.__new__(indexer.Indexer)
    marked = []
    ix.store = type("St", (), {"prefer_roots": (r"C:\Users\me\Downloads",), "mark_fresh": lambda self, p: marked.extend(p)})()
    ix._clock = lambda: 100.0
    ix._round_end = 999.0
    ix.wake = type("E", (), {"set": lambda self: None})()
    ix._fresh_files([r"C:\Program Files\App\cache.bin"])
    assert ix._round_end == 999.0 and marked                         # elsewhere: front of the queue only
    ix._fresh_files([r"C:\Users\me\Downloads\photo.jpg"])
    assert ix._round_end == 0.0                                      # your folder: the turn ends now
    ix._round_end = 999.0
    ix._fresh_files([r"C:\Users\me\Downloads\photo2.jpg"])
    assert ix._round_end == 999.0                                    # not again within 30 s
