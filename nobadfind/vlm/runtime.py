"""The llama.cpp runtime (talk about a photo): the pinned release zip, and ONLY its pinned DLLs unpacked.

The DLLs become code NOBAD Find loads, so nothing in the zip is trusted beyond its pins (models.CATALOG entries
llama-cpu / llama-vulkan, llama_pins.py):
  * the zip comes through embed._fetch_verified (HTTPS, exact size, SHA-256) from its GitHub release asset;
  * a member is unpacked only when its name IS one of the entry's `files_in_zip` (case-insensitive, Windows names):
    so never a directory, an absolute path, a path with `..` or any other folder, an .exe or an unlisted DLL;
    a listed name twice in the zip is refused;
  * each member is read at most to its pinned size and its SHA-256 checked while it is written;
  * everything goes to `<folder>.part`, every listed DLL must be there, then the folder is swapped in (rename);
  * on any failure the .part folder and the zip are deleted; the zip is deleted after a good install too.
"""
import hashlib
import os
import shutil
import zipfile

from .. import embed, models
from ..log import log

CHUNK = 1 << 16


def _entry(mid):
    m = models.get(mid) if isinstance(mid, str) else None
    if m is None or m.get("feature") != "runtime":
        raise ValueError(f"not a llama.cpp runtime: {mid!r}")
    for n in m["files_in_zip"]:
        if not _plain(n):
            raise ValueError(f"runtime {mid}: pinned name {n!r} is not a plain .dll name")
    return m


def _plain(name, ext=".dll"):
    """A bare file name ending in `ext`: no folder, drive or `..`, nothing Windows would reinterpret (a leading or
    trailing dot or space, a reserved character)."""
    return (isinstance(name, str) and name.lower().endswith(ext) and name == name.strip(" .") and ".." not in name
            and not any(c in name for c in '/\\:*?"<>|') and all(ord(c) >= 32 for c in name))


def ready(mid, data_dir=models.DATA_DIR):
    """Every kept DLL on disk at its pinned size (their SHA-256 was checked when they were unpacked)."""
    m = models.get(mid) if isinstance(mid, str) else None
    return bool(m and m.get("feature") == "runtime" and models.ready(mid, data_dir))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def _verified(d, pins):
    """Every pinned DLL in `d` at its size and SHA-256."""
    for n, (size, sha) in pins.items():
        p = os.path.join(d, n)
        if not (os.path.isfile(p) and os.path.getsize(p) == size and _sha256(p) == sha):
            return False
    return True


def _rmtree(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _extract(zpath, dest, pins):
    """Unpack only the pinned names from `zpath` into the empty folder `dest`, each size-capped and SHA-256 checked."""
    by_key = {n.lower(): n for n in pins}
    done = set()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = by_key.get(info.filename.lower())
            if name is None:
                continue                                    # not a pinned name: never unpacked
            if name in done:
                raise IOError(f"runtime zip lists {name} twice")
            done.add(name)
            size, sha = pins[name]
            if info.is_dir() or info.flag_bits & 0x1 or info.file_size != size:
                raise IOError(f"{name}: not the pinned file (size {info.file_size}, expected {size})")
            h, got = hashlib.sha256(), 0
            with z.open(info) as src, open(os.path.join(dest, name), "xb") as out:
                while True:
                    b = src.read(min(CHUNK, size + 1 - got))
                    if not b:
                        break
                    got += len(b)
                    if got > size:
                        raise IOError(f"{name}: bigger than pinned")
                    h.update(b)
                    out.write(b)
            if got != size or h.hexdigest() != sha:
                raise IOError(f"{name}: checksum mismatch, runtime rejected")
    missing = sorted(set(pins) - done)
    if missing:
        raise IOError(f"runtime zip is missing {', '.join(missing)}")


def _swap(part, final):
    """Put the checked `part` folder in place of `final` (each step a rename; the old folder comes back on failure)."""
    old = final + ".old"
    _rmtree(old)
    if os.path.lexists(final):
        os.replace(final, old)
    try:
        os.replace(part, final)
    except BaseException:
        if os.path.lexists(old) and not os.path.lexists(final):
            os.replace(old, final)
        raise
    _rmtree(old)


def install(mid, data_dir, progress=None):
    """Download runtime `mid`'s pinned zip and unpack only its pinned DLLs to <data_dir>/runtime/<mid>; returns it.
    progress(name, got, size) follows the zip download. Raises (ValueError / OSError) and leaves nothing behind."""
    m = _entry(mid)
    pins = m["files_in_zip"]
    final = models.model_dir(mid, data_dir)
    if _verified(final, pins):
        return final                                        # already there and checked: no download
    zname, size, sha = m["files"]["zip"]
    if not _plain(zname, ".zip"):
        raise ValueError(f"runtime {mid}: zip name {zname!r} is not a plain name")
    root = os.path.dirname(final)
    os.makedirs(root, exist_ok=True)
    zpath, part = os.path.join(root, zname), final + ".part"
    try:
        _rmtree(part)
        embed._fetch_verified(m["url"], zpath, size, sha, zname, progress, part=".dl.part")
        os.makedirs(part)
        _extract(zpath, part, pins)
        _swap(part, final)
    except BaseException:
        _rmtree(part)
        _remove(zpath)
        raise
    _remove(zpath)
    log(f"runtime {mid} unpacked and verified ({len(pins)} DLLs)")
    return final
