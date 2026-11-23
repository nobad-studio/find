import importlib
import inspect
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _real_dir():
    """The data folder the product would use here, noted at import so another plugin's patch can't change it."""
    from nobadfind import const
    return const.DATA_DIR


REAL_DATA_DIR = _real_dir()


def _moved(value, d):
    """value with the real data folder at its front replaced by d, else None."""
    if isinstance(value, str) and (value == REAL_DATA_DIR or value.startswith(REAL_DATA_DIR + os.sep)):
        return d + value[len(REAL_DATA_DIR):]
    return None


def _functions(mod):
    for v in list(vars(mod).values()):
        if inspect.isfunction(v):
            yield v
        elif inspect.isclass(v) and v.__module__ == mod.__name__:
            for m in list(vars(v).values()):
                m = getattr(m, "__func__", m)
                if inspect.isfunction(m):
                    yield m


@pytest.fixture(autouse=True)
def _never_the_real_data_folder(tmp_path_factory, monkeypatch):
    """Every test works in a temp data folder. Code that falls back to a data-dir name (the contract test's Api
    did, and downloaded a model into the user's real folder) lands in a throwaway one instead: every module-level
    name of nobadfind holding the real folder or a path inside it (DATA_DIR, MODEL_DIR, PHOTO_DIR, DB_PATH...)
    and every function default built from one (`download_model(model_dir=MODEL_DIR)`, `ready(mid, data_dir=...)`,
    `Updater(data_dir=...)`) is moved into it, and put back after the test."""
    for name in ("api", "embed", "indexer", "models", "photo", "scope", "update", "vlm.runtime"):
        importlib.import_module("nobadfind." + name)           # so their names and defaults are moved too
    d = str(tmp_path_factory.mktemp("nf-data"))
    undo = []
    for name, mod in list(sys.modules.items()):
        if not name.startswith("nobadfind") or mod is None:
            continue
        for attr, value in list(vars(mod).items()):
            new = _moved(value, d)
            if new is not None:
                monkeypatch.setattr(mod, attr, new)
        for fn in _functions(mod):
            if fn.__defaults__ and any(_moved(v, d) for v in fn.__defaults__):
                undo.append((fn, "__defaults__", fn.__defaults__))
                fn.__defaults__ = tuple(_moved(v, d) or v for v in fn.__defaults__)
            if fn.__kwdefaults__ and any(_moved(v, d) for v in fn.__kwdefaults__.values()):
                undo.append((fn, "__kwdefaults__", dict(fn.__kwdefaults__)))
                fn.__kwdefaults__ = {k: _moved(v, d) or v for k, v in fn.__kwdefaults__.items()}
    yield d
    for fn, attr, old in undo:
        setattr(fn, attr, old)


def _no_window(*a, **k):
    raise OSError("tests never open a window")


@pytest.fixture(autouse=True)
def _never_a_window(monkeypatch):
    """No test opens File Explorer or any program. A test that checks these patches them itself (its own
    monkeypatch runs after this one)."""
    from nobadfind import api
    from nobadfind import turbo, winapi
    monkeypatch.setattr(api, "open_folder", _no_window)
    for mod, name in ((winapi, "run_elevated"), (turbo, "start_elevated")):       # UAC: never from a test
        monkeypatch.setattr(mod, name, _no_window)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", _no_window)
    real_popen = subprocess.Popen

    def check(args, k):
        if k.get("creationflags", 0) & winapi.CREATE_BREAKAWAY_FROM_JOB:      # start_outside_job, open_outside_job
            _no_window()
        first = args if isinstance(args, str) else (args[0] if args else "")
        if os.path.basename(str(first)).lower().split(" ")[0] in ("explorer.exe", "explorer"):
            _no_window()

    if isinstance(real_popen, type):
        class GuardedPopen(real_popen):
            def __init__(self, args, *a, **k):
                check(args, k)
                super().__init__(args, *a, **k)
    else:                                   # another plugin already replaced Popen with a function
        def GuardedPopen(args, *a, **k):
            check(args, k)
            return real_popen(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


def _no_download(*a, **k):
    raise OSError("tests never download")


@pytest.fixture(autouse=True)
def _never_a_download(monkeypatch):
    """No test reaches the network: every download (embed._fetch_verified, update, runtimes) ends in urlopen. A test
    that needs one supplies its own fake urlopen."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _no_download)
