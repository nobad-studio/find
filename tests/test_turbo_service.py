"""The turbo helper as a service (nobadfind/turbosvc.py, ntfs.check_client, turbo.HelperSetup), maintainer decision
2026-11-21: one UAC prompt when turbo is turned on, none at engine start.

Never a UAC prompt, never a real service: the service manager is a fake, the protected folder's DACL steps are a
fake (setting an Administrators owner needs admin rights), and the elevated step's exit codes are scripted. The
pipe's DACL and both ends' identity checks run on a real, unelevated pipe."""
import ctypes
import os
import sys
import threading
from ctypes import wintypes

import pytest

from nobadfind import ntfs, turbo, turbosvc
from nobadfind.settings import Settings
from nobadfind.store import Store

win = pytest.mark.skipif(sys.platform != "win32", reason="Windows")
SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER = "S-1-5-21-1111111111-2222222222-3333333333-1002"


# ---------- SDDL ----------
def test_the_service_dacl_lets_the_user_only_query_start_and_stop():
    s = turbosvc.service_sddl(SID)
    assert s == ("D:(A;;CCLCSWRPWPDTLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)"
                 f"(A;;CCLCRPWPLORC;;;{SID})")
    assert turbosvc.service_dacl_ok(s, SID)
    assert not turbosvc.service_dacl_ok(s, OTHER)                         # recorded for someone else
    for extra in ("DC", "WD", "WO", "SD"):                                  # change config, DACL, owner, delete
        assert not turbosvc.service_dacl_ok(s.replace("CCLCRPWPLORC", "CCLCRPWPLORC" + extra), SID), extra
    assert not turbosvc.service_dacl_ok(s + "(A;;RP;;;IU)", SID)          # interactive users may not start it
    assert not turbosvc.service_dacl_ok(s + "(A;;RP;;;WD)", SID)
    with pytest.raises(ValueError):
        turbosvc.service_sddl("S-1-5-18")                                   # only a real user account
    with pytest.raises(ValueError):
        turbosvc.service_sddl(SID + ")(A;;GA;;;WD")


def test_the_pipe_dacl_is_the_user_only_with_data_rights():
    s = turbosvc.pipe_sddl(SID)
    assert s == f"D:P(D;;GA;;;NU)(A;;0x120083;;;{SID})S:(ML;;NWNR;;;ME)"
    mask = turbosvc.rights("0x120083")
    assert not mask & 0x4                     # FILE_CREATE_PIPE_INSTANCE: nobody else can add an instance
    assert not mask & (0x40000 | 0x80000)     # no WRITE_DAC / WRITE_OWNER
    assert turbosvc.service_pipe_name(SID) == "\\\\.\\pipe\\NOBADFind-turbo-svc-" + SID


@pytest.mark.parametrize("sddl, strong", [
    (turbosvc.FOLDER_SDDL, True),
    ("O:BAG:SYD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)", True),
    ("O:S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464D:(A;;FA;;;S-1-5-80-956008885-3418522649-"
     "1831038044-1853292631-2271478464)(A;;FR;;;BU)", True),                        # TrustedInstaller
    ("O:SYD:(A;;FA;;;SY)(D;;FA;;;WD)(A;;FX;;;BU)", True),                           # a deny is never weaker
    ("O:BUD:(A;;FA;;;SY)", False),                                                  # owned by Users
    (f"O:{SID}D:(A;;FA;;;SY)", False),                                              # owned by a user
    ("O:BAD:(A;OICI;FA;;;SY)(A;OICI;FW;;;BU)", False),                              # Users may write
    ("O:BAD:(A;OICIIO;GA;;;CO)(A;;FA;;;SY)", False),                                # creator owner (inherit-only)
    ("O:BAD:(A;;0x2;;;AU)", False),                                                 # add file
    ("O:BAD:(A;;0x40;;;BU)", False),                                                # delete child
    ("O:BAD:(A;;0x10000;;;WD)", False),                                             # delete
    ("O:BAD:(A;;GW;;;WD)", False),
    (f"O:BAD:(A;;FA;;;{SID})", False),
    ("O:BAD:NO_ACCESS_CONTROL", False),                                             # null DACL
    ("O:BA", False),                                                                # no DACL
    ("O:BAD:(OA;;FA;;;WD)", False),                                                 # an object ACE: not ours
    ("O:BAD:(A;;ZZ;;;BU)", False),                                                  # a right this can't read
    ("O:BAD:(XA;;FX;;;BU;(x))", False),                                             # callback ACE
    (None, False),
])
def test_dacl_is_strong(sddl, strong):
    assert turbosvc.dacl_is_strong(sddl) is strong


@win
def test_a_folder_the_user_made_is_never_strong(tmp_path):
    """A real DACL read back from Windows: a folder the user owns (and could change) is refused."""
    assert not turbosvc.dacl_is_strong(turbosvc.path_sddl(str(tmp_path)))


# ---------- manifest and verified copy ----------
def _tree(root, files):
    for rel, data in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
    return root


FILES = {turbosvc.EXE: b"MZ helper", "_internal\\python311.dll": b"dll" * 1000, "_internal\\base_library.zip": b"z"}


def test_manifest_hash_and_verified_copy(tmp_path):
    src = _tree(str(tmp_path / "src"), FILES)
    m = turbosvc.manifest(src)
    assert sorted(m) == sorted(FILES) and all(len(v) == 64 for v in m.values())
    assert turbosvc.manifest_hash(m) == turbosvc.manifest_hash(dict(reversed(list(m.items()))))   # order-free
    dst = str(tmp_path / "dst")
    os.mkdir(dst)
    turbosvc.copy_verified(src, dst, m)
    turbosvc.verify_tree(dst, m)
    other = dict(m, **{turbosvc.EXE: "0" * 64})
    assert turbosvc.manifest_hash(other) != turbosvc.manifest_hash(m)


def test_a_file_swapped_before_its_copy_fails_the_copy(tmp_path):
    src = _tree(str(tmp_path / "src"), FILES)
    m = turbosvc.manifest(src)
    dst = str(tmp_path / "dst")
    os.mkdir(dst)

    def swap(rel):
        if rel == turbosvc.EXE:
            with open(os.path.join(src, rel), "wb") as f:
                f.write(b"MZ something else")
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.copy_verified(src, dst, m, hook=swap)


def test_a_file_swapped_after_its_copy_fails_the_check(tmp_path):
    src = _tree(str(tmp_path / "src"), FILES)
    m = turbosvc.manifest(src)
    dst = str(tmp_path / "dst")
    os.mkdir(dst)
    turbosvc.copy_verified(src, dst, m)
    with open(os.path.join(dst, "_internal", "python311.dll"), "wb") as f:
        f.write(b"evil")
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.verify_tree(dst, m)


def test_an_extra_or_missing_file_fails_the_check(tmp_path):
    src = _tree(str(tmp_path / "src"), FILES)
    m = turbosvc.manifest(src)
    dst = str(tmp_path / "dst")
    os.mkdir(dst)
    turbosvc.copy_verified(src, dst, m)
    with open(os.path.join(dst, "_internal", "evil.pyd"), "wb") as f:
        f.write(b"x")
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.verify_tree(dst, m)
    os.remove(os.path.join(dst, "_internal", "evil.pyd"))
    os.remove(os.path.join(dst, "_internal", "base_library.zip"))
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.verify_tree(dst, m)


def _junction(link, target):
    import _winapi
    _winapi.CreateJunction(target, link)


@win
def test_a_junction_in_the_helper_files_is_refused(tmp_path):
    src = _tree(str(tmp_path / "src"), FILES)
    outside = _tree(str(tmp_path / "outside"), {"secret.dll": b"x"})
    _junction(os.path.join(src, "_internal", "more"), outside)
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.manifest(src)
    link = str(tmp_path / "linked-src")
    _junction(link, src)
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.tree_files(link)


@win
def test_rmtree_safe_removes_a_junction_without_following_it(tmp_path):
    target = _tree(str(tmp_path / "keep"), {"precious.txt": b"x"})
    tree = _tree(str(tmp_path / "gone"), {"a.txt": b"x"})
    _junction(os.path.join(tree, "j"), target)
    turbosvc.rmtree_safe(tree)
    assert not os.path.exists(tree) and os.path.exists(os.path.join(target, "precious.txt"))


@win
def test_a_helper_file_is_copied_from_a_handle_nobody_can_write_meanwhile(tmp_path):
    p = _tree(str(tmp_path / "s"), {"f.bin": b"abc"})
    with turbosvc.open_locked(os.path.join(p, "f.bin")) as f:
        with pytest.raises(PermissionError):
            open(os.path.join(p, "f.bin"), "r+b")
        assert f.read() == b"abc"


# ---------- the elevated steps, with a fake service manager and a fake DACL layer ----------
class FakeScm:
    def __init__(self, cfg=None):
        self.cfg, self.sddl, self.privs, self.calls = cfg, None, None, []
        self.state = (turbosvc.STOPPED, 0)

    def config(self):
        return self.cfg

    def create(self, cmd):
        self.calls.append("create")
        self.cfg = turbosvc.ServiceConfig(cmd, turbosvc.SERVICE_DEMAND_START, "LocalSystem", 0x10)

    def change(self, cmd):
        self.calls.append("change")
        self.cfg = turbosvc.ServiceConfig(cmd, turbosvc.SERVICE_DEMAND_START, "LocalSystem", 0x10)

    def describe(self, privs):
        self.privs = tuple(privs)

    def privileges(self):
        return None if self.privs is None else set(self.privs)

    def set_sddl(self, s):
        self.sddl = s

    def get_sddl(self):
        return self.sddl

    def stop(self):
        self.calls.append("stop")

    def delete(self):
        self.calls.append("delete")
        self.cfg = None

    def start(self):
        self.calls.append("start")

    def status(self):
        return self.state


class FakeFs:
    """CreateDirectory with a DACL / SetNamedSecurityInfo need admin rights for an Administrators owner: recorded."""

    def __init__(self, sddl=turbosvc.FOLDER_SDDL):
        self.sddl, self.made, self.applied = sddl, [], []

    def is_reparse(self, path):
        return turbosvc.is_reparse(path)

    def sddl_of(self, path):
        return self.sddl

    def create_dir(self, path, sddl):
        os.mkdir(path)
        self.made.append((path, sddl))

    def apply(self, path, sddl):
        self.applied.append((path, sddl))


def _setup(tmp_path):
    app = tmp_path / "app"
    src = _tree(str(app / turbosvc.USER_DIR), FILES)
    pf = tmp_path / "Program Files"
    pf.mkdir()
    return src, str(pf / turbosvc.DIR_NAME), str(app / "NobadFind.exe")


def test_install_copies_records_and_registers(tmp_path):
    src, root, client = _setup(tmp_path)
    scm, fs = FakeScm(), FakeFs()
    mh = turbosvc.install(src, root, SID, client, scm, fs)
    assert fs.made == [(root, turbosvc.FOLDER_SDDL)]
    turbosvc.verify_tree(os.path.join(root, turbosvc.BIN), turbosvc.manifest(src))
    rec = turbosvc.read_record(root)
    assert rec == turbosvc.Record(SID, client, mh) and mh == turbosvc.manifest_hash(turbosvc.manifest(src))
    assert scm.calls == ["create"]
    assert scm.cfg.command == f'"{os.path.join(root, "bin", turbosvc.EXE)}" --turbo service'
    assert scm.cfg.start == 3 and scm.privs == ("SeChangeNotifyPrivilege", "SeManageVolumePrivilege")
    assert scm.sddl == turbosvc.service_sddl(SID)
    assert not os.path.exists(os.path.join(root, "bin.new"))


def test_an_update_replaces_the_copy_only_after_it_is_verified(tmp_path):
    src, root, client = _setup(tmp_path)
    scm, fs = FakeScm(), FakeFs()
    old = turbosvc.install(src, root, SID, client, scm, fs)
    with open(os.path.join(src, turbosvc.EXE), "wb") as f:
        f.write(b"MZ helper 2")
    fs2 = FakeFs()

    def swap(rel):                    # the user's copy changes mid-update: nothing of the new one is used
        if rel == "_internal\\python311.dll":
            with open(os.path.join(src, rel), "ab") as f:
                f.write(b"!")
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.install(src, root, SID, client, scm, fs2, hook=swap)
    assert fs2.applied == [(root, turbosvc.FOLDER_SDDL)]          # an existing strong folder: DACL set again
    assert turbosvc.read_record(root).manifest == old              # still the old, verified copy and record
    with open(os.path.join(root, "bin", turbosvc.EXE), "rb") as f:
        assert f.read() == b"MZ helper"
    new = turbosvc.install(src, root, SID, client, scm, FakeFs())
    assert new != old and turbosvc.read_record(root).manifest == new
    assert scm.calls == ["create", "stop", "stop", "change"]


def test_install_refuses_a_weak_or_linked_folder(tmp_path):
    src, root, client = _setup(tmp_path)
    os.mkdir(root)
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, root, SID, client, FakeScm(), FakeFs(sddl="O:BAD:(A;OICI;FA;;;BU)"))
    assert os.listdir(root) == []


@win
def test_install_refuses_a_junction_at_the_protected_folder(tmp_path):
    src, root, client = _setup(tmp_path)
    target = str(tmp_path / "user-writable")
    os.mkdir(target)
    _junction(root, target)
    scm = FakeScm()
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, root, SID, client, scm, FakeFs())
    assert os.listdir(target) == [] and scm.calls == []


@win
def test_install_refuses_when_program_files_is_a_junction(tmp_path):
    src, _root, client = _setup(tmp_path)
    real = str(tmp_path / "real")
    os.mkdir(real)
    pf = str(tmp_path / "PF-link")
    _junction(pf, real)
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, os.path.join(pf, turbosvc.DIR_NAME), SID, client, FakeScm(), FakeFs())
    assert os.listdir(real) == []


def test_install_never_touches_another_programs_service(tmp_path):
    src, root, client = _setup(tmp_path)
    scm = FakeScm(turbosvc.ServiceConfig('"C:\\Other\\svc.exe"', 2, "LocalSystem", 0x10))
    with pytest.raises(turbosvc.NotOurs):
        turbosvc.install(src, root, SID, client, scm, FakeFs())
    assert not os.path.exists(root) and scm.calls == []
    with pytest.raises(turbosvc.NotOurs):
        turbosvc.remove(root, scm, FakeFs())
    assert scm.calls == []


def test_install_refuses_bad_input(tmp_path):
    src, root, client = _setup(tmp_path)
    with pytest.raises(ValueError):
        turbosvc.install(src, root, "S-1-5-18", client, FakeScm(), FakeFs())
    os.remove(os.path.join(src, turbosvc.EXE))
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, root, SID, client, FakeScm(), FakeFs())


def test_remove_stops_deletes_and_clears_the_folder(tmp_path):
    src, root, client = _setup(tmp_path)
    scm = FakeScm()
    turbosvc.install(src, root, SID, client, scm, FakeFs())
    turbosvc.remove(root, scm, FakeFs())
    assert scm.calls[-2:] == ["stop", "delete"] and scm.cfg is None and not os.path.exists(root)
    turbosvc.remove(root, scm, FakeFs())                          # nothing there: nothing to do


@win
def test_remove_unlinks_a_junction_at_the_folder_without_following(tmp_path):
    _src, root, _client = _setup(tmp_path)
    target = _tree(str(tmp_path / "keep"), {"precious.txt": b"x"})
    _junction(root, target)
    turbosvc.remove(root, FakeScm(), FakeFs())
    assert not os.path.lexists(root) and os.path.exists(os.path.join(target, "precious.txt"))


# ---------- the record and update-needed detection ----------
def test_the_record_is_checked_field_by_field(tmp_path):
    ok = {"version": 1, "user_sid": SID, "client_image": "C:\\Users\\me\\NobadFind.exe", "manifest": "a" * 64}
    assert turbosvc.parse_record(ok) == turbosvc.Record(SID, ok["client_image"], "a" * 64)
    for bad in ({"version": 2}, {"user_sid": "S-1-5-18"}, {"user_sid": SID + "x"}, {"client_image": "NobadFind.exe"},
                {"client_image": "C:\\x\\calc.bat"}, {"manifest": "A" * 64}, {"manifest": "a" * 63}):
        assert turbosvc.parse_record(dict(ok, **bad)) is None, bad
    assert turbosvc.parse_record([ok]) is None
    assert turbosvc.read_record(str(tmp_path)) is None
    (tmp_path / turbosvc.RECORD).write_text("{not json")
    assert turbosvc.read_record(str(tmp_path)) is None


def test_helper_status():
    img = "C:\\Users\\me\\AppData\\Local\\Programs\\NOBAD Find\\NobadFind.exe"
    cmd = '"C:\\Program Files\\NOBAD Find Turbo\\bin\\NobadFindTurbo.exe" --turbo service'
    rec = turbosvc.Record(SID, img, "b" * 64)
    st = turbosvc.helper_status
    assert st(None, None, "b" * 64, SID, img, cmd)[0] == "not_installed"
    assert st(rec, cmd, "b" * 64, SID, img.upper(), cmd) == ("installed", "")
    assert st(rec, cmd, "c" * 64, SID, img, cmd) == ("needs_update", "NOBAD Find was updated.")
    assert st(rec, cmd, None, SID, img, cmd)[0] == "needs_update"
    assert st(rec, cmd, "b" * 64, OTHER, img, cmd) == ("not_installed", turbosvc.OTHER_ACCOUNT)   # not ours
    assert "another folder" in st(rec, cmd, "b" * 64, SID, "D:\\Find\\NobadFind.exe", cmd)[1]
    assert st(rec, None, "b" * 64, SID, img, cmd)[0] == "needs_update"
    assert st(None, cmd, "b" * 64, SID, img, cmd)[0] == "needs_update"
    assert st(rec, '"C:\\evil.exe" --turbo service', "b" * 64, SID, img, cmd)[0] == "needs_update"


def _helper_setup(tmp_path, monkeypatch, scm, codes=()):
    from nobadfind.rpc import server as srv
    src, root, client = _setup(tmp_path)
    monkeypatch.setattr(turbosvc, "protected_root", lambda: root)
    monkeypatch.setattr(turbosvc, "user_helper_dir", lambda app_dir=None: src)
    monkeypatch.setattr(srv, "user_sid", lambda: SID)
    monkeypatch.setattr(ntfs, "own_image", lambda: client)
    asked = []
    answers = list(codes)

    def elevate(argv):
        asked.append(argv)
        return answers.pop(0) if answers else 0
    hs = turbo.HelperSetup(scm=scm, elevate=elevate, frozen=True)
    return hs, src, root, client, asked


def test_update_needed_when_the_shipped_helper_changes(tmp_path, monkeypatch):
    scm = FakeScm()
    hs, src, root, client, _asked = _helper_setup(tmp_path, monkeypatch, scm)
    assert hs.status()[0] == "not_installed"
    turbosvc.install(src, root, SID, client, scm, FakeFs())
    hs.forget()
    assert hs.status() == ("installed", "")
    with open(os.path.join(src, turbosvc.EXE), "wb") as f:      # a new NOBAD Find came with a new helper
        f.write(b"MZ helper 2")
    fresh = turbo.HelperSetup(scm=scm, elevate=lambda a: 0, frozen=True)
    assert fresh.status() == ("needs_update", "NOBAD Find was updated.")


def test_another_accounts_service_reads_as_not_installed_here(tmp_path, monkeypatch):
    class Denied(FakeScm):
        def config(self):
            raise PermissionError(5, "access denied")
    hs, *_ = _helper_setup(tmp_path, monkeypatch, Denied())
    st, why = hs.status()
    assert st == "not_installed" and why == turbosvc.OTHER_ACCOUNT


def test_the_elevated_steps_run_the_helper_with_fixed_words(tmp_path, monkeypatch):
    hs, src, _root, _client, asked = _helper_setup(tmp_path, monkeypatch, FakeScm(), codes=[0, None, 8])
    hs.install()
    assert asked == [[os.path.join(src, turbosvc.EXE), "--turbo", "install"]]
    with pytest.raises(turbo.Declined):
        hs.remove()
    with pytest.raises(turbo.SetupFailed) as e:
        hs.install()
    assert e.value.code == 8 and "changed while they were copied" in e.value.sentence
    os.remove(os.path.join(src, turbosvc.EXE))
    with pytest.raises(turbo.SetupFailed):
        hs.install()


def test_from_source_nothing_is_ever_installed(tmp_path, monkeypatch):
    asked = []
    hs = turbo.HelperSetup(scm=FakeScm(), elevate=lambda a: asked.append(a), frozen=False)
    assert hs.kind == "dev" and hs.status() == ("not_installed", "")
    with pytest.raises(turbo.DevOnly):
        hs.install()
    hs.remove()
    assert asked == [] and turbo.remove_on_uninstall(hs) is True and asked == []


def test_uninstall_removes_the_helper_once(tmp_path, monkeypatch):
    scm = FakeScm()
    hs, src, root, client, asked = _helper_setup(tmp_path, monkeypatch, scm, codes=[None, 0])
    assert turbo.remove_on_uninstall(hs) is True and asked == []         # nothing set up: no prompt
    turbosvc.install(src, root, SID, client, scm, FakeFs())
    assert turbo.remove_on_uninstall(hs) is False                        # No at the prompt
    assert turbo.remove_on_uninstall(hs) is True
    assert [a[-1] for a in asked] == ["remove", "remove"]


def test_uninstall_leaves_another_accounts_helper_alone(tmp_path, monkeypatch):
    scm = FakeScm()
    hs, src, root, client, asked = _helper_setup(tmp_path, monkeypatch, scm)
    turbosvc.install(src, root, OTHER, client, scm, FakeFs())
    assert turbo.remove_on_uninstall(hs) is True and asked == []

    class Denied(FakeScm):
        def config(self):
            raise PermissionError(5, "access denied")
    hs.scm = Denied()
    assert turbo.remove_on_uninstall(hs) is True and asked == []


# ---------- the engine: one prompt to set up, none at start ----------
class FakeSetup:
    kind = "service"

    def __init__(self, st="not_installed", answers=()):
        self.st, self.answers, self.calls = st, list(answers), []
        self.scm = FakeScm()

    def status(self):
        return self.st, ""

    def _answer(self):
        a = self.answers.pop(0) if self.answers else 0
        if a is None:
            raise turbo.Declined()
        if a:
            raise turbo.SetupFailed(a)

    def install(self):
        self.calls.append("install")
        self._answer()
        self.st = "installed"

    def remove(self):
        self.calls.append("remove")
        self._answer()
        self.st = "not_installed"


class Link:
    def __init__(self, t):
        self.sent, self.alive, self.pid = [], True, 4242
        t.on_message({"t": "hello", "protocol": ntfs.PROTOCOL, "pid": 4242, "volumes": []})

    def send(self, m):
        self.sent.append(m)

    def close(self):
        self.alive = False


@pytest.fixture
def eng(tmp_path):
    from test_turbo import DRIVE, PROF, Ix
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = Settings(str(tmp_path / "s.json"))
    setup = FakeSetup()
    launched = []
    t = turbo.Turbo(st, s, Ix([PROF]), ntfs_drive=lambda d: True,
                    drives=lambda: [{"root": DRIVE, "type": "fixed", "label": ""}], setup=setup)

    def launch():
        launched.append(Link(t))
        return launched[-1]
    t._launch = launch
    yield t, st, setup, launched
    s.close()


def test_turning_on_sets_up_once_then_starts(eng):
    t, st, setup, launched = eng
    r = t.turn_on()
    assert r == {"ok": True, "error": ""} and setup.calls == ["install"] and len(launched) == 1
    assert st.get("turbo") is True and t.state()["helper"] == "installed"


def test_next_engine_start_asks_nothing(eng):
    t, st, setup, launched = eng
    setup.st = "installed"
    st.update({"turbo": True})
    t.ensure()
    assert setup.calls == [] and len(launched) == 1 and t.running()


def test_a_helper_needing_an_update_waits_for_the_users_ok(eng):
    t, st, setup, launched = eng
    setup.st = "needs_update"
    st.update({"turbo": True})
    t.ensure()
    s = t.state()
    assert setup.calls == [] and launched == [] and st.get("turbo") is True       # no prompt, still on
    assert s["helper"] == "needs_update" and s["error"] == turbo.NEEDS_UPDATE and not s["running"]
    r = t.helper_action("update")                                                 # the user's OK
    assert r["ok"] and setup.calls == ["install"] and len(launched) == 1 and t.running()


def test_update_while_off_only_updates(eng):
    t, st, setup, launched = eng
    setup.st = "needs_update"
    assert t.helper_action("update")["ok"] and setup.calls == ["install"] and launched == []
    assert st.get("turbo") is False


def test_no_at_the_setup_prompt_leaves_it_off(eng):
    t, st, setup, launched = eng
    setup.answers = [None]
    r = t.turn_on()
    assert not r["ok"] and r["error"] == turbo.DECLINED and launched == [] and st.get("turbo") is False


def test_a_refused_setup_says_why(eng):
    t, _st, setup, launched = eng
    setup.answers = [9]
    r = t.turn_on()
    assert not r["ok"] and "NOBADFindTurbo" in r["error"] and launched == []


def test_turning_off_removes_the_helper_and_no_keeps_it(eng):
    t, st, setup, launched = eng
    t.turn_on()
    setup.answers = [None]
    r = t.turn_off()
    assert r == {"ok": True, "error": turbo.KEPT} and not launched[0].alive and st.get("turbo") is False
    assert t.state()["helper"] == "installed"
    r = t.helper_action("remove")
    assert r == {"ok": True, "error": ""} and setup.calls == ["install", "remove", "remove"]
    assert t.state()["helper"] == "not_installed"
    with pytest.raises(ValueError):
        t.helper_action("delete")


# ---------- the pipe, for real (no elevation) ----------
def _pipe_name():
    return rf"\\.\pipe\NOBADFind-test-svc-{os.getpid()}-{threading.get_ident()}"


@pytest.fixture
def svc_pipe():
    from nobadfind.rpc import server as srv
    sid = srv.user_sid()
    name = _pipe_name()
    h = turbosvc.make_server_pipe(name, turbosvc.pipe_sddl(sid))
    yield name, h, sid
    ntfs._k32().CloseHandle(h)


@win
def test_the_service_pipe_dacl(svc_pipe):
    _name, h, sid = svc_pipe
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.GetSecurityInfo.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    a.GetSecurityInfo.restype = wintypes.DWORD
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    assert a.GetSecurityInfo(h, 6, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(sd)) == 0
    d = turbosvc.sd_to_sddl(sd, 4)
    ctypes.windll.kernel32.LocalFree(sd)
    flags, entries = turbosvc.aces(turbosvc.split_sddl(d)["D"])
    assert flags.startswith("P")
    allows = [e for e in entries if e[0] == "A"]
    assert len(allows) == 1 and turbosvc.rights(allows[0][2]) == turbosvc.PIPE_RIGHTS
    assert _sid_of(allows[0][5]) == sid               # SDDL may write an account as an alias (LA on CI runners)
    assert any(e[0] == "D" and e[5] == "NU" for e in entries)
    sd = ctypes.c_void_p()
    assert a.GetSecurityInfo(h, 6, 0x10, None, None, None, None, ctypes.byref(sd)) == 0     # the label
    label = turbosvc.sd_to_sddl(sd, 0x10)
    ctypes.windll.kernel32.LocalFree(sd)
    assert "ML;;NWNR;;;ME" in label


def _sid_of(trustee):
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    a.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    p = ctypes.c_void_p()
    assert a.ConvertStringSidToSidW(trustee, ctypes.byref(p))
    out = wintypes.LPWSTR()
    assert a.ConvertSidToStringSidW(p, ctypes.byref(out))
    value = out.value
    ctypes.windll.kernel32.LocalFree(p)
    ctypes.windll.kernel32.LocalFree(out)
    return value


@win
def test_the_pipe_gives_no_more_than_data_rights(svc_pipe):
    name, _h, _sid = svc_pipe
    k = ntfs._k32()
    c = k.CreateFileW(name, 0x80000000 | 0x40000000, 0, None, 3, 0, None)      # GENERIC_READ | GENERIC_WRITE
    assert not c or c == ntfs.INVALID_HANDLE
    assert ctypes.get_last_error() == 5                                         # access denied
    c = turbosvc.open_client_pipe(name, 2)
    k.CloseHandle(c)


@win
def test_only_one_pipe_of_that_name(svc_pipe):
    name, _h, sid = svc_pipe
    with pytest.raises(OSError):
        turbosvc.make_server_pipe(name, turbosvc.pipe_sddl(sid))


@win
def test_both_ends_identify_each_other_on_a_real_pipe(svc_pipe, tmp_path):
    name, h, sid = svc_pipe
    c = turbosvc.open_client_pipe(name, 2)
    try:
        assert ntfs._wait_connect(h, 2)
        me, sess = os.getpid(), ntfs.session_of(os.getpid())
        # the engine's check of the server
        assert ntfs.server_ok(c, me, sess)
        assert not ntfs.server_ok(c, me + 4, sess) and not ntfs.server_ok(c, me, sess + 1)
        # the service's check of the client, after its hi
        ntfs._Pipe(c).send({"t": "hi", "protocol": ntfs.PROTOCOL})
        assert ntfs.Lines(ntfs.HI_MAX).feed(ntfs._Pipe(h).read()) == [{"t": "hi", "protocol": ntfs.PROTOCOL}]
        ident, token, hp = ntfs.client_identity(h)
        try:
            assert ident.pid == me and ident.sid == sid == ident.process_sid
            assert ident.pipe_session == ident.token_session == ident.process_session == sess
            assert turbosvc.same_path(ident.image, ntfs.own_image())
            assert not ident.app_container and not ident.restricted
            from nobadfind import winapi
            if not winapi.is_admin():
                assert not ident.elevated and ident.integrity == ntfs.MEDIUM
            # the client's own token is what AccessCheck uses: this user can list their own folder
            assert ntfs.Lister(token)(str(tmp_path)) is True
            with pytest.raises(PermissionError):
                ntfs.check_client(ident, OTHER, ntfs.own_image())
            with pytest.raises(PermissionError):
                ntfs.check_client(ident, sid, "C:\\Windows\\notepad.exe")
            with pytest.raises(PermissionError):
                ntfs.check_client(ident, sid, ntfs.own_image(), pid=me + 4)
            if ident.active and not ident.elevated:
                assert ntfs.check_client(ident, sid, ntfs.own_image(), pid=me)
        finally:
            ntfs._k32().CloseHandle(token)
            ntfs._k32().CloseHandle(hp)
    finally:
        ntfs._k32().CloseHandle(c)


@win
def test_the_helper_serves_a_checked_client_and_drops_an_unchecked_one(svc_pipe, monkeypatch):
    """serve_client end to end on a real pipe: hi, the client checks, hello, config, stop."""
    from nobadfind import winapi
    name, h, sid = svc_pipe
    monkeypatch.setattr(winapi, "worker_priority", lambda on: None)          # not this test process's priority
    ident_probe = {}

    def run(image, box):
        try:
            box["r"] = ntfs.serve_client(h, sid, image, pid=os.getpid(), end=lambda code: box.setdefault("end", code))
        except Exception as e:
            box["e"] = e
    c = turbosvc.open_client_pipe(name, 2)
    assert ntfs._wait_connect(h, 2)
    box = {}
    th = threading.Thread(target=run, args=("C:\\Windows\\notepad.exe", box), daemon=True)
    th.start()
    ntfs._Pipe(c).send({"t": "hi", "protocol": ntfs.PROTOCOL})
    th.join(5)
    assert isinstance(box.get("e"), PermissionError)                         # not the recorded program: refused
    ntfs._k32().CloseHandle(c)
    ident_probe["active"] = ntfs.session_active(ntfs.session_of(os.getpid()))
    if not ident_probe["active"] or winapi.is_admin():
        pytest.skip("needs an active, unelevated session")
    name += "-2"
    h = turbosvc.make_server_pipe(name, turbosvc.pipe_sddl(sid))
    c = turbosvc.open_client_pipe(name, 2)
    assert ntfs._wait_connect(h, 2)
    box = {}
    th = threading.Thread(target=run, args=(ntfs.own_image(), box), daemon=True)
    th.start()
    cp = ntfs._Pipe(c)
    cp.send({"t": "hi", "protocol": ntfs.PROTOCOL})
    got = ntfs.Lines().feed(cp.read())
    assert got and got[0]["t"] == "hello" and got[0]["protocol"] == ntfs.PROTOCOL
    cp.send({"t": "config", "roots": [], "exclude": []})
    cp.send({"t": "stop"})
    th.join(5)
    assert box.get("r") == 0 and "e" not in box
    ntfs._k32().CloseHandle(c)
    ntfs._k32().CloseHandle(h)


def test_the_helper_wants_hi_first():
    class P:
        def __init__(self):
            self.reads = [ntfs.encode({"t": "config", "roots": []})]

        def read(self):
            return self.reads.pop(0) if self.reads else b""
    import nobadfind.ntfs as n
    orig = n._Pipe
    n._Pipe = lambda h: P()
    try:
        with pytest.raises(ValueError):
            n.serve_client(None, SID, "C:\\x.exe", end=lambda code: None)
    finally:
        n._Pipe = orig


def _ident(**kw):
    base = dict(pid=10, pipe_session=1, token_session=1, process_session=1, sid=SID, process_sid=SID,
                image="C:\\Users\\me\\NobadFind.exe", elevated=False, integrity=ntfs.MEDIUM, app_container=False,
                restricted=False, active=True, created=1, alive=True)
    base.update(kw)
    return ntfs.Identity(**base)


@pytest.mark.parametrize("bad", [
    {"sid": OTHER}, {"process_sid": OTHER}, {"process_sid": ""}, {"pipe_session": 0, "token_session": 0,
                                                                   "process_session": 0},
    {"token_session": 2}, {"process_session": 2}, {"active": False}, {"elevated": True}, {"integrity": 0x1000},
    {"integrity": -1}, {"app_container": True}, {"restricted": True}, {"image": "C:\\Users\\me\\evil.exe"},
    {"alive": False},
])
def test_check_client_fails_closed(bad):
    assert ntfs.check_client(_ident(), SID, "c:\\users\\ME\\NobadFind.exe")
    with pytest.raises(PermissionError):
        ntfs.check_client(_ident(**bad), SID, "C:\\Users\\me\\NobadFind.exe")


def test_check_client_needs_a_recorded_user_sid():
    with pytest.raises(PermissionError):
        ntfs.check_client(_ident(sid="", process_sid=""), "", "C:\\Users\\me\\NobadFind.exe")


@win
def test_the_engine_refuses_a_pipe_not_served_by_the_service(svc_pipe, monkeypatch):
    """Someone else (here: this test process) holds the service's pipe name: the engine checks the server's pid
    against the service manager's and closes it."""
    name, h, sid = svc_pipe
    root = "C:\\Program Files\\NOBAD Find Turbo"
    monkeypatch.setattr(turbosvc, "protected_root", lambda: root)
    scm = FakeScm(turbosvc.ServiceConfig(turbosvc.service_command(root), 3, "LocalSystem", 0x10))
    scm.state = (turbosvc.RUNNING, os.getpid() + 4)                   # the real service's pid: not this process
    monkeypatch.setattr(turbosvc, "service_pipe_name", lambda s: name)
    with pytest.raises(PermissionError):
        turbo.PipeLink._connect_service(scm, wait_s=2)
    assert scm.calls == ["start"]


def test_the_engine_never_starts_a_service_that_isnt_the_protected_copy(monkeypatch):
    root = "C:\\Program Files\\NOBAD Find Turbo"
    monkeypatch.setattr(turbosvc, "protected_root", lambda: root)
    scm = FakeScm(turbosvc.ServiceConfig('"C:\\Users\\me\\evil.exe" --turbo service', 3, "LocalSystem", 0x10))
    with pytest.raises(PermissionError):
        turbo.PipeLink._connect_service(scm, wait_s=1)
    assert scm.calls == []


def test_the_service_refuses_to_run_outside_its_protected_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(turbosvc, "protected_root", lambda: str(tmp_path))
    monkeypatch.setattr(ntfs, "own_image", lambda: "C:\\Users\\me\\turbo\\NobadFindTurbo.exe")
    with pytest.raises(PermissionError):
        ntfs._service(lambda code: None)


@win
def test_the_service_refuses_a_weak_folder(monkeypatch, tmp_path):
    root = str(tmp_path)
    os.mkdir(os.path.join(root, "bin"))
    monkeypatch.setattr(turbosvc, "protected_root", lambda: root)
    monkeypatch.setattr(ntfs, "own_image", lambda: os.path.join(root, "bin", turbosvc.EXE))
    monkeypatch.setattr(sys, "_MEIPASS", os.path.join(root, "bin", "_internal"), raising=False)
    monkeypatch.setattr(sys, "path", [os.path.join(root, "bin", "_internal")])
    with pytest.raises(PermissionError, match="isn't protected"):      # a folder the user made: not protected
        ntfs._service(lambda code: None)


# ---------- hardening (turbo security review, 2026-11-21) ----------
def test_check_client_wants_the_process_that_connected_alive():
    """A pid is only a number: the process behind it must still run and be older than the connection (a client
    that connected and exited could have its pid taken by a new NobadFind.exe, which would pass the image check)."""
    image = "C:\\Users\\me\\NobadFind.exe"
    assert ntfs.check_client(_ident(created=100, alive=True), SID, image, connected_at=200)
    with pytest.raises(PermissionError):
        ntfs.check_client(_ident(alive=False), SID, image, connected_at=200)
    with pytest.raises(PermissionError):
        ntfs.check_client(_ident(created=300), SID, image, connected_at=200)
    with pytest.raises(PermissionError):
        ntfs.check_client(_ident(created=0), SID, image, connected_at=200)


def test_serve_client_checks_the_client_against_when_it_connected(monkeypatch):
    class P:
        def __init__(self, h):
            self.reads = [ntfs.encode({"t": "hi", "protocol": ntfs.PROTOCOL})]

        def read(self):
            return self.reads.pop(0) if self.reads else b""
    monkeypatch.setattr(ntfs, "_Pipe", P)
    monkeypatch.setattr(ntfs, "_serve", lambda *a, **kw: "served")
    born = {"t": 0}
    monkeypatch.setattr(ntfs, "client_identity", lambda h: (_ident(created=born["t"]), None, None))
    image = "C:\\Users\\me\\NobadFind.exe"
    born["t"] = ntfs.filetime_now() + 10 ** 9                 # the process behind the pid is newer than the connect
    with pytest.raises(PermissionError):
        ntfs.serve_client(None, SID, image, end=lambda code: None)
    born["t"] = ntfs.filetime_now() - 10 ** 7
    assert ntfs.serve_client(None, SID, image, end=lambda code: None) == "served"


@win
def test_client_identity_says_when_the_client_started_and_that_it_runs(svc_pipe):
    name, h, _sid = svc_pipe
    c = turbosvc.open_client_pipe(name, 2)
    try:
        assert ntfs._wait_connect(h, 2)
        ntfs._Pipe(c).send({"t": "hi", "protocol": ntfs.PROTOCOL})
        ntfs._Pipe(h).read()
        ident, token, hp = ntfs.client_identity(h)
        try:
            assert ident.alive and 0 < ident.created == ntfs.process_created(ntfs._k32().GetCurrentProcess())
            assert ident.created <= ntfs.filetime_now()
        finally:
            ntfs._k32().CloseHandle(token)
            ntfs._k32().CloseHandle(hp)
    finally:
        ntfs._k32().CloseHandle(c)


@win
def test_the_elevated_step_refuses_a_parent_younger_than_itself(monkeypatch):
    """The parent's pid comes from a process snapshot: if it was reused, the 'parent' started after this process."""
    me = ntfs._k32().GetCurrentProcess()
    monkeypatch.setattr(ntfs, "process_created", lambda h: 100 if h == me else 200)
    with pytest.raises(PermissionError, match="started after"):
        ntfs._parent_user()


def test_install_checks_the_services_privileges_were_cut(tmp_path):
    src, root, client = _setup(tmp_path)

    class Ignores(FakeScm):
        def describe(self, privs):
            pass                                                  # the privilege list didn't take
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, root, SID, client, Ignores(), FakeFs())

    class More(FakeScm):
        def describe(self, privs):
            self.privs = tuple(privs) + ("SeDebugPrivilege",)
    with pytest.raises(turbosvc.Unsafe):
        turbosvc.install(src, root, SID, client, More(), FakeFs())


@win
def test_the_service_manager_reads_a_services_required_privileges():
    """Read-only and unelevated: EventLog's required privileges (what `sc.exe qprivs EventLog` shows)."""
    privs = turbosvc.Scm("EventLog").privileges()
    assert "SeChangeNotifyPrivilege" in privs and "SeImpersonatePrivilege" in privs
    assert turbosvc.Scm("NOBADFind-no-such-service").privileges() is None


def test_privileges_ok():
    assert turbosvc.privileges_ok({"SeChangeNotifyPrivilege", "SeManageVolumePrivilege"})
    assert turbosvc.privileges_ok(set())
    for p in ("SeDebugPrivilege", "SeTcbPrivilege", "SeImpersonatePrivilege", "SeBackupPrivilege",
              "SeRestorePrivilege", "SeTakeOwnershipPrivilege", "SeLoadDriverPrivilege",
              "SeAssignPrimaryTokenPrivilege", "SeCreateTokenPrivilege"):
        assert not turbosvc.privileges_ok({"SeChangeNotifyPrivilege", p})


@win
def test_the_privileges_in_this_process_token():
    privs = ntfs.own_privileges()
    assert "SeChangeNotifyPrivilege" in privs and all(p.startswith("Se") for p in privs)


def _service_env(monkeypatch, tmp_path, privs=("SeChangeNotifyPrivilege", "SeManageVolumePrivilege")):
    root = str(tmp_path)
    binp = os.path.join(root, "bin")
    monkeypatch.setattr(turbosvc, "protected_root", lambda: root)
    monkeypatch.setattr(ntfs, "own_image", lambda: os.path.join(binp, turbosvc.EXE))
    monkeypatch.setattr(sys, "_MEIPASS", os.path.join(binp, "_internal"), raising=False)
    monkeypatch.setattr(sys, "path", [os.path.join(binp, "_internal", "base_library.zip"),
                                      os.path.join(binp, "_internal")])
    monkeypatch.setattr(turbosvc, "is_reparse", lambda p: False)
    monkeypatch.setattr(turbosvc, "path_sddl", lambda p: turbosvc.FOLDER_SDDL)
    monkeypatch.setattr(ntfs, "own_token_sid", lambda: (turbosvc.SY, 1))
    monkeypatch.setattr(ntfs, "own_privileges", lambda: set(privs))
    reached = []

    def read_record(r):
        reached.append(r)
        return None                                               # ends the service right after its checks
    monkeypatch.setattr(turbosvc, "read_record", read_record)
    return root, reached


def test_the_service_runs_its_checks_then_reads_the_record(monkeypatch, tmp_path):
    root, reached = _service_env(monkeypatch, tmp_path)
    with pytest.raises(PermissionError, match="no record"):
        ntfs._service(lambda code: None)
    assert reached == [root]


def test_the_service_refuses_privileges_it_shouldnt_have(monkeypatch, tmp_path):
    _root, reached = _service_env(monkeypatch, tmp_path, privs=("SeChangeNotifyPrivilege", "SeImpersonatePrivilege"))
    with pytest.raises(PermissionError, match="privileges"):
        ntfs._service(lambda code: None)
    assert reached == []


@pytest.mark.parametrize("where", ["meipass", "path"])
def test_the_service_refuses_code_from_outside_its_protected_folder(monkeypatch, tmp_path, where):
    """A one-file build unpacks into a temp folder, and a path entry outside bin could import from anywhere: the
    service runs only as a one-folder build whose code is all in bin."""
    _root, reached = _service_env(monkeypatch, tmp_path)
    temp = os.path.join(str(tmp_path.parent), "_MEI1234")
    if where == "meipass":
        monkeypatch.setattr(sys, "_MEIPASS", temp)
    else:
        monkeypatch.setattr(sys, "path", sys.path + [temp])
    with pytest.raises(PermissionError, match="protected folder"):
        ntfs._service(lambda code: None)
    assert reached == []


def test_code_is_in_bin():
    b = "C:\\Program Files\\NOBAD Find Turbo\\bin"
    assert ntfs.code_is_in(b, b + "\\_internal", [b + "\\_internal\\base_library.zip", b + "\\_internal"])
    assert not ntfs.code_is_in(b, None, [b + "\\_internal"])                     # not a frozen build
    assert not ntfs.code_is_in(b, "C:\\Windows\\Temp\\_MEI1", [b + "\\_internal"])
    assert not ntfs.code_is_in(b, b + "\\_internal", [b + "\\_internal", ""])     # the current folder
    assert not ntfs.code_is_in(b, b + "\\_internal", [b + "x\\_internal"])       # a lookalike sibling
    assert not ntfs.code_is_in(b, b + "\\..\\..\\x", [b + "\\_internal"])


def test_a_failed_install_leaves_no_half_copy(tmp_path):
    src, root, client = _setup(tmp_path)

    def swap(rel):
        if rel == "_internal\\python311.dll":
            with open(os.path.join(src, rel), "ab") as f:
                f.write(b"!")
    with pytest.raises(turbosvc.Mismatch):
        turbosvc.install(src, root, SID, client, FakeScm(), FakeFs(), hook=swap)
    assert not os.path.exists(os.path.join(root, "bin.new"))
