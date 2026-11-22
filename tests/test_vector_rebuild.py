"""Switching the text (or photo) model: new vectors are built next to the old ones, the old ones stay searchable,
and they swap in one transaction once complete. Vectors from two models are never searched together."""
import numpy as np
import pytest

from nobadfind import embed, indexer, models
from nobadfind.store import Store


def blob(x, dim=4):
    return embed.to_blob(np.full(dim, x, np.float32))


def _store(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    s.upsert_files([("C:/p/a.txt", "a.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1),
                    ("C:/p/b.txt", "b.txt", "C:/p", ".txt", "text", 10, 1.0, 1.0, 1)])
    for fid in (1, 2):
        s.set_text(fid, 1.0, [f"body {fid}"], None)
    return s


def test_next_vectors_live_beside_the_current_ones_and_swap_in(tmp_path):
    s = _store(tmp_path)
    chunks = [r[0] for r in s.chunks_without_vectors(10)]
    s.add_vectors([(c, blob(1)) for c in chunks])
    s.add_name_vectors([(1, blob(1)), (2, blob(1))])
    assert s.chunks_without_vectors(10) == []
    assert len(s.chunks_without_vectors(10, next=True)) == 2          # the new model has none yet
    s.add_vectors([(chunks[0], blob(2, 8))], next=True)
    assert len(s.chunks_without_vectors(10, next=True)) == 1
    assert s.count_chunks_without_vectors(next=True) == 1
    s.add_vectors([(chunks[1], blob(2, 8))], next=True)
    s.add_name_vectors([(1, blob(2, 8)), (2, blob(2, 8))], next=True)
    s.swap_vectors()
    assert {len(v) for _k, v in s.q("SELECT chunk_id, v FROM vecs")} == {16}      # 8 float16 = the new model's
    assert s.q("SELECT count(*) FROM vecs_next")[0][0] == 0 and s.q("SELECT count(*) FROM nvecs_next")[0][0] == 0


def test_deleted_files_and_chunks_leave_the_next_tables_too(tmp_path):
    s = _store(tmp_path)
    c = s.chunks_without_vectors(10, next=True)[0][0]
    s.add_vectors([(c, blob(3))], next=True)
    s.add_name_vectors([(1, blob(3))], next=True)
    s.set_text(1, 2.0, ["changed"], None)                 # the chunk is replaced
    s.remove_paths(["C:/p/a.txt"])
    assert s.q("SELECT count(*) FROM vecs_next")[0][0] == 0 and s.q("SELECT count(*) FROM nvecs_next")[0][0] == 0


def test_vector_model_of_an_old_index_is_minilm(tmp_path):
    """Indexes from 0.7.0 have MiniLM vectors and no model id."""
    s = _store(tmp_path)
    assert indexer.vector_model(s) is None                 # nothing made yet
    s.add_name_vectors([(1, blob(1))])
    assert indexer.vector_model(s) == "minilm-l6-v2"
    s.set_meta("vec_model", "bge-small-en-v1.5")
    assert indexer.vector_model(s) == "bge-small-en-v1.5"


def test_vector_index_takes_the_models_size(tmp_path):
    vi = embed.VectorIndex()
    vi.reset(768, "bge-base-en-v1.5")
    assert vi.dim == 768 and vi.model == "bge-base-en-v1.5" and vi.n == 0
    assert models.get("bge-base-en-v1.5")["dim"] == 768


# ---------- the indexer switches models in the background ----------
class Stand:
    """A stand-in model: every text -> the same unit vector of its model's size."""
    def __init__(self, mid, dim):
        self.model_id, self.dim = mid, dim

    def encode(self, texts):
        v = np.zeros((len(texts), self.dim), np.float32)
        v[:, 0] = 1
        return v


class S(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def _ix(tmp_path, monkeypatch, text_model):
    s = _store(tmp_path)
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    st = S(semantic=True, text_model=text_model, content=True)
    vi = embed.VectorIndex()
    ix = indexer.Indexer(s, st, vindex=vi)
    ix.make_embedder = lambda mid, query=False: Stand(mid, models.get(mid)["dim"])
    ix.vectors_in_process = True                          # stand-in models: no meaning worker process
    ix.status["plan"] = {}
    return ix, s, st, vi


def test_a_fresh_index_uses_the_chosen_model_at_once(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "bge-base-en-v1.5")
    ix._load_embedder()
    ix._make_vectors()
    assert ix.text_model == "bge-base-en-v1.5" == s.meta("vec_model") == vi.model
    assert vi.dim == 768 and vi.n > 0 and ix.embedder.model_id == "bge-base-en-v1.5"


def test_switching_rebuilds_beside_the_old_vectors_then_swaps(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "minilm-l6-v2")
    ix._load_embedder()
    ix._make_vectors()
    assert s.meta("vec_model") == "minilm-l6-v2" and vi.dim == 384
    st["text_model"] = "bge-base-en-v1.5"                 # the user picks another model
    seen = []
    real = s.add_vectors

    def watch(rows, next=False, **kw):
        seen.append((next, vi.model, s.meta("vec_model")))        # while rebuilding, search keeps the old set
        return real(rows, next=next, **kw)
    s.add_vectors = watch
    ix._make_vectors()
    assert (True, "minilm-l6-v2", "minilm-l6-v2") in seen
    assert s.meta("vec_model") == "bge-base-en-v1.5" and vi.model == "bge-base-en-v1.5" and vi.dim == 768
    assert ix.embedder.model_id == "bge-base-en-v1.5"
    assert {len(v) for (v,) in s.q("SELECT v FROM vecs")} == {768 * 2}
    assert any("BGE base" in a for a in ix._notes)


def test_a_switch_away_from_an_empty_set_uses_the_new_model_at_once(tmp_path, monkeypatch):
    """Found on the reference PC (0.9.3): the MiniLM vectors had been dropped (the vector format changed) while a
    switch to GTE small was pending, so search kept the empty MiniLM set until all 1.4 million GTE vectors were
    made: no meaning results for days. With nothing to keep searchable, the new model takes over at once and
    its vectors count as they're made."""
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "bge-base-en-v1.5")
    s.set_meta("vec_model", "minilm-l6-v2")
    s.set_meta("vec_version", embed.VEC_VERSION)
    s.set_meta("vec_model_next", "bge-base-en-v1.5")
    s.add_name_vectors([(1, blob(1, 768))], next=True)     # part of the rebuild was done
    to_next = []
    real = s.add_vectors
    s.add_vectors = lambda rows, next=False, **kw: (to_next.append(next), real(rows, next=next, **kw))[1]
    ix._load_embedder()
    ix._make_vectors()
    assert True not in to_next                             # nothing waits beside an empty set
    assert s.meta("vec_model") == "bge-base-en-v1.5" and not s.meta("vec_model_next")
    assert ix.text_model == "bge-base-en-v1.5" == vi.model and ix.embedder.model_id == "bge-base-en-v1.5"
    ix._make_vectors()                                     # the next round fills the searched set itself
    assert s.count_chunks_without_vectors() == 0 and s.q("SELECT count(*) FROM vecs_next")[0][0] == 0
    assert {len(v) for (v,) in s.q("SELECT v FROM vecs")} == {768 * 2}
    assert ix.status.get("rebuild") is None


def test_a_new_vector_format_also_drops_a_half_built_next_set(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "bge-base-en-v1.5")
    s.set_meta("vec_model", "minilm-l6-v2")
    s.set_meta("vec_version", "1")
    s.set_meta("vec_model_next", "bge-base-en-v1.5")
    s.add_name_vectors([(1, blob(1, 768))], next=True)     # made the old way
    ix._load_embedder()
    assert s.q("SELECT count(*) FROM nvecs_next")[0][0] == 0 and not s.meta("vec_model_next")


def test_a_model_not_downloaded_yet_changes_nothing(tmp_path, monkeypatch):
    ix, s, st, vi = _ix(tmp_path, monkeypatch, "minilm-l6-v2")
    ix._load_embedder()
    ix._make_vectors()
    st["text_model"] = "bge-base-en-v1.5"
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: mid == "minilm-l6-v2")
    ix._make_vectors()
    assert s.meta("vec_model") == "minilm-l6-v2" and s.q("SELECT count(*) FROM vecs_next")[0][0] == 0


# ---------- photos: one model's vectors at a time ----------
def test_photo_model_switch_starts_the_photo_vectors_again(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.set_photo_vector(1, 1.0, embed.to_blob(np.ones(768)), None)
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": ("enc", model_dir, style))
    st = S(photo_meaning=True, photo_model="siglip-base")
    ix = indexer.Indexer(s, st, vindex=embed.VectorIndex())
    ix._load_photo()
    assert ix.photo_model == "siglip-base" and s.meta("pvec_model") == "siglip-base" and ix.pindex.n == 1
    assert ix.photo_text.model_id == "siglip-base"
    st["photo_model"] = "siglip2-base"
    ix._load_photo()
    assert ix.photo_model == "siglip2-base" and ix.pindex.model == "siglip2-base"
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 0             # SigLIP and SigLIP 2 are never compared
    assert ix.photo_text._factory() == ("enc", models.model_dir("siglip2-base"), "siglip2")


def test_siglip2_questions_are_lower_case_with_end_of_text_and_padding():
    from nobadfind import photo

    class Tok:
        def encode(self, text):
            class E:
                ids = [7, 8, 1] + [0] * 61
            Tok.seen = text
            return E()
    ids = photo.question_ids(Tok(), "Sunset over THE Sea", "siglip2")
    assert Tok.seen == "sunset over the sea" and len(ids) == 64 and ids[:3] == [7, 8, 1] and ids[3] == 0


def test_the_vision_session_follows_the_model_folder(monkeypatch, tmp_path):
    """Review H2: the worker cached one vision session and ignored a new model's folder."""
    from nobadfind import photo
    import onnxruntime as ort
    made = []
    monkeypatch.setattr(ort, "InferenceSession", lambda path, opts, providers: made.append(path) or object())
    monkeypatch.setattr(photo, "_vision", {})
    photo._vision_session(str(tmp_path / "a"))
    photo._vision_session(str(tmp_path / "a"))
    photo._vision_session(str(tmp_path / "b"))
    assert [p.split("\\")[-2] if "\\" in p else p.split("/")[-2] for p in made] == ["a", "b"]


class SyncPhotoPool:
    def __init__(self, *a, **k):
        self._processes = {}

    def submit(self, fn, *args):
        import concurrent.futures as cf
        f = cf.Future()
        f.set_result(fn(*args))
        return f

    def shutdown(self, **k):
        pass


def test_a_photo_pass_running_through_a_switch_writes_nothing_under_the_new_id(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.upsert_files([(f"C:/p/img{i}.jpg", f"img{i}.jpg", "C:/p", ".jpg", "image", 50000, 1.0, 1.0, 1) for i in range(20)])
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": object())
    st = S(photo_meaning=True, photo_model="siglip-base")
    ix = indexer.Indexer(s, st, vindex=embed.VectorIndex())
    ix.status["plan"] = {}
    ix._load_photo()
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", SyncPhotoPool)
    made_with = []

    def embed_photos(jobs, fast=False):
        made_with.append(jobs[0][3])
        if len(made_with) == 1:                            # the user switches while this batch is being made
            st["photo_model"] = "siglip2-base"
            ix._load_photo()
        return [(fid, mtime, embed.to_blob(np.ones(768)), None) for fid, _p, mtime, _d in jobs]
    monkeypatch.setattr(indexer.photo, "embed_photos", embed_photos)
    ix._photo_vectors()
    assert s.meta("pvec_model") == models.vector_tag("siglip2-base")
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 0      # the old model's batch was thrown away
    ix._photo_vectors()                                      # the next pass: the new model's folder
    assert made_with[-1] == models.model_dir("siglip2-base")
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 20


# ---------- SigLIP 2 re-pin (2026-11-22): fp16 vision; vectors from the old 8-bit vision are rebuilt ----------
def test_siglip2_vision_is_the_fp16_file_and_text_stays_8bit():
    m = models.get("siglip2-base")
    assert m["files"]["vision.onnx"][0] == "onnx/vision_model_fp16.onnx"
    assert m["files"]["vision.onnx"][1] == 186039516
    assert m["files"]["text.onnx"][0] == "onnx/text_model_quantized.onnx"
    assert models.PHOTO_CHOICE["balanced"] == "siglip-base" and models.DEFAULT_PHOTO == "siglip-base"


def test_vectors_made_by_the_8bit_siglip2_vision_are_made_again(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.set_photo_vector(1, 1.0, embed.to_blob(np.ones(768)), None)
    s.set_meta("pvec_model", "siglip2-base")                     # made with the 8-bit vision file
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": object())
    ix = indexer.Indexer(s, S(photo_meaning=True, photo_model="siglip2-base"), vindex=embed.VectorIndex())
    ix._load_photo()
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 0
    assert s.meta("pvec_model") == models.vector_tag("siglip2-base") == "siglip2-base#2"
    assert ix.photo_model == "siglip2-base" and ix.pindex.model == "siglip2-base"
    ix._load_photo()                                             # loading again keeps the new vectors' tag
    assert s.meta("pvec_model") == "siglip2-base#2"


def test_siglip_base_vectors_are_kept_by_the_repin(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.set_photo_vector(1, 1.0, embed.to_blob(np.ones(768)), None)
    s.set_meta("pvec_model", "siglip-base")
    monkeypatch.setattr(models, "ready", lambda mid, data_dir=None: True)
    monkeypatch.setattr(indexer.photo, "TextEncoder", lambda model_dir, style="siglip": object())
    ix = indexer.Indexer(s, S(photo_meaning=True, photo_model="siglip-base"), vindex=embed.VectorIndex())
    ix._load_photo()
    assert s.q("SELECT count(*) FROM pvecs")[0][0] == 1 and s.meta("pvec_model") == "siglip-base"


def test_a_graph_the_full_optimizer_cant_load_is_opened_with_basic_optimization(monkeypatch):
    """fp16 exports fail ONNX Runtime 1.27's full optimizer (GetIndexFromName); basic loads them."""
    from nobadfind import photo
    import onnxruntime as ort
    levels = []

    def session(path, opts, providers):
        levels.append(opts.graph_optimization_level)
        if opts.graph_optimization_level != ort.GraphOptimizationLevel.ORT_ENABLE_BASIC:
            raise RuntimeError("[ONNXRuntimeError] : 1 : FAIL : graph_utils.cc GetIndexFromName")
        return "session"
    monkeypatch.setattr(ort, "InferenceSession", session)
    opts = ort.SessionOptions()
    assert photo.open_session("x.onnx", opts) == "session"
    assert levels[-1] == ort.GraphOptimizationLevel.ORT_ENABLE_BASIC and len(levels) == 2
    assert opts.enable_cpu_mem_arena is False                # measured: the arena grew to 1.3 GB on fp16 vision
    levels.clear()
    monkeypatch.setattr(ort, "InferenceSession", lambda path, opts, providers: levels.append(1) or "ok")
    assert photo.open_session("y.onnx", ort.SessionOptions()) == "ok" and levels == [1]   # no retry when it loads


def test_other_load_errors_are_not_hidden_by_the_fallback(monkeypatch):
    from nobadfind import photo
    import onnxruntime as ort

    def session(path, opts, providers):
        raise RuntimeError("NO_SUCHFILE: file doesn't exist")
    monkeypatch.setattr(ort, "InferenceSession", session)
    with pytest.raises(RuntimeError, match="NO_SUCHFILE"):
        photo.open_session("missing.onnx", ort.SessionOptions())
