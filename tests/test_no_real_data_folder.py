"""The guard in conftest: no test touches the user's real data folder, the network or a window."""
import inspect
import os
import time

import pytest

from nobadfind import api as api_mod, const, embed, models, photo, scope, update
from nobadfind.vlm import runtime

REAL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")


def _inside_real(p):
    p = os.path.normcase(os.path.abspath(str(p)))
    r = os.path.normcase(os.path.abspath(REAL))
    return p == r or p.startswith(r + os.sep)


def test_no_test_touches_the_real_data_folder():
    names = [const.DATA_DIR, const.MODEL_DIR, const.DB_PATH, const.KEY_PATH, const.SETTINGS_PATH, const.LOG_PATH,
             models.DATA_DIR, photo.DATA_DIR, photo.PHOTO_DIR, update.DATA_DIR, scope.DATA_DIR, embed.MODEL_DIR,
             api_mod.Api.__new__(api_mod.Api)._mdir()]
    assert not [n for n in names if _inside_real(n)]


def test_the_import_bound_defaults_are_moved_too():
    defaults = [inspect.signature(f).parameters[p].default for f, p in (
        (embed.download_model, "model_dir"), (embed.model_ready, "model_dir"), (embed.Embedder.__init__, "model_dir"),
        (photo.download_model, "model_dir"), (photo.model_ready, "model_dir"), (photo.TextEncoder.__init__, "model_dir"),
        (update.Updater.__init__, "data_dir"), (models.model_dir, "data_dir"), (models.ready, "data_dir"),
        (models.missing_mb, "data_dir"), (models.runtime_for, "data_dir"), (models.talk_runtime, "data_dir"),
        (runtime.ready, "data_dir"))]
    assert not [d for d in defaults if _inside_real(d)]
    assert not _inside_real(models.model_dir("multilingual-e5-small"))


def test_the_two_downloads_create_nothing_under_the_real_folder(monkeypatch):
    class S:
        def get(self, key):
            return True

        def update(self, changes):
            pass

    made = []
    monkeypatch.setattr(os, "makedirs", lambda p, *a, **k: made.append(str(p)))     # records, creates nothing
    a = api_mod.Api.__new__(api_mod.Api)
    a._settings, a._indexer = S(), None
    a._model = {"state": "missing", "got": 0, "size": 0, "error": ""}
    a._photo_model = dict(a._model)
    assert a.download_model()["ok"] and a.download_photo_model()["ok"]
    for _ in range(100):                                    # the two worker threads finish: the guard stops them
        if a._model["state"] == "missing" and a._photo_model["state"] == "missing" and a._model["error"] \
                and a._photo_model["error"]:
            break
        time.sleep(0.05)
    assert made and not [m for m in made if _inside_real(m)]


def test_a_bare_api_cannot_open_a_window_or_download():
    a = api_mod.Api.__new__(api_mod.Api)
    with pytest.raises(OSError, match="never open a window"):
        api_mod.open_folder(a._mdir())
    with pytest.raises(OSError, match="never open a window"):
        os.startfile(a._mdir())
    from nobadfind import turbo, winapi
    for fn in (winapi.start_outside_job, winapi.open_outside_job, winapi.run_elevated, turbo.start_elevated):
        with pytest.raises(OSError, match="never open a window"):
            fn(["C:/x.exe"] if fn is not winapi.open_outside_job else "C:/x.txt")
    with pytest.raises(OSError, match="never download"):          # the real downloader hits the guard
        embed._fetch_verified("https://example.invalid/x", os.path.join(a._mdir(), "x"), 1, "0", "x")
    import urllib.request
    with pytest.raises(OSError, match="never download"):
        urllib.request.urlopen("https://example.invalid/")
