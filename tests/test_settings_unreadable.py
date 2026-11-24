"""S0: a settings file that couldn't be read is never replaced by the defaults."""
import json
import os

from nobadfind import settings as settings_mod

RAW = {"settings_rev": 3, "performance_goal": "quiet", "power": "balanced", "roots": ["C:\\Work"], "scope": "custom",
       "exclude": ["C:\\Work\\private"], "hotkey": "ctrl+alt+f"}


def _write(tmp_path, body=None):
    p = tmp_path / "s.json"
    p.write_bytes(body if body is not None else json.dumps(RAW).encode("utf-8"))
    return p


def _asides(tmp_path):
    return sorted(n for n in os.listdir(tmp_path) if n.startswith("s.json.unreadable-"))


def _lock_once(monkeypatch, path, times=1):
    """The first `times` reads of settings.json fail as if an antivirus held it."""
    real = open
    left = [times]

    def fake(p, mode="r", *a, **kw):
        if str(p) == str(path) and "r" in mode and left[0] > 0:
            left[0] -= 1
            raise PermissionError(13, "in use", str(p))
        return real(p, mode, *a, **kw)
    monkeypatch.setattr(settings_mod, "open", fake, raising=False)


def test_a_locked_file_keeps_every_key_when_the_lock_is_gone_by_the_next_save(tmp_path, monkeypatch):
    p = _write(tmp_path)
    _lock_once(monkeypatch, p)
    st = settings_mod.Settings(str(p))
    assert st.read_failed
    st.update({"hotkey": "ctrl+alt+k"})
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["hotkey"] == "ctrl+alt+k"
    assert saved["roots"] == ["C:\\Work"] and saved["scope"] == "custom" and saved["exclude"] == ["C:\\Work\\private"]
    assert saved["performance_goal"] == "quiet"
    assert _asides(tmp_path) == []
    assert not st.read_failed and st.get("roots") == ["C:\\Work"]


def test_a_corrupt_file_is_set_aside_byte_for_byte_and_a_new_one_written(tmp_path):
    body = b'{"roots": ["C:\\\\Work"], "hotkey": '
    p = _write(tmp_path, body)
    st = settings_mod.Settings(str(p))
    st.update({"theme": "light"})
    asides = _asides(tmp_path)
    assert len(asides) == 1 and (tmp_path / asides[0]).read_bytes() == body
    assert json.loads(p.read_text(encoding="utf-8"))["theme"] == "light"
    assert "settings file" in st.notice and asides[0] in st.notice
    st.update({"theme": "dark"})
    assert len(_asides(tmp_path)) == 1                                  # only the first save sets it aside


def test_a_file_that_is_not_an_object_is_treated_like_a_corrupt_one(tmp_path):
    body = b'["roots", "hotkey"]'
    p = _write(tmp_path, body)
    st = settings_mod.Settings(str(p))
    st.update({"theme": "light"})
    asides = _asides(tmp_path)
    assert len(asides) == 1 and (tmp_path / asides[0]).read_bytes() == body
    assert json.loads(p.read_text(encoding="utf-8"))["theme"] == "light"


def test_when_the_move_fails_too_nothing_is_written_and_the_next_save_does_it(tmp_path, monkeypatch):
    body = b"{ not json"
    p = _write(tmp_path, body)
    st = settings_mod.Settings(str(p))
    real = os.replace

    def locked(src, dst):
        if str(src) == str(p):
            raise PermissionError(13, "in use")
        return real(src, dst)
    monkeypatch.setattr(settings_mod.os, "replace", locked)
    st.update({"theme": "light"})                                       # no error: kept in memory
    assert p.read_bytes() == body and _asides(tmp_path) == []
    assert st.get("theme") == "light"
    monkeypatch.setattr(settings_mod.os, "replace", real)
    st.update({"hotkey": "ctrl+alt+k"})
    assert len(_asides(tmp_path)) == 1 and (tmp_path / _asides(tmp_path)[0]).read_bytes() == body
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["theme"] == "light" and saved["hotkey"] == "ctrl+alt+k"


def test_forget_is_guarded_too(tmp_path, monkeypatch):
    p = _write(tmp_path)
    _lock_once(monkeypatch, p)
    st = settings_mod.Settings(str(p))
    assert st.forget(str(tmp_path / "secret.txt")) == "ok"
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["roots"] == ["C:\\Work"] and saved["hotkey"] == "ctrl+alt+f"
    assert "C:\\Work\\private" in saved["exclude"]                      # the user's own entry survived
    assert str(tmp_path / "secret.txt") in st.get("exclude")
    assert _asides(tmp_path) == []


def test_mark_forgotten_is_guarded_too(tmp_path, monkeypatch):
    p = _write(tmp_path)
    _lock_once(monkeypatch, p)
    st = settings_mod.Settings(str(p))
    st._forgot_read = False                                             # as if forgotten.dat couldn't be read
    monkeypatch.setattr(st, "_load_forgotten", lambda: None)
    st.mark_forgotten(["C:\\Work\\private"])
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["roots"] == ["C:\\Work"] and saved["hotkey"] == "ctrl+alt+f" and saved["scope"] == "custom"
    assert _asides(tmp_path) == []


def test_a_fresh_install_saves_normally(tmp_path):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    assert not st.read_failed
    st.update({"theme": "light"})
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["theme"] == "light"
    assert _asides(tmp_path) == [] and st.notice == ""


def test_remove_aside_copies_deletes_only_the_settings_copies(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "s.json.unreadable-20261123-101010").write_bytes(b"old")
    (tmp_path / "other.txt").write_text("x")
    st = settings_mod.Settings(str(p))
    assert st.remove_aside_copies() == 1
    assert os.listdir(tmp_path).count("other.txt") == 1 and _asides(tmp_path) == []
    assert p.exists()


# ---------- fix round 1 ----------
def _fail_the_write(monkeypatch, p):
    real = os.replace

    def bad(src, dst):
        if str(dst) == str(p) and str(src).endswith(".tmp"):
            raise OSError(5, "disk")
        return real(src, dst)
    monkeypatch.setattr(settings_mod.os, "replace", bad)
    return real


def test_a_failed_write_after_the_merge_changes_nothing_and_the_next_save_merges_again(tmp_path, monkeypatch):
    p = _write(tmp_path)
    for how in ("update", "forget", "mark"):
        with monkeypatch.context() as m:
            _lock_once(m, p)
            st = settings_mod.Settings(str(p))
            before = st.all()
            real = _fail_the_write(m, p)
            try:
                if how == "update":
                    st.update({"hotkey": "ctrl+alt+k"})
                elif how == "forget":
                    st.forget(str(tmp_path / "x.txt"))
                else:
                    st._forgot_read = False
                    m.setattr(st, "_load_forgotten", lambda: None)
                    st.mark_forgotten(["C:\\Work\\private"])
                raised = False
            except OSError:
                raised = True
            assert raised, how
            assert st.read_failed, how                                      # still not known to be safe
            if how == "update":
                assert st.all() == before                                   # rolled back to the pre-merge state
            m.setattr(settings_mod.os, "replace", real)
            st.update({"theme": "light"})                                   # the next save: the FILE again
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved["roots"] == ["C:\\Work"] and saved["hotkey"] == "ctrl+alt+f" and saved["theme"] == "light", how
        assert not st.read_failed and _asides(tmp_path) == []
        p.write_bytes(json.dumps(RAW).encode("utf-8"))


def test_the_set_aside_and_a_blocked_save_are_said_through_the_notification_path(tmp_path, monkeypatch):
    from nobadfind import engine, notify

    class Center:
        def __init__(self):
            self.posted = []

        def post(self, kind, title, body, severity, **kw):
            self.posted.append((kind, body, kw.get("key")))
    c = Center()
    monkeypatch.setattr(notify, "CENTER", c)
    p = _write(tmp_path, b"{ broken")
    st = settings_mod.Settings(str(p))
    st.on_notice = engine.say_settings
    st.update({"theme": "light"})
    st.update({"theme": "dark"})
    assert len(c.posted) == 1 and c.posted[0][0] == "internal_error"
    assert "couldn't read its settings file" in c.posted[0][1] and "s.json.unreadable-" in c.posted[0][1]
    # blocked: said too
    d = tmp_path / "b"
    d.mkdir()
    p2 = d / "s.json"
    p2.write_bytes(b"{ broken")
    st2 = settings_mod.Settings(str(p2))
    st2.on_notice = engine.say_settings
    real = os.replace
    monkeypatch.setattr(settings_mod.os, "replace",
                        lambda a, b: (_ for _ in ()).throw(PermissionError(13, "x")) if str(a) == str(p2)
                        else real(a, b))
    st2.update({"theme": "light"})
    assert "kept for now" in c.posted[-1][1]
