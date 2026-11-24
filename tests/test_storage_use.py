"""storage_use (contract): what NOBAD Find keeps on disk, measured from file sizes in a fake data folder."""
import os

import pytest

from nobadfind import api as api_mod, models

from test_api_status import make

MB = 1048576


def _file(path, size):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.truncate(size)


@pytest.fixture
def a(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "DATA_DIR", str(tmp_path))
    a, s = make(tmp_path)
    a._models_dir = str(tmp_path)
    yield a
    s.close()


def test_storage_use_measures_the_files_on_disk(a, tmp_path):
    _file(str(tmp_path / "i.db"), 10 * MB)
    a._store.db.commit()
    _file(str(tmp_path / "i.db-wal"), 2 * MB)         # whatever SQLite left, the file is now exactly 2 MB
    _file(str(models.model_dir("minilm-l6-v2", str(tmp_path)) + "/m.onnx"), 23 * MB)
    _file(str(models.model_dir("siglip-base", str(tmp_path)) + "/sub/v.onnx"), 5 * MB)
    _file(str(models.model_dir("llama-cpu", str(tmp_path)) + "/ggml.dll"), 4 * MB)
    _file(str(tmp_path / "tmp" / "browser-x" / "History"), 1 * MB)
    r = a.storage_use()
    assert set(r) == {"index_mb", "wal_mb", "models", "runtime_mb", "tmp_mb", "total_mb"}
    assert r["wal_mb"] == 2 and r["runtime_mb"] == 4 and r["tmp_mb"] == 1
    assert r["index_mb"] >= 10
    assert {m["id"]: m["mb"] for m in r["models"]} == {"minilm-l6-v2": 23, "siglip-base": 5}
    assert r["total_mb"] == pytest.approx(r["index_mb"] + r["wal_mb"] + 28 + r["runtime_mb"] + r["tmp_mb"], abs=0.1)


def test_storage_use_on_an_empty_folder_is_zeros_and_lists_only_models_on_disk(a, tmp_path):
    r = a.storage_use()
    assert r["runtime_mb"] == 0 and r["tmp_mb"] == 0 and r["models"] == []
    assert r["total_mb"] == pytest.approx(r["index_mb"] + r["wal_mb"], abs=0.1)


def test_storage_use_never_looks_outside_the_data_folder(a, tmp_path, monkeypatch):
    seen = []
    real = os.walk
    monkeypatch.setattr(api_mod.os, "walk", lambda p, *k, **kw: (seen.append(p), real(p, *k, **kw))[1])
    a.storage_use()
    assert all(str(p).startswith(str(tmp_path)) for p in seen)
