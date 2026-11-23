"""The guard in conftest: no test touches the user's real data folder, the network or a window."""
import os

import pytest

from nobadfind import api as api_mod, const, models

REAL = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "NOBAD", "Find")


def _norm(p):
    return os.path.normcase(os.path.abspath(p))


def test_no_test_touches_the_real_data_folder():
    for d in (const.DATA_DIR, models.DATA_DIR):
        assert _norm(d) != _norm(REAL) and not _norm(d).startswith(_norm(REAL) + os.sep)
    a = api_mod.Api.__new__(api_mod.Api)
    assert _norm(a._mdir()) != _norm(REAL)


def test_a_bare_api_cannot_open_a_window_or_download():
    a = api_mod.Api.__new__(api_mod.Api)
    with pytest.raises(OSError, match="never open a window"):
        api_mod.open_folder(a._mdir())
    with pytest.raises(OSError, match="never open a window"):
        os.startfile(a._mdir())
    from nobadfind import embed
    with pytest.raises(OSError, match="never download"):          # the real downloader hits the guard
        embed._fetch_verified("https://example.invalid/x", os.path.join(a._mdir(), "x"), 1, "0", "x")
    import urllib.request
    with pytest.raises(OSError, match="never download"):
        urllib.request.urlopen("https://example.invalid/")
