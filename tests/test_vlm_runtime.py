"""The llama.cpp runtime download (vlm/runtime.py): only the pinned DLLs come out of the zip, each SHA-256 checked.

Never the network: a synthetic zip in tmp_path, handed over by a fake embed._fetch_verified."""
import hashlib
import io
import os
import shutil
import warnings
import zipfile

import pytest

from nobadfind import models
from nobadfind.vlm import runtime

GOOD = {"ggml.dll": b"ggml" * 100, "llama.dll": b"llama" * 300, "ggml-cpu-x64.dll": b"cpu" * 50}


def _pin(blobs):
    return {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in blobs.items()}


def _zip(members):
    """members: [(name, bytes)], written in order (duplicates allowed)."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                    # zipfile warns on a duplicate name
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in members:
                z.writestr(zipfile.ZipInfo(name), data)
    return buf.getvalue()


@pytest.fixture
def entry(monkeypatch):
    """A test runtime entry in the catalog; returns a function setting its zip (bytes) and its pinned DLLs."""
    m = dict(models.get("llama-cpu"))
    state = {}

    def setup(zip_bytes, pins=None):
        state["zip"] = zip_bytes
        m["files"] = {"zip": ("llama-test.zip", len(zip_bytes), hashlib.sha256(zip_bytes).hexdigest())}
        m["files_in_zip"] = dict(pins if pins is not None else _pin(GOOD))
        return m

    monkeypatch.setitem(models._BY_ID, "llama-cpu", m)
    calls = []

    def fake_fetch(url, dest, size, sha, name, progress=None, part=".part"):
        calls.append((url, dest, size, sha, name))
        assert (name, size, sha) == m["files"]["zip"] and url == m["url"]
        with open(dest, "wb") as f:
            f.write(state["zip"])
        if progress:
            progress(name, size, size)

    monkeypatch.setattr(runtime.embed, "_fetch_verified", fake_fetch)
    setup.calls = calls
    return setup


def _left(data_dir):
    root = os.path.join(data_dir, "runtime")
    return sorted(os.listdir(root)) if os.path.isdir(root) else []


def test_install_extracts_only_listed_files(tmp_path, entry):
    entry(_zip([("evil.exe", b"MZ evil"), ("..\\x.dll", b"x"), ("../y.dll", b"y"), ("/abs.dll", b"a"),
                ("sub/ggml.dll", b"nested"), ("ggml-rpc.dll", b"rpc"), ("sub/", b"")]
               + list(GOOD.items())))
    seen = []
    d = runtime.install("llama-cpu", str(tmp_path), lambda n, got, size: seen.append((got, size)))
    assert d == os.path.join(str(tmp_path), "runtime", "llama-cpu")
    assert sorted(os.listdir(d)) == sorted(GOOD)
    for n, b in GOOD.items():
        with open(os.path.join(d, n), "rb") as f:
            assert f.read() == b
    assert _left(str(tmp_path)) == ["llama-cpu"]           # no zip, no .part
    assert not os.path.exists(os.path.join(str(tmp_path), "x.dll"))
    assert not os.path.exists(os.path.join(str(tmp_path), "runtime", "x.dll"))
    assert seen and runtime.ready("llama-cpu", str(tmp_path))


def test_install_rejects_a_dll_with_a_wrong_sha(tmp_path, entry):
    bad = dict(GOOD, **{"llama.dll": b"LLAMA" * 300})       # same size, other bytes
    entry(_zip(list(bad.items())))
    with pytest.raises(IOError, match="llama.dll"):
        runtime.install("llama-cpu", str(tmp_path), None)
    assert _left(str(tmp_path)) == []                      # nothing left behind: no folder, no .part, no zip
    assert not runtime.ready("llama-cpu", str(tmp_path))


def test_install_rejects_a_bigger_dll_a_missing_dll_and_a_duplicate(tmp_path, entry):
    for members in ([("ggml.dll", GOOD["ggml.dll"] + b"!"), ("llama.dll", GOOD["llama.dll"]),
                     ("ggml-cpu-x64.dll", GOOD["ggml-cpu-x64.dll"])],
                    [("ggml.dll", GOOD["ggml.dll"]), ("llama.dll", GOOD["llama.dll"])],
                    list(GOOD.items()) + [("LLAMA.DLL", GOOD["llama.dll"])]):
        entry(_zip(members))
        with pytest.raises(IOError):
            runtime.install("llama-cpu", str(tmp_path), None)
        assert _left(str(tmp_path)) == []


def test_install_matches_names_without_case_and_replaces_an_old_folder(tmp_path, entry):
    entry(_zip([("GGML.DLL", GOOD["ggml.dll"]), ("llama.dll", GOOD["llama.dll"]),
                ("ggml-cpu-x64.dll", GOOD["ggml-cpu-x64.dll"])]))
    old = os.path.join(str(tmp_path), "runtime", "llama-cpu")
    os.makedirs(old)
    with open(os.path.join(old, "planted.dll"), "wb") as f:
        f.write(b"old")
    os.makedirs(old + ".part")                             # a stale one from a crash
    d = runtime.install("llama-cpu", str(tmp_path), None)
    assert sorted(os.listdir(d)) == sorted(GOOD)           # stored under the pinned name; the old folder is gone
    assert _left(str(tmp_path)) == ["llama-cpu"]


def test_install_skips_the_download_when_every_dll_is_already_there(tmp_path, entry):
    entry(_zip(list(GOOD.items())))
    runtime.install("llama-cpu", str(tmp_path), None)
    assert len(entry.calls) == 1
    runtime.install("llama-cpu", str(tmp_path), None)
    assert len(entry.calls) == 1
    with open(os.path.join(str(tmp_path), "runtime", "llama-cpu", "llama.dll"), "r+b") as f:
        f.write(b"X")                                      # same size, changed: downloaded again
    runtime.install("llama-cpu", str(tmp_path), None)
    assert len(entry.calls) == 2


def test_install_refuses_what_is_not_a_runtime(tmp_path, entry):
    with pytest.raises(ValueError):
        runtime.install("minilm-l6-v2", str(tmp_path), None)
    with pytest.raises(ValueError):
        runtime.install("nope", str(tmp_path), None)
    entry(_zip(list(GOOD.items())), pins=dict(_pin(GOOD), **{"..\\evil.dll": (1, "0" * 64)}))
    with pytest.raises(ValueError):
        runtime.install("llama-cpu", str(tmp_path), None)   # a pinned name with a path in it is never trusted


def test_ready_needs_every_dll_at_its_size(tmp_path, entry):
    entry(_zip(list(GOOD.items())))
    assert not runtime.ready("llama-cpu", str(tmp_path))
    d = runtime.install("llama-cpu", str(tmp_path), None)
    assert runtime.ready("llama-cpu", str(tmp_path))
    with open(os.path.join(d, "ggml.dll"), "ab") as f:
        f.write(b"!")
    assert not runtime.ready("llama-cpu", str(tmp_path))
    shutil.rmtree(d)
    os.makedirs(d)
    for n, b in list(GOOD.items())[1:]:
        with open(os.path.join(d, n), "wb") as f:
            f.write(b)
    assert not runtime.ready("llama-cpu", str(tmp_path))
    assert not runtime.ready("minilm-l6-v2", str(tmp_path))


def test_plain_names_only():
    assert runtime._plain("llama.dll") and runtime._plain("ggml-cpu-x64.dll")
    for n in ("a\\b.dll", "..\\x.dll", "../x.dll", "C:x.dll", "/x.dll", "x.dll ", "x.dll.", ".x.dll", "a/b.dll",
              "x.exe", "x.dll\x00", "x.dll:ads", None):
        assert not runtime._plain(n), n


def test_the_real_pins_are_plain_dll_names():
    for rid in ("llama-cpu", "llama-vulkan"):
        m = models.get(rid)
        assert m["url"].startswith("https://github.com/ggml-org/llama.cpp/releases/download/")
        assert all(runtime._plain(n) and n.endswith(".dll") for n in m["files_in_zip"])
        assert "ggml-rpc.dll" not in m["files_in_zip"]


def test_only_the_dlls_find_loads_are_pinned():
    """I2: no llama.cpp program bodies (llama-server-impl, llama-cli-impl, llama-common, the other *-impl tools) are
    kept on disk: only ggml, ggml-base, the CPU variants, ggml-vulkan (Vulkan zip), libomp, llama and mtmd."""
    for rid, extra in (("llama-cpu", set()), ("llama-vulkan", {"ggml-vulkan.dll"})):
        z = set(models.get(rid)["files_in_zip"])
        cpu = {n for n in z if n.startswith("ggml-cpu-")}
        assert len(cpu) >= 10, rid                              # every CPU variant of the release
        assert z - cpu == {"ggml.dll", "ggml-base.dll", "libomp.dll", "llama.dll", "mtmd.dll"} | extra, rid
        assert not any(n.endswith("-impl.dll") or n == "llama-common.dll" for n in z), rid
