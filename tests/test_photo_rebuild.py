"""Photo vectors rebuild beside the old ones (1.2.0). 1.0.0's SigLIP 2 re-pin dropped every photo vector at once on
upgrade: photo search was near empty for the hour+ it took to look at the photos again. Now a new photo vector
identity (another model, or a re-pin: models.vector_tag) is built in pvecs_next (meta pvec_next_model) while the
old vectors keep answering with their own model, and the two swap in one transaction once pvecs_next covers every
photo. Search never compares one identity's scores with the other's: each is its own channel, fused by RRF."""
import concurrent.futures as cf
import sqlite3

import numpy as np
import pytest

from nobadfind import embed, indexer, models, photo, search
from nobadfind.store import Store


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class SyncPhotoPool:
    def __init__(self, *a, **k):
        self._processes = {}

    def submit(self, fn, *args):
        f = cf.Future()
        f.set_result(fn(*args))
        return f

    def shutdown(self, **k):
        pass


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


OLD = embed.to_blob(_unit(np.r_[1.0, np.zeros(photo.PHOTO_DIM - 1)]))      # what the old identity made
NEW = embed.to_blob(_unit(np.r_[0.0, 1.0, np.zeros(photo.PHOTO_DIM - 2)]))  # what the new one makes


def _photos(s, n, start=0):
    s.upsert_files([(f"C:\\p\\img{i}.jpg", f"img{i}.jpg", "C:\\p", ".jpg", "image", 50_000, 1.0, 1.0, 1)
                    for i in range(start, start + n)])
    return [r[0] for r in s.q("SELECT id FROM files WHERE kind = 'image' ORDER BY id")]


def _patch(monkeypatch, made_with):
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": ("enc", model_dir, style))
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", SyncPhotoPool)

    def embed_photos(jobs, fast=False):
        made_with.append(jobs[0][3])
        return [(fid, mtime, NEW, None) for fid, _p, mtime, _d in jobs]
    monkeypatch.setattr(indexer.photo, "embed_photos", embed_photos)


def _ix(s, st):
    ix = indexer.Indexer(s, st, vindex=embed.VectorIndex())
    ix.status["plan"] = {}
    return ix


def _count(s, t):
    return s.one(f"SELECT count(*) FROM {t} WHERE length(v) > 0")


def test_tag_change_builds_beside_and_swaps(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 3)
    for fid in ids:
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip-base")
    made_with = []
    _patch(monkeypatch, made_with)
    st = S(photo_meaning=True, photo_model="siglip2-base")              # the user picked SigLIP 2
    ix = _ix(s, st)
    ix._load_photo()
    # nothing dropped: the old vectors answer with their own model, the new set starts empty beside them
    assert _count(s, "pvecs") == 3 and s.meta("pvec_model") == "siglip-base"
    assert s.meta("pvec_next_model") == "siglip2-base#2"
    assert ix.photo_model == "siglip-base" and ix.pindex.model == "siglip-base" and ix.pindex.n == 3
    assert ix.photo_text.model_id == "siglip-base"
    assert ix.photo_model_next == "siglip2-base" and ix.pindex_next.model == "siglip2-base"
    assert ix.photo_text_next.model_id == "siglip2-base" and ix.pindex_next.n == 0

    # part of the rebuild, then NOBAD Find stops: no swap while pvecs_next doesn't cover every photo
    monkeypatch.setattr(indexer, "PHOTO_BATCH", 1)
    ix._photo_one_by_one = True
    turns = iter([False, True])
    ix._round_over = lambda: next(turns, True)
    ix._photo_vectors()
    assert _count(s, "pvecs_next") == 1 and _count(s, "pvecs") == 3
    assert s.meta("pvec_model") == "siglip-base" and ix.pindex.model == "siglip-base" and ix.pindex_next.n == 1
    assert made_with == [models.model_dir("siglip2-base")]               # made with the new model only

    # started again: the half-built set is kept, not started over
    ix = _ix(s, st)
    ix._load_photo()
    assert _count(s, "pvecs_next") == 1 and ix.pindex_next.n == 1 and ix.pindex.n == 3
    ix._photo_vectors()
    # every photo covered: one swap, the new identity answers alone
    assert s.meta("pvec_model") == "siglip2-base#2" and not s.meta("pvec_next_model")
    assert {v for (v,) in s.q("SELECT v FROM pvecs")} == {NEW} and _count(s, "pvecs") == 3
    assert s.one("SELECT count(*) FROM pvecs_next") == 0
    assert ix.photo_model == "siglip2-base" and ix.pindex.model == "siglip2-base" and ix.pindex.n == 3
    assert ix.photo_text.model_id == "siglip2-base" and ix.photo_model_next is None
    assert ix.photo_text_next is None and ix.pindex_next.n == 0
    assert any("SigLIP 2" in n for n in ix._notes)
    ix._load_photo()                                                     # loading again changes nothing
    assert _count(s, "pvecs") == 3 and s.meta("pvec_model") == "siglip2-base#2"
    s.close()


def test_switching_back_during_a_rebuild_drops_only_the_new_set(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 2)
    for fid in ids:
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip-base")
    _patch(monkeypatch, [])
    st = S(photo_meaning=True, photo_model="siglip2-base")
    ix = _ix(s, st)
    ix._load_photo()
    s.set_photo_vector(ids[0], 1.0, NEW, next=True)
    st["photo_model"] = "siglip-base"
    ix._load_photo()
    assert _count(s, "pvecs") == 2 and s.one("SELECT count(*) FROM pvecs_next") == 0
    assert not s.meta("pvec_next_model") and ix.photo_model_next is None and ix.photo_model == "siglip-base"
    s.close()


def test_a_deleted_photo_leaves_the_next_set_too(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 2)
    s.set_photo_vector(ids[0], 1.0, NEW, next=True)
    s.remove_paths(["C:\\p\\img0.jpg"])
    assert s.one("SELECT count(*) FROM pvecs_next") == 0
    s.close()


def _run_rebuild_not_asking_the_old_set(s, ix, monkeypatch, old_tag, new_tag, n):
    """One photo per pass: before each pass the old rows and tag are all still there, nothing asks them, and no
    partial set is swapped in; after the last photo, one swap."""
    monkeypatch.setattr(indexer, "PHOTO_BATCH", 1)
    ix._photo_one_by_one = True
    for done in range(n):
        assert s.meta("pvec_model") == old_tag and s.meta("pvec_next_model") == new_tag
        assert {v for (v,) in s.q("SELECT v FROM pvecs")} == {OLD} and _count(s, "pvecs") == n
        assert ix.pindex.n == 0 and ix.photo_old_answers is False         # kept, but never asked
        assert _count(s, "pvecs_next") == done == ix.pindex_next.n
        turns = iter([False, True])
        ix._round_over = lambda: next(turns, True)
        ix._photo_one_by_one = True                                     # one photo this pass
        ix._photo_vectors()
    ix._round_over = lambda: False
    ix._photo_vectors()                                                  # finds nothing left: the swap
    assert s.meta("pvec_model") == new_tag and not s.meta("pvec_next_model")
    assert {v for (v,) in s.q("SELECT v FROM pvecs")} == {NEW} and _count(s, "pvecs") == n == ix.pindex.n
    assert ix.photo_old_answers is True and ix.photo_model_next is None


def test_an_old_model_no_longer_on_this_pc_keeps_its_rows_until_the_swap(tmp_path, monkeypatch):
    """Nothing can ask the old vectors without their model: they aren't searched, but their rows and tag stay
    until the new set covers every photo (never dropped, never a partial swap)."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    for fid in _photos(s, 3):
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip-base")
    _patch(monkeypatch, [])
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: mid == "siglip2-base")
    ix = _ix(s, S(photo_meaning=True, photo_model="siglip2-base"))
    ix._load_photo()
    assert ix.photo_model == ix.photo_model_next == "siglip2-base" and ix.photo_text is ix.photo_text_next
    _run_rebuild_not_asking_the_old_set(s, ix, monkeypatch, "siglip-base", "siglip2-base#2", 3)
    s.close()


def test_a_half_built_set_is_not_swapped_in_when_the_old_model_goes(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 3)
    for fid in ids:
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip-base")
    s.set_meta("pvec_next_model", "siglip2-base#2")
    s.set_photo_vector(ids[0], 1.0, NEW, next=True)                     # a rebuild was a third done
    _patch(monkeypatch, [])
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: mid == "siglip2-base")
    ix = _ix(s, S(photo_meaning=True, photo_model="siglip2-base"))
    ix._load_photo()
    assert s.meta("pvec_model") == "siglip-base" and _count(s, "pvecs") == 3 and _count(s, "pvecs_next") == 1
    assert ix.pindex.n == 0 and ix.pindex_next.n == 1                    # the partial set answers alone
    s.close()


# ---------- search during a rebuild ----------
class _Enc:
    """A stand-in question encoder: dim numbers, all on axis `axis`."""
    def __init__(self, model_id, dim, axis):
        self.model_id, self.dim, self.axis, self.asked = model_id, dim, axis, []

    def encode(self, text):
        self.asked.append(text)
        v = np.zeros(self.dim, np.float32)
        v[self.axis], v[-1] = 1.0, 0.2
        return _unit(v)


class _Idx(embed.VectorIndex):
    """Records the size of every question vector it is searched with."""
    def __init__(self, dim, model):
        super().__init__(dim, ())
        self.model, self.seen = model, []

    def search(self, qvec, k=10):
        self.seen.append(len(qvec))
        return super().search(qvec, k)


def test_search_during_rebuild_uses_one_identity_per_channel(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 4)
    old_enc, new_enc = _Enc("siglip-base", 8, 0), _Enc("siglip2-base", 6, 0)
    old_idx, new_idx = _Idx(8, "siglip-base"), _Idx(6, "siglip2-base")
    on = lambda dim, i: _unit(np.r_[np.eye(dim)[i][:-1], 0.2])          # noqa: E731
    old_idx.add(ids[:3], np.stack([on(8, 0), on(8, 1), on(8, 2)]))     # photos 1-3 in the old identity
    new_idx.add([ids[3]], np.stack([on(6, 0)]))                         # the rebuild has only reached photo 4
    r = search.search(s, "a red car on a road", photo_text=old_enc, pindex=old_idx,
                      photo_next=(new_enc, new_idx))["results"]
    got = {x["id"]: x for x in r}
    assert ids[0] in got and ids[3] in got                               # each set answers with its own model
    assert any("picture" in w for w in got[ids[3]]["why"])
    assert set(old_idx.seen) == {8} and set(new_idx.seen) == {6}       # never one model's question in the other
    assert len(old_enc.asked) == 1 and len(new_enc.asked) == 1
    # a question from the wrong model is never asked of a set
    r2 = search.search(s, "a red car on a road", photo_text=old_enc, pindex=old_idx,
                       photo_next=(old_enc, new_idx))["results"]
    assert ids[3] not in {x["id"] for x in r2}
    # with nothing being rebuilt, search is exactly as before
    plain = search.search(s, "a red car on a road", photo_text=old_enc, pindex=old_idx)
    empty = search.search(s, "a red car on a road", photo_text=old_enc, pindex=old_idx,
                          photo_next=(new_enc, _Idx(6, "siglip2-base")))
    assert [(x["id"], x["why"], x["weak"]) for x in plain["results"]] == \
        [(x["id"], x["why"], x["weak"]) for x in empty["results"]]
    s.close()


# ---------- the note while it rebuilds ----------
def test_progress_note(tmp_path, monkeypatch):
    from nobadfind import api as api_mod, settings
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"photo_meaning": True, "photo_model": "siglip2-base"})

    class Ix:
        embedder = None
        photo_text = None
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ())
        drive_list = []
        photo_model = "siglip-base"
        photo_model_next = "siglip2-base"

        def roots(self, drives):
            return []
    Ix.pindex.add([1], np.stack([_unit(np.ones(photo.PHOTO_DIM))]))
    a = api_mod.Api(s, st, Ix(), None)
    monkeypatch.setattr(api_mod.models, "ready", lambda mid, d=None: True)
    a._totals = (0.0, None, {"photos": (11033, 11033 - 4210)})          # the photos looked at again so far
    n = a.search("black shirt image")["needs"][0]
    assert (n["model"], n["state"], n["done"], n["total"]) == ("photo", "analyzing", 4210, 11033)
    assert n["text"] == ("Looking at your photos again with SigLIP 2: 4,210 of 11,033; "
                         "the old results answer until then")
    s.close()


def test_the_photo_count_follows_the_rebuild(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 3)
    for fid in ids:
        s.set_photo_vector(fid, 1.0, OLD)
    args = (photo.PHOTO_EXT, photo.MIN_PHOTO_BYTES, photo.MAX_PHOTO_BYTES)
    assert s.count_photos_to_read(*args) == 0 and s.count_photos_to_read(*args, next=True) == 3
    s.set_photo_vector(ids[0], 1.0, NEW, next=True)
    assert s.count_photos_to_read(*args, next=True) == 2
    assert [r[0] for r in s.photos_to_read(*args, next=True)] and len(s.photos_to_read(*args, next=True)) == 2
    s.close()


# ---------- upgrade from a 1.0.1 index ----------
# The 1.0.1 schema's photo part (find-v1.0.1:nobadfind/store.py): pvecs and no pvecs_next. The rest of 1.0.1's
# schema is the same as now, so the current one is made first and the photo part is put back the way 1.0.1 had it.
SCHEMA_1_0_1_PHOTOS = """
DROP TABLE IF EXISTS pvecs_next;
DROP TRIGGER IF EXISTS files_ad;
DROP TABLE IF EXISTS vdesc;
CREATE TRIGGER files_ad AFTER DELETE ON files BEGIN
  INSERT INTO names(names, rowid, name, dir) VALUES ('delete', old.id, old.name, old.dir);
  DELETE FROM chunks WHERE file_id = old.id;
  DELETE FROM nvecs WHERE file_id = old.id;
  DELETE FROM pvecs WHERE file_id = old.id; END;
"""


def _index_1_0_1(tmp_path, encrypt, n, tag):
    s = Store(str(tmp_path / "i.db"), str(tmp_path / "i.key"), encrypt=encrypt)
    ids = _photos(s, n)
    with s.wlock:
        s.db.executescript(SCHEMA_1_0_1_PHOTOS)
    for fid in ids:
        s.db.execute("INSERT INTO pvecs(file_id, mtime, v, err) VALUES(?,?,?,NULL)", (fid, 1.0, OLD))
    s.db.execute("INSERT INTO meta(k, v) VALUES('pvec_model', ?)", (tag,))
    s.db.commit()
    assert not s.one("SELECT 1 FROM sqlite_master WHERE name = 'pvecs_next'")
    encrypted = s.encrypted
    s.close()
    return encrypted


@pytest.mark.parametrize("encrypt", [False, True])
def test_upgrade_path_from_1_0_1_index(tmp_path, monkeypatch, encrypt):
    encrypted = _index_1_0_1(tmp_path, encrypt, 5, "siglip2-base#2")
    if encrypt and encrypted:                                            # SQLCipher: unreadable without the key
        with pytest.raises(sqlite3.DatabaseError):
            sqlite3.connect(str(tmp_path / "i.db")).execute("SELECT count(*) FROM pvecs").fetchone()
    made_with = []
    _patch(monkeypatch, made_with)
    monkeypatch.setattr(indexer.photo, "TextEncoder",
                        lambda model_dir, style="siglip": _Enc("siglip2-base", photo.PHOTO_DIM, 0))
    st = S(photo_meaning=True, photo_model="siglip2-base")
    s = Store(str(tmp_path / "i.db"), str(tmp_path / "i.key"), encrypt=encrypt)
    assert s.encrypted == encrypted
    ix = _ix(s, st)
    ix._load_photo()
    # 1.2.0 opens it: the same identity, every vector kept and searched, nothing to look at again
    assert _count(s, "pvecs") == 5 and s.meta("pvec_model") == "siglip2-base#2" and ix.pindex.n == 5
    assert not s.meta("pvec_next_model") and ix.photo_model_next is None
    ix._photo_vectors()
    assert made_with == []

    # the next re-pin of SigLIP 2's vision ("vectors": 3) is built beside the 1.0.1 vectors
    spec = dict(models.get("siglip2-base"), vectors=3)
    monkeypatch.setitem(models._BY_ID, "siglip2-base", spec)
    ix = _ix(s, st)
    ix._load_photo()
    assert s.meta("pvec_next_model") == "siglip2-base#3" and s.meta("pvec_model") == "siglip2-base#2"
    assert ix.pindex.n == 5 and ix.photo_text is ix.photo_text_next     # same model: one question encoder
    r = search.search(s, "a red car on a road", photo_text=ix.photo_text, pindex=ix.pindex,
                      photo_next=(ix.photo_text_next, ix.pindex_next))
    assert len(r["results"]) == 5 and all(any("picture" in w for w in x["why"]) for x in r["results"])
    ix._photo_vectors()
    assert s.meta("pvec_model") == "siglip2-base#3" and _count(s, "pvecs") == 5
    assert {v for (v,) in s.q("SELECT v FROM pvecs")} == {NEW} and ix.pindex.n == 5
    s.close()



# ---------- review fix round 1 ----------
class CrashingPool(SyncPhotoPool):
    def submit(self, fn, *args):
        f = cf.Future()
        try:
            f.set_result(fn(*args))
        except Exception as e:
            f.set_exception(e)
        return f


def test_a_photo_that_crashes_the_reader_during_a_rebuild_is_marked_in_the_new_set(tmp_path, monkeypatch):
    """Review: the "unreadable" mark went to pvecs: a working old vector was blanked, the new set never got a row,
    so the photo crashed the reader every pass and the set never swapped."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 3)
    for fid in ids:
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip-base")
    _patch(monkeypatch, [])
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", CrashingPool)
    bad = ids[1]

    def embed_photos(jobs, fast=False):
        if any(j[0] == bad for j in jobs):
            raise cf.BrokenExecutor("the reader died on this photo")
        return [(fid, mtime, NEW, None) for fid, _p, mtime, _d in jobs]
    monkeypatch.setattr(indexer.photo, "embed_photos", embed_photos)
    monkeypatch.setattr(indexer, "PHOTO_BATCH", 1)
    ix = _ix(s, S(photo_meaning=True, photo_model="siglip2-base"))
    ix._load_photo()
    ix._photo_one_by_one = True
    for _ in range(6):
        if s.meta("pvec_model") != "siglip-base":
            break
        assert s.one("SELECT v FROM pvecs WHERE file_id = ?", (bad,)) == OLD      # untouched until the swap
        ix._photo_vectors()
    assert s.meta("pvec_model") == "siglip2-base#2" and not s.meta("pvec_next_model")
    assert s.q("SELECT v, err FROM pvecs WHERE file_id = ?", (bad,)) == [(b"", "unreadable")]
    assert _count(s, "pvecs") == 2 and ix.pindex.n == 2
    s.close()


def test_one_photo_list_takes_each_photos_best_rank():
    assert search._one_photo_list([1, 2, 3], [4, 2]) == [1, 4, 2, 3]
    assert search._one_photo_list([1, 2], []) == [1, 2]


def test_a_photo_in_both_sets_counts_no_more_than_in_one(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    ids = _photos(s, 3)
    enc_old, enc_new = _Enc("siglip-base", 8, 0), _Enc("siglip2-base", 6, 0)
    on = lambda dim, i: _unit(np.r_[np.eye(dim)[i][:-1], 0.2])          # noqa: E731
    old_idx, new_idx = _Idx(8, "siglip-base"), _Idx(6, "siglip2-base")
    old_idx.add(ids, np.stack([on(8, 0), on(8, 1), on(8, 2)]))
    new_idx.add([ids[0]], np.stack([on(6, 0)]))                          # photo 1: first in both sets
    scores = []
    real = search.best_guess
    monkeypatch.setattr(search, "best_guess", lambda q, out, score, *a, **k: (scores.append(dict(score)),
                                                                              real(q, out, score, *a, **k))[1])
    ask = "a red car on a road"
    search.search(s, ask, photo_text=enc_old, pindex=old_idx)
    search.search(s, ask, photo_text=enc_old, pindex=old_idx, photo_next=(enc_new, new_idx))
    one, both = scores
    assert both[ids[0]] <= one[ids[0]]
    s.close()


def _repinned(monkeypatch, **kw):
    base = {k: v for k, v in models.get("siglip2-base").items() if k not in ("vectors", "text_changed_at")}
    monkeypatch.setitem(models._BY_ID, "siglip2-base", dict(base, **kw))


def test_a_repin_that_changed_the_text_side_keeps_the_old_rows_but_does_not_ask_them(tmp_path, monkeypatch):
    """"text_changed_at": 3: re-pin #3 changed the text half, so #2 vectors can't be asked with the text file on
    disk now. They stay (rows and tag) until the swap; only the new set answers meanwhile."""
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    for fid in _photos(s, 2):
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip2-base#2")
    _patch(monkeypatch, [])
    _repinned(monkeypatch, vectors=3, text_changed_at=3)
    ix = _ix(s, S(photo_meaning=True, photo_model="siglip2-base"))
    ix._load_photo()
    _run_rebuild_not_asking_the_old_set(s, ix, monkeypatch, "siglip2-base#2", "siglip2-base#3", 2)
    s.close()


def test_text_changed_at_belongs_to_the_version_it_describes(monkeypatch):
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    _repinned(monkeypatch, vectors=4, text_changed_at=3)
    assert models.old_vectors_askable("siglip2-base#3", "siglip2-base")      # #3 -> #4: vision only
    assert not models.old_vectors_askable("siglip2-base#2", "siglip2-base")  # #2 -> #4 crosses the text change
    assert not models.old_vectors_askable("siglip2-base", "siglip2-base")
    _repinned(monkeypatch, vectors=3)
    assert models.old_vectors_askable("siglip2-base#2", "siglip2-base")      # no marker: vision only
    assert models.old_vectors_askable("siglip-base", "siglip2-base")
    assert not models.old_vectors_askable("gone-model#1", "siglip2-base")


def test_a_later_vision_only_repin_still_asks_the_old_set(tmp_path, monkeypatch):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    for fid in _photos(s, 2):
        s.set_photo_vector(fid, 1.0, OLD)
    s.set_meta("pvec_model", "siglip2-base#3")
    _patch(monkeypatch, [])
    _repinned(monkeypatch, vectors=4, text_changed_at=3)
    ix = _ix(s, S(photo_meaning=True, photo_model="siglip2-base"))
    ix._load_photo()
    assert ix.pindex.n == 2 and ix.photo_old_answers is True and s.meta("pvec_next_model") == "siglip2-base#4"
    s.close()


def test_the_note_says_when_the_old_results_cant_answer(tmp_path, monkeypatch):
    from nobadfind import api as api_mod, settings
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings.Settings(str(tmp_path / "s.json"))
    st.update({"photo_meaning": True, "photo_model": "siglip2-base"})

    class Ix:
        embedder = None
        photo_text = None
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ())
        drive_list = []
        photo_model = photo_model_next = "siglip2-base"
        photo_old_answers = False

        def roots(self, drives):
            return []
    a = api_mod.Api(s, st, Ix(), None)
    monkeypatch.setattr(api_mod.models, "ready", lambda mid, d=None: True)
    a._totals = (0.0, None, {"photos": (11033, 11033 - 4210)})
    n = a.search("black shirt image")["needs"][0]
    assert n["text"] == ("Looking at your photos again with SigLIP 2: 4,210 of 11,033; "
                         "until then only those photos can be found by what is in them")
    s.close()
