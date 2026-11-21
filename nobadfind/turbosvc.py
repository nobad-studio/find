"""The turbo helper as a Windows service: set up once with one permission prompt, started without one.

Maintainer decision 2026-11-21: the optional turbo index (ntfs.py, its privacy rules are there) asks for
administrator rights ONCE, when the user turns it on, instead of every engine start. This module holds what both
sides need: the protected copy, its manifest, the DACLs, the service manager and the record of who may use it.

Setting it up (`NobadFindTurbo.exe --turbo install`, elevated, one UAC prompt; ntfs.helper_main)
- The helper is its own small program (packaging/nobadfind.spec: NobadFindTurbo.exe and its `_internal`, standard
  library and nobadfind's ntfs/scope/winapi/const only: no numpy, models, OCR or SQLCipher), in the user's install
  folder under `turbo\\`. The elevated step copies ONLY that folder into `<Program Files>\\NOBAD Find Turbo\\bin`.
  Program Files comes from HKLM (ProgramFilesDir), never from an environment variable the user can set.
- `<Program Files>\\NOBAD Find Turbo` gets FOLDER_SDDL (owner Administrators; SYSTEM and Administrators full,
  Users read and execute; protected, inherited by everything inside). A folder that is already there is refused
  when it is a reparse point (junction, link) or its DACL lets anyone but SYSTEM, Administrators or TrustedInstaller
  write (dacl_is_strong); so is a Program Files that is a reparse point.
- The copy: a manifest (SHA-256 of every file) is computed from the source just before copying; each file is then
  copied from ONE handle (opened without write or delete sharing, never through a reparse point) while its bytes
  are hashed, and must match the manifest; after the copy every file in the destination is hashed again and the
  tree must be exactly the manifest (nothing missing, nothing extra). A file swapped in between fails the step.
  The copy goes to `bin.new` and replaces `bin` only when it is complete and verified.
- The record (`install.json` in the protected folder, written by the elevated step): the user's SID (from Windows:
  the elevated process's parent, the engine that asked, and for an administrator's split token also the linked
  token; never from the command line), the engine's own exe path (the only program allowed to connect) and the
  manifest hash. The service and the engine both read it from the protected folder; the engine's messages never
  change it.
- The service `NOBADFindTurbo`: own process, DEMAND start (never automatic or at boot), binary path = the protected
  copy, quoted, with the fixed words `--turbo service`, account LocalSystem with its privileges cut down to
  REQUIRED_PRIVILEGES (SERVICE_CONFIG_REQUIRED_PRIVILEGES_INFO: no SeDebug, SeTcb, SeImpersonate, SeBackup...).
  Its DACL (service_sddl): SYSTEM and Administrators as Windows sets them, and the installing user may only query,
  start and stop it (no config change, no DACL change, no delete). Nobody else may even start it.
  Why LocalSystem: reading the volume (CreateFile on \\\\.\\C: and FSCTL_ENUM_USN_DATA / READ_USN_JOURNAL /
  GET_NTFS_FILE_RECORD) needs a token in the volume's DACL (Administrators or SYSTEM). LocalService/NetworkService
  are in neither; a virtual service account with only SeManageVolumePrivilege might be enough but could not be
  checked without elevation here, so the service runs as LocalSystem with its privileges cut down instead.

Using it (no prompt): the engine (turbo.py) starts the service with the user's own rights (StartService, allowed by
the service's DACL), checks the service's configuration is the protected copy, connects to the service's pipe and
checks the pipe's server is the service's own process in session 0. The service serves ONE client and ends when it
disconnects, or after IDLE_S without a client. Its checks of the client are in ntfs.py (check_client).

Updating: the engine hashes its own `turbo\\` folder and compares with the record. Different (a new version of NOBAD
Find was installed), or the record names another NobadFind.exe, or the service isn't the protected copy: "needs
update". The engine then uses the normal walk and says so until the user OKs the update (the same elevated step).
The protected copy is never changed without that prompt. Set up for ANOTHER account on this PC: "not installed" for
this one (one service per PC; turning turbo on here sets it up for this account with the prompt, and the other
account goes back to the normal walk); this account never removes the other's.

Removing: turning turbo off, the Remove button and `--uninstall` run `--turbo remove` elevated (one prompt): stop
the service, delete it (only if its binary path is ours), delete the protected folder (reparse points are removed,
never followed).

From source: `install`, `remove` and `service` always refuse (the service would run user-writable code as
LocalSystem). Development keeps ntfs.py's per-run `serve` behind NOBAD_FIND_DEV_TURBO=1.
"""
import ctypes
import hashlib
import json
import os
import re
import sys
from collections import namedtuple

SERVICE = "NOBADFindTurbo"
DISPLAY = "NOBAD Find Turbo"
DESCRIPTION = ("NOBAD Find's optional turbo index: reads NTFS file names and changes for the account that set it "
               "up. Started by NOBAD Find when needed; stops when NOBAD Find closes.")
DIR_NAME = "NOBAD Find Turbo"
EXE = "NobadFindTurbo.exe"
USER_DIR = "turbo"                 # in the user's install folder, next to NobadFind.exe
BIN = "bin"
RECORD = "install.json"
RECORD_VERSION = 1
SERVICE_WORDS = ("--turbo", "service")
IDLE_S = 60                        # the service ends when no client connects this long after it starts
MAX_FILES = 5000
MAX_BYTES = 512 * 1024 * 1024
REQUIRED_PRIVILEGES = ("SeChangeNotifyPrivilege", "SeManageVolumePrivilege")

SY, BA, BU = "S-1-5-18", "S-1-5-32-544", "S-1-5-32-545"
TI = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"      # NT SERVICE\TrustedInstaller
SID_RE = re.compile(r"^S-1-5-21-\d+-\d+-\d+-\d+$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

# The protected folder: owner Administrators, SYSTEM and Administrators full, Users read + execute; nothing inherited
# from Program Files (P), everything inside inherits it (OICI).
FOLDER_SDDL = "O:BAG:SYD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"
# Service rights for the user: CC query config, LC query status, RP start, WP stop, LO interrogate, RC read control.
USER_SERVICE_RIGHTS = "CCLCRPWPLORC"
# The service's pipe: this user only (read/write data, read attributes, synchronize, read control: no
# FILE_CREATE_PIPE_INSTANCE, no WRITE_DAC), network logons denied, medium label (no write or read up from below).
PIPE_RIGHTS = 0x00120083
PIPE_CLIENT_ACCESS = 0x00100083       # what the engine opens it with
SECURITY_SQOS_IDENTIFICATION = 0x00100000 | 0x00010000     # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION


def _sid_ok(sid):
    if not (isinstance(sid, str) and SID_RE.match(sid)):
        raise ValueError("not a user SID")
    return sid


def service_sddl(sid):
    return (f"D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
            f"(A;;{USER_SERVICE_RIGHTS};;;{_sid_ok(sid)})")


def pipe_sddl(sid):
    return f"D:P(D;;GA;;;NU)(A;;0x{PIPE_RIGHTS:x};;;{_sid_ok(sid)})S:(ML;;NWNR;;;ME)"


def service_pipe_name(sid):
    return f"\\\\.\\pipe\\NOBADFind-turbo-svc-{_sid_ok(sid)}"


# ---------- SDDL checks (pure) ----------
_ALIAS = {"SY": SY, "BA": BA, "BU": BU, "WD": "S-1-1-0", "AU": "S-1-5-11", "CO": "S-1-3-0", "OW": "S-1-3-4",
          "IU": "S-1-5-4", "AN": "S-1-5-7", "NU": "S-1-5-2", "PU": "S-1-5-32-547", "BG": "S-1-5-32-546",
          "LS": "S-1-5-19", "NS": "S-1-5-20", "AC": "S-1-15-2-1", "RC": "S-1-5-12", "CG": "S-1-3-1"}
TRUSTED = frozenset({SY, BA, TI})
_RIGHT = {"GA": 0x10000000, "GR": 0x80000000, "GW": 0x40000000, "GX": 0x20000000, "RC": 0x20000, "SD": 0x10000,
          "WD": 0x40000, "WO": 0x80000, "CC": 0x1, "DC": 0x2, "LC": 0x4, "SW": 0x8, "RP": 0x10, "WP": 0x20,
          "DT": 0x40, "LO": 0x80, "CR": 0x100, "FA": 0x1F01FF, "FR": 0x120089, "FW": 0x120116, "FX": 0x1200A0,
          "KA": 0xF003F, "KR": 0x20019, "KW": 0x20006, "KX": 0x20019}
# For a file or folder: anything that writes, deletes, changes the DACL/owner, or a generic right that includes them.
WRITE_BITS = (0x2 | 0x4 | 0x10 | 0x40 | 0x100 | 0x10000 | 0x40000 | 0x80000 | 0x1000000 | 0x2000000 |
              0x10000000 | 0x40000000)


def sid_of(trustee):
    return _ALIAS.get(trustee, trustee)


def rights(text):
    """An SDDL rights field (0x... or two-letter codes) as a mask; None when it has a code this doesn't know."""
    if re.match(r"^0[xX][0-9a-fA-F]+$", text):
        return int(text, 16)
    if len(text) % 2:
        return None
    mask = 0
    for i in range(0, len(text), 2):
        v = _RIGHT.get(text[i:i + 2])
        if v is None:
            return None
        mask |= v
    return mask


def split_sddl(sddl):
    """{"O": owner, "G": group, "D": dacl text, "S": sacl text} from an SDDL string (parentheses respected)."""
    out, key, depth, start = {}, None, 0, 0
    i = 0
    while i < len(sddl):
        ch = sddl[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch in "OGDS" and i + 1 < len(sddl) and sddl[i + 1] == ":":
            if key is not None:
                out[key] = sddl[start:i]
            key, start = ch, i + 2
            i += 2
            continue
        i += 1
    if key is not None:
        out[key] = sddl[start:]
    return out


def aces(part):
    """'PAI(A;;FA;;;SY)(...)' -> (flags, [[type, flags, rights, guid, inherit guid, sid, ...]])."""
    i = part.find("(")
    flags = part if i < 0 else part[:i]
    return flags, [a.split(";") for a in re.findall(r"\(([^()]*)\)", part)]


def dacl_is_strong(sddl):
    """True only if the owner is SYSTEM, Administrators or TrustedInstaller and no allow ACE gives anyone else a
    right that writes, deletes or changes permissions (inherit-only ACEs count too: children get them). Anything
    this can't read is weak (fail closed)."""
    if not isinstance(sddl, str):
        return False
    p = split_sddl(sddl)
    if sid_of(p.get("O", "")) not in TRUSTED:
        return False
    d = p.get("D")
    if d is None or "NO_ACCESS_CONTROL" in d:
        return False
    _flags, entries = aces(d)
    for a in entries:
        if len(a) < 6:
            return False
        kind, mask, sid = a[0], rights(a[2]), sid_of(a[5])
        if kind in ("D", "OD"):
            continue                                     # deny: never weaker
        if kind != "A" or mask is None:
            return False                                 # object, callback or conditional allows: not ours
        if sid not in TRUSTED and mask & WRITE_BITS:
            return False
    return True


def service_dacl_ok(sddl, sid):
    """The service's DACL as set up: SYSTEM and Administrators, and the user with at most USER_SERVICE_RIGHTS."""
    p = split_sddl(sddl or "")
    d = p.get("D")
    if d is None:
        return False
    allowed_user = rights(USER_SERVICE_RIGHTS)
    seen_user = False
    for a in aces(d)[1]:
        if len(a) < 6:
            return False
        kind, mask, who = a[0], rights(a[2]), sid_of(a[5])
        if kind == "D":
            continue
        if kind != "A" or mask is None:
            return False
        if who in (SY, BA):
            continue
        if who == sid and not mask & ~allowed_user:
            seen_user = True
            continue
        return False
    return seen_user


# ---------- manifest and verified copy ----------
class Unsafe(PermissionError):
    """A reparse point, a weak DACL, an unexpected file: the step refuses."""


class Mismatch(PermissionError):
    """A file's bytes are not what the manifest says (changed or swapped during the step)."""


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_reparse_entry(entry):
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    return entry.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def tree_files(root):
    """Every file under root as sorted relative paths. Raises Unsafe on a reparse point anywhere, too many files
    or too many bytes."""
    out, total = [], 0

    def walk(d, rel):
        nonlocal total
        with os.scandir(d) as it:
            entries = sorted(it, key=lambda e: e.name)
        for e in entries:
            r = e.name if not rel else rel + "\\" + e.name
            if _is_reparse_entry(e):
                raise Unsafe(f"a link or junction in the helper's files: {r}")
            if e.is_dir(follow_symlinks=False):
                walk(e.path, r)
            elif e.is_file(follow_symlinks=False):
                out.append(r)
                total += e.stat(follow_symlinks=False).st_size
                if len(out) > MAX_FILES or total > MAX_BYTES:
                    raise Unsafe("the helper's folder is too big")
            else:
                raise Unsafe(f"not a file or folder: {r}")
    if os.path.lexists(root) and is_reparse(root):
        raise Unsafe("the helper's folder is a link or junction")
    walk(root, "")
    return out


def is_reparse(path):
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return os.path.islink(path) or bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def open_locked(path):
    """A file opened for reading once, without write or delete sharing and never through a reparse point. Off
    Windows (tests) plain open."""
    if sys.platform != "win32":
        return open(path, "rb")
    import msvcrt
    from ctypes import wintypes
    k = _k32()
    h = k.CreateFileW(path, 0x80000000, 0x1, None, 3, 0x00200000 | 0x08000000, None)   # READ; share READ;
    if not h or h == INVALID_HANDLE:                                                    # OPEN_REPARSE_POINT|SEQ
        raise OSError(ctypes.get_last_error(), "can't open a helper file")
    info = (wintypes.DWORD * 13)()
    if not k.GetFileInformationByHandle(h, info) or info[0] & (FILE_ATTRIBUTE_REPARSE_POINT | 0x10):
        k.CloseHandle(h)
        raise Unsafe("a helper file is a link or a folder")
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "rb")


def _hash_stream(f, out=None):
    h = hashlib.sha256()
    while True:
        b = f.read(1 << 20)
        if not b:
            return h.hexdigest()
        h.update(b)
        if out is not None:
            out.write(b)


def manifest(root, opener=open_locked):
    """{relative path: SHA-256} of every file under root."""
    m = {}
    for rel in tree_files(root):
        with opener(os.path.join(root, rel)) as f:
            m[rel] = _hash_stream(f)
    return m


def manifest_hash(m):
    return hashlib.sha256(json.dumps(sorted(m.items()), separators=(",", ":")).encode("utf-8")).hexdigest()


def copy_verified(src, dst, m, opener=open_locked, hook=None):
    """Copy every file of the manifest from src to dst (which must be empty), each from one handle, hashing what was
    read; raises Mismatch when a file differs from the manifest. hook(rel) runs before each file (tests)."""
    for rel in sorted(m):
        if hook is not None:
            hook(rel)
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with opener(os.path.join(src, rel)) as f, open(target, "xb") as out:
            got = _hash_stream(f, out)
        if got != m[rel]:
            raise Mismatch(f"{rel} changed while it was copied")


def verify_tree(dst, m, opener=open_locked):
    """dst holds exactly the manifest's files with exactly its hashes."""
    have = tree_files(dst)
    if sorted(have) != sorted(m):
        raise Mismatch("the copied helper's files are not the ones expected")
    for rel in have:
        with opener(os.path.join(dst, rel)) as f:
            if _hash_stream(f) != m[rel]:
                raise Mismatch(f"{rel} is not what was copied")


def rmtree_safe(path):
    """Delete a folder tree; a reparse point is removed itself, never followed."""
    if not os.path.lexists(path):
        return
    if is_reparse(path):
        try:
            os.rmdir(path)
        except OSError:
            os.unlink(path)
        return
    with os.scandir(path) as it:
        entries = list(it)
    for e in entries:
        if _is_reparse_entry(e):
            try:
                os.rmdir(e.path)
            except OSError:
                os.unlink(e.path)
        elif e.is_dir(follow_symlinks=False):
            rmtree_safe(e.path)
        else:
            try:
                os.chmod(e.path, 0o666)
            except OSError:
                pass
            os.unlink(e.path)
    os.rmdir(path)


# ---------- the record ----------
Record = namedtuple("Record", "user_sid client_image manifest")


def parse_record(obj):
    """A Record from install.json's content, or None if it isn't exactly what the elevated step writes."""
    if not isinstance(obj, dict) or obj.get("version") != RECORD_VERSION:
        return None
    sid, image, mh = obj.get("user_sid"), obj.get("client_image"), obj.get("manifest")
    if not (isinstance(sid, str) and SID_RE.match(sid)):
        return None
    if not (isinstance(image, str) and 3 < len(image) < 32768 and os.path.isabs(image) and "\x00" not in image
            and image.lower().endswith(".exe")):
        return None
    if not (isinstance(mh, str) and HEX64.match(mh)):
        return None
    return Record(sid, image, mh)


def read_record(root):
    try:
        with open(os.path.join(root, RECORD), "rb") as f:
            raw = f.read(65536)
        return parse_record(json.loads(raw.decode("utf-8")))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def write_record(root, rec):
    data = json.dumps({"version": RECORD_VERSION, "user_sid": rec.user_sid, "client_image": rec.client_image,
                       "manifest": rec.manifest}, indent=1).encode("utf-8")
    tmp = os.path.join(root, RECORD + ".new")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(root, RECORD))


def same_path(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


NOT_INSTALLED, INSTALLED, NEEDS_UPDATE = "not_installed", "installed", "needs_update"
OTHER_ACCOUNT = "Turbo's helper is set up for another account on this PC."


def helper_status(record, service_cmd, own_manifest, sid, image, expected_cmd):
    """(status, why) for the engine: installed only when the record and the service are this install's, for this
    account, with exactly the helper files this NOBAD Find ships."""
    if record is None and service_cmd is None:
        return NOT_INSTALLED, ""
    if record is not None and record.user_sid != sid:
        return NOT_INSTALLED, OTHER_ACCOUNT          # nothing for this account (never removed from here)
    if record is None or service_cmd is None:
        return NEEDS_UPDATE, "Turbo's helper is only partly set up."
    if not same_path(record.client_image, image):
        return NEEDS_UPDATE, "Turbo's helper is set up for a NOBAD Find in another folder."
    if os.path.normcase(service_cmd.strip()) != os.path.normcase(expected_cmd):
        return NEEDS_UPDATE, "Turbo's service isn't the one NOBAD Find set up."
    if own_manifest is None or record.manifest != own_manifest:
        return NEEDS_UPDATE, "NOBAD Find was updated."
    return INSTALLED, ""


# ---------- paths ----------
def program_files():
    """Program Files as HKLM says (admin-only), never from an environment variable."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion", 0,
                        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as k:
        v = winreg.QueryValueEx(k, "ProgramFilesDir")[0]
    if not (isinstance(v, str) and re.match(r"^[A-Za-z]:\\", v) and "%" not in v):
        raise Unsafe("Program Files isn't a plain folder")
    return os.path.normpath(v)


def protected_root():
    return os.path.join(program_files(), DIR_NAME)


def service_command(root):
    return f'"{os.path.join(root, BIN, EXE)}" {" ".join(SERVICE_WORDS)}'


def user_helper_dir(app_dir=None):
    """The helper's files in the user's install: <folder of NobadFind.exe>\\turbo."""
    return os.path.join(app_dir or os.path.dirname(os.path.abspath(sys.executable)), USER_DIR)


# ---------- Windows: files and security descriptors ----------
INVALID_HANDLE = ctypes.c_void_p(-1).value
_dll = {}


def _k32():
    if "k" not in _dll:
        from ctypes import wintypes as w
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B, P = w.HANDLE, w.DWORD, w.BOOL, ctypes.c_void_p
        for name, res, args in (
                ("CreateFileW", H, [w.LPCWSTR, D, D, P, D, D, H]),
                ("GetFileInformationByHandle", B, [H, P]),
                ("CloseHandle", B, [H]),
                ("CreateDirectoryW", B, [w.LPCWSTR, P]),
                ("LocalFree", P, [P]),
                ("CreateNamedPipeW", H, [w.LPCWSTR, D, D, D, D, D, D, P]),
                ("WaitNamedPipeW", B, [w.LPCWSTR, D]),
                ("Sleep", None, [D])):
            f = getattr(k, name)
            f.restype, f.argtypes = res, args
        _dll["k"] = k
    return _dll["k"]


def _adv():
    if "a" not in _dll:
        from ctypes import wintypes as w
        a = ctypes.WinDLL("advapi32", use_last_error=True)
        H, D, B, P = w.HANDLE, w.DWORD, w.BOOL, ctypes.c_void_p
        PD = ctypes.POINTER(D)
        for name, res, args in (
                ("ConvertStringSecurityDescriptorToSecurityDescriptorW", B, [w.LPCWSTR, D, ctypes.POINTER(P), P]),
                ("ConvertSecurityDescriptorToStringSecurityDescriptorW", B, [P, D, D, ctypes.POINTER(w.LPWSTR), P]),
                ("GetNamedSecurityInfoW", D, [w.LPCWSTR, ctypes.c_int, D, P, P, P, P, ctypes.POINTER(P)]),
                ("SetNamedSecurityInfoW", D, [w.LPWSTR, ctypes.c_int, D, P, P, P, P]),
                ("GetSecurityDescriptorDacl", B, [P, ctypes.POINTER(B), ctypes.POINTER(P), ctypes.POINTER(B)]),
                ("GetSecurityDescriptorOwner", B, [P, ctypes.POINTER(P), ctypes.POINTER(B)]),
                ("OpenSCManagerW", H, [w.LPCWSTR, w.LPCWSTR, D]),
                ("OpenServiceW", H, [H, w.LPCWSTR, D]),
                ("CreateServiceW", H, [H, w.LPCWSTR, w.LPCWSTR, D, D, D, D, w.LPCWSTR, w.LPCWSTR, PD, w.LPCWSTR,
                                       w.LPCWSTR, w.LPCWSTR]),
                ("ChangeServiceConfigW", B, [H, D, D, D, w.LPCWSTR, w.LPCWSTR, PD, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR,
                                             w.LPCWSTR]),
                ("ChangeServiceConfig2W", B, [H, D, P]),
                ("QueryServiceConfigW", B, [H, P, D, PD]),
                ("QueryServiceStatusEx", B, [H, ctypes.c_int, P, D, PD]),
                ("StartServiceW", B, [H, D, P]),
                ("ControlService", B, [H, D, P]),
                ("DeleteService", B, [H]),
                ("CloseServiceHandle", B, [H]),
                ("SetServiceObjectSecurity", B, [H, D, P]),
                ("QueryServiceObjectSecurity", B, [H, D, P, D, PD])):
            f = getattr(a, name)
            f.restype, f.argtypes = res, args
        _dll["a"] = a
    return _dll["a"]


class _SA(ctypes.Structure):
    _fields_ = [("nLength", ctypes.c_uint32), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", ctypes.c_int)]


class SecurityDescriptor:
    """An SDDL string as a self-relative security descriptor (LocalFree'd on close)."""

    def __init__(self, sddl):
        self.p = ctypes.c_void_p()
        if not _adv().ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(self.p), None):
            raise ctypes.WinError(ctypes.get_last_error())

    def attributes(self):
        self._sa = _SA(ctypes.sizeof(_SA), self.p, 0)
        return ctypes.byref(self._sa)

    def close(self):
        if self.p:
            _k32().LocalFree(self.p)
            self.p = ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sd_to_sddl(psd, info=0x1 | 0x4):
    from ctypes import wintypes
    s = wintypes.LPWSTR()
    if not _adv().ConvertSecurityDescriptorToStringSecurityDescriptorW(psd, 1, info, ctypes.byref(s), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return s.value
    finally:
        _k32().LocalFree(s)


def path_sddl(path):
    """Owner and DACL of a file or folder, as SDDL (the link itself if it is one: GetNamedSecurityInfo opens it
    without following only for the last component, so callers check is_reparse first)."""
    psd = ctypes.c_void_p()
    err = _adv().GetNamedSecurityInfoW(path, 1, 0x1 | 0x4, None, None, None, None, ctypes.byref(psd))
    if err:
        raise OSError(err, "can't read the folder's permissions")
    try:
        return sd_to_sddl(psd)
    finally:
        _k32().LocalFree(psd)


class Fs:
    """The protected folder's file system operations (tests replace them: no admin rights there)."""

    def is_reparse(self, path):
        return is_reparse(path)

    def sddl_of(self, path):
        return path_sddl(path)

    def create_dir(self, path, sddl):
        with SecurityDescriptor(sddl) as sd:
            if not _k32().CreateDirectoryW(path, sd.attributes()):
                raise ctypes.WinError(ctypes.get_last_error())

    def apply(self, path, sddl):
        """Owner + protected DACL from sddl onto an existing folder (children inherit it)."""
        from ctypes import wintypes
        a = _adv()
        with SecurityDescriptor(sddl) as sd:
            present, defaulted = wintypes.BOOL(), wintypes.BOOL()
            dacl, owner = ctypes.c_void_p(), ctypes.c_void_p()
            if not (a.GetSecurityDescriptorDacl(sd.p, ctypes.byref(present), ctypes.byref(dacl),
                                                ctypes.byref(defaulted)) and present.value
                    and a.GetSecurityDescriptorOwner(sd.p, ctypes.byref(owner), ctypes.byref(defaulted))):
                raise OSError(0, "bad descriptor")
            err = a.SetNamedSecurityInfoW(path, 1, 0x1 | 0x4 | 0x80000000, owner, None, dacl, None)
            if err:
                raise OSError(err, "can't set the folder's permissions")


def prepare_root(root, fs):
    """Create or check the protected folder: refuses a reparse point (the folder or Program Files) or an existing
    folder anyone but SYSTEM/Administrators/TrustedInstaller may write to; then sets and checks FOLDER_SDDL."""
    parent = os.path.dirname(root)
    if fs.is_reparse(parent):
        raise Unsafe("Program Files is a link or junction")
    if os.path.lexists(root):
        if fs.is_reparse(root) or not os.path.isdir(root):
            raise Unsafe(f"{root} is a link, a junction or a file")
        if not dacl_is_strong(fs.sddl_of(root)):
            raise Unsafe(f"{root} is already there and others may change it")
        fs.apply(root, FOLDER_SDDL)
    else:
        fs.create_dir(root, FOLDER_SDDL)
    if fs.is_reparse(root) or not dacl_is_strong(fs.sddl_of(root)):
        raise Unsafe(f"{root} didn't get its permissions")


# ---------- the service manager ----------
SERVICE_WIN32_OWN_PROCESS = 0x10
SERVICE_DEMAND_START = 3
SERVICE_ERROR_NORMAL = 1
SERVICE_NO_CHANGE = 0xFFFFFFFF
STOPPED, START_PENDING, STOP_PENDING, RUNNING = 1, 2, 3, 4
ERROR_SERVICE_DOES_NOT_EXIST, ERROR_SERVICE_ALREADY_RUNNING, ERROR_SERVICE_NOT_ACTIVE = 1060, 1056, 1062
ERROR_ACCESS_DENIED = 5
ServiceConfig = namedtuple("ServiceConfig", "command start account type")


class Scm:
    """A thin wrapper over the service manager (tests use a fake with the same methods)."""

    def _open(self, access, scm_access=0x1):
        a = _adv()
        m = a.OpenSCManagerW(None, None, scm_access)
        if not m:
            raise ctypes.WinError(ctypes.get_last_error())
        h = a.OpenServiceW(m, SERVICE, access)
        err = ctypes.get_last_error()
        a.CloseServiceHandle(m)
        if not h:
            if err == ERROR_SERVICE_DOES_NOT_EXIST:
                return None
            raise ctypes.WinError(err)
        return h

    def _close(self, h):
        if h:
            _adv().CloseServiceHandle(h)

    def config(self):
        """ServiceConfig, or None when there is no such service. Raises PermissionError when this account may not
        look at it (another account's turbo)."""
        from ctypes import wintypes
        h = self._open(0x1)                                        # SERVICE_QUERY_CONFIG
        if h is None:
            return None
        try:
            need = wintypes.DWORD()
            _adv().QueryServiceConfigW(h, None, 0, ctypes.byref(need))
            buf = ctypes.create_string_buffer(max(need.value, 64))
            if not _adv().QueryServiceConfigW(h, buf, len(buf), ctypes.byref(need)):
                raise ctypes.WinError(ctypes.get_last_error())

            class QSC(ctypes.Structure):
                _fields_ = [("type", wintypes.DWORD), ("start", wintypes.DWORD), ("err", wintypes.DWORD),
                            ("path", wintypes.LPWSTR), ("group", wintypes.LPWSTR), ("tag", wintypes.DWORD),
                            ("deps", wintypes.LPWSTR), ("account", wintypes.LPWSTR), ("display", wintypes.LPWSTR)]
            q = QSC.from_buffer(buf)
            return ServiceConfig(q.path or "", q.start, q.account or "", q.type)
        finally:
            self._close(h)

    def status(self):
        """(state, process id) or None when there is no such service."""
        h = self._open(0x4)                                        # SERVICE_QUERY_STATUS
        if h is None:
            return None
        try:
            from ctypes import wintypes
            buf = (wintypes.DWORD * 9)()
            need = wintypes.DWORD()
            if not _adv().QueryServiceStatusEx(h, 0, buf, ctypes.sizeof(buf), ctypes.byref(need)):
                raise ctypes.WinError(ctypes.get_last_error())
            return buf[1], buf[7]
        finally:
            self._close(h)

    def start(self):
        h = self._open(0x10)                                       # SERVICE_START
        if h is None:
            raise FileNotFoundError("no turbo service")
        try:
            if not _adv().StartServiceW(h, 0, None):
                err = ctypes.get_last_error()
                if err != ERROR_SERVICE_ALREADY_RUNNING:
                    raise ctypes.WinError(err)
        finally:
            self._close(h)

    def stop(self, wait_s=20):
        h = self._open(0x20 | 0x4)                                 # SERVICE_STOP | QUERY_STATUS
        if h is None:
            return
        try:
            st = (ctypes.c_uint32 * 7)()
            _adv().ControlService(h, 1, st)                        # SERVICE_CONTROL_STOP
        finally:
            self._close(h)
        import time
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            s = self.status()
            if s is None or s[0] == STOPPED:
                return
            time.sleep(0.2)

    def create(self, command):
        a = _adv()
        m = a.OpenSCManagerW(None, None, 0x1 | 0x2)                # CONNECT | CREATE_SERVICE
        if not m:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            h = a.CreateServiceW(m, SERVICE, DISPLAY, 0xF01FF, SERVICE_WIN32_OWN_PROCESS, SERVICE_DEMAND_START,
                                 SERVICE_ERROR_NORMAL, command, None, None, None, None, None)   # LocalSystem
            if not h:
                raise ctypes.WinError(ctypes.get_last_error())
            a.CloseServiceHandle(h)
        finally:
            a.CloseServiceHandle(m)

    def change(self, command):
        h = self._open(0x2)                                        # SERVICE_CHANGE_CONFIG
        try:
            if not _adv().ChangeServiceConfigW(h, SERVICE_WIN32_OWN_PROCESS, SERVICE_DEMAND_START,
                                               SERVICE_ERROR_NORMAL, command, None, None, None, "LocalSystem",
                                               "", DISPLAY):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._close(h)

    def describe(self, privileges):
        from ctypes import wintypes
        h = self._open(0x2)
        try:
            desc = ctypes.create_unicode_buffer(DESCRIPTION)
            box = (wintypes.LPWSTR * 1)(ctypes.cast(desc, wintypes.LPWSTR))
            if not _adv().ChangeServiceConfig2W(h, 1, box):        # SERVICE_CONFIG_DESCRIPTION
                raise ctypes.WinError(ctypes.get_last_error())
            multi = ctypes.create_unicode_buffer("\0".join(privileges) + "\0\0")
            box2 = (wintypes.LPWSTR * 1)(ctypes.cast(multi, wintypes.LPWSTR))
            if not _adv().ChangeServiceConfig2W(h, 6, box2):       # SERVICE_CONFIG_REQUIRED_PRIVILEGES_INFO
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._close(h)

    def set_sddl(self, sddl):
        h = self._open(0x40000)                                    # WRITE_DAC
        try:
            with SecurityDescriptor(sddl) as sd:
                if not _adv().SetServiceObjectSecurity(h, 0x4, sd.p):
                    raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._close(h)

    def get_sddl(self):
        from ctypes import wintypes
        h = self._open(0x20000)                                    # READ_CONTROL
        try:
            need = wintypes.DWORD()
            _adv().QueryServiceObjectSecurity(h, 0x4, None, 0, ctypes.byref(need))
            buf = ctypes.create_string_buffer(max(need.value, 64))
            if not _adv().QueryServiceObjectSecurity(h, 0x4, buf, len(buf), ctypes.byref(need)):
                raise ctypes.WinError(ctypes.get_last_error())
            return sd_to_sddl(buf, 0x4)
        finally:
            self._close(h)

    def delete(self):
        h = self._open(0x10000)                                    # DELETE
        if h is None:
            return
        try:
            if not _adv().DeleteService(h):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._close(h)


# ---------- the elevated steps (ntfs.helper_main runs them; tests run them with fakes) ----------
class NotOurs(PermissionError):
    """A service called NOBADFindTurbo exists and runs something else: never touched."""


def _ours(cfg, root):
    return cfg is not None and os.path.normcase(cfg.command.strip()) == os.path.normcase(service_command(root))


def register(scm, root, sid):
    """Create or update the service for the protected copy, then check it is exactly that."""
    cmd = service_command(root)
    cfg = scm.config()
    if cfg is not None and not _ours(cfg, root):
        raise NotOurs("a service of that name runs another program")
    if cfg is None:
        scm.create(cmd)
    else:
        scm.change(cmd)
    scm.describe(REQUIRED_PRIVILEGES)
    scm.set_sddl(service_sddl(sid))
    cfg = scm.config()
    if not (_ours(cfg, root) and cfg.start == SERVICE_DEMAND_START and cfg.account.lower() == "localsystem"):
        raise Unsafe("the service wasn't set up as asked")
    if not service_dacl_ok(scm.get_sddl(), sid):
        raise Unsafe("the service's permissions weren't set as asked")


def _rmtree_retry(path, tries=20):
    """rmtree_safe, again for a few seconds: a service that just stopped may hold its exe a moment longer."""
    import time
    for attempt in range(tries):
        try:
            rmtree_safe(path)
            return
        except OSError:
            if attempt == tries - 1:
                raise
            time.sleep(0.5)


def install(src, root, sid, client_image, scm, fs, opener=open_locked, hook=None):
    """The elevated step: copy the helper (verified), record who may use it, register the service. Returns the
    manifest hash. Raises Unsafe / Mismatch / NotOurs (PermissionError) or OSError; nothing half-done is used:
    the service only ever points at a complete, verified bin."""
    _sid_ok(sid)
    if same_path(os.path.dirname(src), root) or same_path(src, os.path.join(root, BIN)):
        raise Unsafe("the helper can't be set up from its own protected copy")
    cfg = scm.config()
    if cfg is not None and not _ours(cfg, root):
        raise NotOurs("a service of that name runs another program")
    m = manifest(src, opener)
    if EXE not in m:
        raise Unsafe(f"{EXE} isn't in the helper's folder")
    prepare_root(root, fs)
    if cfg is not None:
        scm.stop()
    stage, final = os.path.join(root, BIN + ".new"), os.path.join(root, BIN)
    rmtree_safe(stage)
    os.mkdir(stage)
    copy_verified(src, stage, m, opener, hook)
    verify_tree(stage, m, opener)
    _rmtree_retry(final)
    os.rename(stage, final)
    if fs.is_reparse(final) or not dacl_is_strong(fs.sddl_of(final)):
        raise Unsafe("the helper's folder didn't get its permissions")
    verify_tree(final, m, opener)
    mh = manifest_hash(m)
    write_record(root, Record(sid, client_image, mh))
    register(scm, root, sid)
    return mh


def remove(root, scm, fs):
    """The elevated step: stop and delete our service (never another program's), delete the protected folder."""
    cfg = scm.config()
    if cfg is not None:
        if not _ours(cfg, root):
            raise NotOurs("a service of that name runs another program")
        scm.stop()
        scm.delete()
    if os.path.lexists(root):
        if fs.is_reparse(root):
            try:
                os.rmdir(root)                                     # the link itself, never what it points to
            except OSError:
                os.unlink(root)
            return
        _rmtree_retry(root)


# ---------- the pipe (both ends) ----------
def make_server_pipe(name, sddl, first=True):
    """The service's end: one instance, FILE_FLAG_FIRST_PIPE_INSTANCE (fails if anyone holds the name), no remote
    clients, overlapped, the DACL given. Raises OSError."""
    with SecurityDescriptor(sddl) as sd:
        h = _k32().CreateNamedPipeW(name, 0x3 | 0x40000000 | (0x00080000 if first else 0), 0x8, 1, 65536, 65536, 0,
                                    sd.attributes())
    if not h or h == INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return h


def open_client_pipe(name, timeout_s=20.0, alive=None):
    """The engine's end: waits for the pipe, opens it with only the rights the DACL gives, overlapped, and with
    SECURITY_IDENTIFICATION (the server can identify the engine's user, never act as it). Raises OSError."""
    import time
    k = _k32()
    end = time.monotonic() + timeout_s
    while True:
        h = k.CreateFileW(name, PIPE_CLIENT_ACCESS, 0, None, 3, 0x40000000 | SECURITY_SQOS_IDENTIFICATION, None)
        if h and h != INVALID_HANDLE:
            return h
        err = ctypes.get_last_error()
        if time.monotonic() > end or (alive is not None and not alive()):
            raise OSError(err, "the turbo helper's pipe isn't there")
        if err == 231:                                            # ERROR_PIPE_BUSY
            k.WaitNamedPipeW(name, 500)
        else:
            time.sleep(0.1)


# ---------- the service itself (the protected copy, run by the service manager) ----------
def run_service(body):
    """StartServiceCtrlDispatcher for the one service in this process. body(end) serves; end(code) tells the
    service manager it stopped and ends the process. Accepts stop and shutdown. Returns 10 when the service
    manager didn't start this process (someone ran `--turbo service` by hand)."""
    import threading
    from ctypes import wintypes as w
    a = ctypes.WinDLL("advapi32", use_last_error=True)

    class STATUS(ctypes.Structure):
        _fields_ = [(n, w.DWORD) for n in ("type", "state", "accepted", "exit", "specific", "checkpoint", "hint")]

    HANDLER = ctypes.WINFUNCTYPE(w.DWORD, w.DWORD, w.DWORD, ctypes.c_void_p, ctypes.c_void_p)
    MAIN = ctypes.WINFUNCTYPE(None, w.DWORD, ctypes.POINTER(w.LPWSTR))

    class ENTRY(ctypes.Structure):
        _fields_ = [("name", w.LPWSTR), ("proc", MAIN)]

    a.RegisterServiceCtrlHandlerExW.restype = ctypes.c_void_p
    a.RegisterServiceCtrlHandlerExW.argtypes = [w.LPCWSTR, HANDLER, ctypes.c_void_p]
    a.SetServiceStatus.argtypes = [ctypes.c_void_p, ctypes.POINTER(STATUS)]
    a.StartServiceCtrlDispatcherW.argtypes = [ctypes.POINTER(ENTRY)]
    box = {"h": None}

    def report(state, code=0):
        if box["h"]:
            st = STATUS(SERVICE_WIN32_OWN_PROCESS, state, (0x1 | 0x4) if state == RUNNING else 0,
                        1066 if code else 0, code, 0, 3000 if state in (START_PENDING, STOP_PENDING) else 0)
            a.SetServiceStatus(box["h"], ctypes.byref(st))

    def end(code=0):
        try:
            report(STOPPED, int(code or 0))
        finally:
            os._exit(int(code or 0))

    def handler(control, _etype, _edata, _ctx):
        if control in (1, 5):                                    # SERVICE_CONTROL_STOP, SHUTDOWN
            report(STOP_PENDING)
            threading.Thread(target=end, args=(0,), daemon=True).start()
            return 0
        return 0 if control == 4 else 120                        # INTERROGATE; else ERROR_CALL_NOT_IMPLEMENTED

    def main(_argc, _argv):                                      # the arguments StartService passed: never read
        box["h"] = a.RegisterServiceCtrlHandlerExW(SERVICE, box["handler"], None)
        if not box["h"]:
            os._exit(11)
        report(RUNNING)
        try:
            code = body(end)
        except Exception as e:
            print(f"turbo service ended: {type(e).__name__}", file=sys.stderr)
            code = 5
        end(code or 0)

    box["handler"], box["main"] = HANDLER(handler), MAIN(main)  # kept alive for as long as the process runs
    table = (ENTRY * 2)(ENTRY(SERVICE, box["main"]), ENTRY(None, MAIN()))
    if not a.StartServiceCtrlDispatcherW(table):
        return 10
    return 0
