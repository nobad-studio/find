import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _never_the_real_data_folder(tmp_path_factory, monkeypatch):
    """Every test works in a temp data folder: code that falls back to the module-level data dir (the contract
    test's Api did, and downloaded a model into the user's real folder) lands in a throwaway one instead."""
    from nobadfind import const, models, photo, update
    d = str(tmp_path_factory.mktemp("nf-data"))
    for mod in (const, models, photo, update):
        if hasattr(mod, "DATA_DIR"):
            monkeypatch.setattr(mod, "DATA_DIR", d)
    monkeypatch.setattr(photo, "PHOTO_DIR", os.path.join(d, "photo-model"))
    monkeypatch.setattr(const, "MODEL_DIR", os.path.join(d, "model"))
    return d


def _no_window(*a, **k):
    raise OSError("tests never open a window")


@pytest.fixture(autouse=True)
def _never_a_window(monkeypatch):
    """No test opens File Explorer or any program. A test that checks these patches them itself (its own
    monkeypatch runs after this one)."""
    from nobadfind import api
    monkeypatch.setattr(api, "open_folder", _no_window)
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", _no_window)
    real_popen = subprocess.Popen

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **k):
            first = args if isinstance(args, str) else (args[0] if args else "")
            if os.path.basename(str(first)).lower().split(" ")[0] in ("explorer.exe", "explorer"):
                _no_window()
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)


def _no_download(*a, **k):
    raise OSError("tests never download")


@pytest.fixture(autouse=True)
def _never_a_download(monkeypatch):
    """No test reaches the network: every download (embed._fetch_verified, update, runtimes) ends in urlopen. A test
    that needs one supplies its own fake urlopen."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", _no_download)
