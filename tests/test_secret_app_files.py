"""1.1.0: the opt-in to read what other programs record and developer tools' plain-text sign-ins (setting
secret_app_files, off by default; maintainer ruling 2026-11-22), .env files names only until then, Recent items
always out, and the review minors folded in: the Recent rule anchored to the profile (b), forgotten.dat that can't
be read (a) or written (c)."""
import json
import os

import pytest

from nobadfind import indexer, scope, settings as settings_mod
from nobadfind.const import APP_FILES_CONSENT, DEFAULTS
from nobadfind.kinds import READABLE_EXT
from nobadfind.store import Store
from nobadfind.walker import Walker
from test_scope_indexer import PROF, S, make_api

ROAMING = os.path.join(PROF, "AppData", "Roaming")
LOCAL = os.path.join(PROF, "AppData", "Local")


def rules(**kw):
    s = dict(DEFAULTS)
    s.update(kw)
    return scope.Rules.from_settings(s)


# ---------- the setting ----------
def test_the_setting_is_off_by_default_and_a_plain_switch():
    assert DEFAULTS["secret_app_files"] is False
    assert settings_mod.coerce("secret_app_files", True) is True
    assert settings_mod.coerce("secret_app_files", "yes") is False


def test_the_pipe_turns_it_on_only_with_the_consent_word(tmp_path):
    """Fix round 1 (M7): like model_download's DOWNLOAD, set_settings needs READ_APP_SECRETS to turn it on."""
    from nobadfind.rpc.handlers import settings as h
    from nobadfind.rpc.protocol import RpcError
    a, s = make_api(tmp_path)
    m = h.methods(a)
    assert m["set_settings"]({"changes": {"secret_app_files": True}})["changed"] == []
    assert m["set_settings"]({"changes": {"secret_app_files": True}, "consent": "DOWNLOAD"})["changed"] == []
    with pytest.raises(RpcError):
        m["set_settings"]({"changes": {"secret_app_files": True}, "consent": 1})
    r = m["set_settings"]({"changes": {"secret_app_files": True}, "consent": APP_FILES_CONSENT})
    assert r["changed"] == ["secret_app_files"] and r["settings"]["secret_app_files"] is True
    assert m["set_settings"]({"changes": {"secret_app_files": False}})["changed"] == ["secret_app_files"]
    s.close()


# ---------- the scope rules, off and on ----------
APP_FILES = [
    os.path.join(ROAMING, "Microsoft", "Windows", "PowerShell", "PSReadLine", "ConsoleHost_history.txt"),
    os.path.join(ROAMING, "Microsoft", "Windows", "PowerShell", "PSReadLine", "Visual Studio Code Host_history.txt"),
    os.path.join(PROF, ".bash_history"), os.path.join(PROF, ".zsh_history"), os.path.join(PROF, ".python_history"),
    os.path.join(PROF, ".psql_history"), os.path.join(PROF, "_viminfo"),
    os.path.join(ROAMING, "FileZilla", "sitemanager.xml"), os.path.join(ROAMING, "FileZilla", "recentservers.xml"),
    os.path.join(ROAMING, "FileZilla", "queue.sqlite3x"), os.path.join(PROF, "Documents", "WinSCP.ini"),
    os.path.join(PROF, "_netrc"), os.path.join(PROF, ".netrc"),
    os.path.join(ROAMING, "GitHub CLI", "hosts.yml"), os.path.join(PROF, ".config", "gh", "hosts.yml"),
    os.path.join(PROF, ".npmrc"), os.path.join(PROF, ".pypirc"), os.path.join(PROF, ".git-credentials"),
    os.path.join(PROF, ".m2", "settings.xml"), os.path.join(PROF, ".cargo", "credentials.toml"),
    os.path.join(PROF, ".cargo", "credentials"), os.path.join(ROAMING, "terraform.d", "credentials.tfrc.json"),
    os.path.join(PROF, ".vault-token"), os.path.join(PROF, ".pgpass"),
    os.path.join(ROAMING, "postgresql", "pgpass.conf"), os.path.join(PROF, ".s3cfg"),
]
# still secrets with the opt-in on: keys, browser passwords, vaults, wallets, Windows' and the cloud's sign-ins
STRICT = [
    os.path.join(PROF, ".ssh", "id_ed25519"), os.path.join(PROF, "backup", "id_rsa"),
    os.path.join(PROF, "backup", "known_hosts"), os.path.join(PROF, "Documents", "server.pem"),
    os.path.join(LOCAL, "Google", "Chrome", "User Data", "Default", "Login Data"),
    os.path.join(ROAMING, "Mozilla", "Firefox", "Profiles", "x.default", "logins.json"),
    os.path.join(ROAMING, "Microsoft", "Credentials", "DFBE70A7"), os.path.join(PROF, "Documents", "vault.kdbx"),
    os.path.join(PROF, ".aws", "credentials"), os.path.join(ROAMING, "gcloud", "application_default_credentials.json"),
    os.path.join(ROAMING, "gnupg", "pubring.kbx"), os.path.join(PROF, "wallet.dat"),
    os.path.join(ROAMING, "Discord", "Local Storage", "leveldb", "000003.log"),
    os.path.join(ROAMING, "FileZilla", "id_rsa"),                     # a key in FileZilla's folder is still a key
]


@pytest.mark.parametrize("path", APP_FILES)
def test_app_files_off_are_secrets_out_by_default_and_names_only_with_secrets_on(path):
    r = rules()
    assert r.category(path) == "secrets" and r.out(path) and r.names_only(path), path
    r = rules(include_secrets=True)
    assert not r.out(path) and r.names_only(path), path


@pytest.mark.parametrize("secrets", [False, True])
@pytest.mark.parametrize("path", APP_FILES)
def test_app_files_on_are_read_like_any_file(path, secrets):
    r = rules(secret_app_files=True, include_secrets=secrets)
    assert r.category(path) in (None, "caches"), path
    assert not r.out(path) and not r.names_only(path), path
    assert scope.app_file(path), path


@pytest.mark.parametrize("path", STRICT)
def test_keys_and_passwords_stay_names_only_with_the_opt_in_on(path):
    r = rules(secret_app_files=True)
    assert r.category(path) == "secrets" and r.out(path), path
    r = rules(secret_app_files=True, include_secrets=True)
    assert not r.out(path) and r.names_only(path), path


def test_the_walk_lists_app_files_only_with_the_opt_in(tmp_path):
    prof = tmp_path / "me"
    psr = prof / "AppData" / "Roaming" / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine"
    psr.mkdir(parents=True)
    (psr / "ConsoleHost_history.txt").write_text("git push")
    (prof / ".npmrc").write_text("x")
    (prof / ".ssh").mkdir()
    (prof / ".ssh" / "id_rsa").write_text("x")
    (prof / "notes.txt").write_text("x")

    def walk(apps):
        seen = []
        r = scope.Rules(apps=apps, profile=str(prof), others=())
        Walker([str(prof)], gen=1, on_batch=seen.extend, rules=r).run()
        return {os.path.basename(x[0]) for x in seen}
    off, on = walk(False), walk(True)
    assert "notes.txt" in off and not {"ConsoleHost_history.txt", ".npmrc", "PSReadLine", "id_rsa"} & off
    assert {"notes.txt", "ConsoleHost_history.txt", ".npmrc", "PSReadLine"} <= on and "id_rsa" not in on


def test_the_turbo_helper_gets_the_opt_in_too():
    from nobadfind import ntfs
    cfg = ntfs.parse_config({"roots": ["C:\\"], "exclude": [], "secret_app_files": True})
    assert cfg["secret_app_files"] is True
    assert ntfs.parse_config({"roots": ["C:\\"], "exclude": []})["secret_app_files"] is False
    with pytest.raises(ValueError):
        ntfs.parse_config({"roots": ["C:\\"], "exclude": [], "secret_app_files": "yes"})
    r = ntfs._rules_for("S-1-5-21-1", cfg, profile=PROF)
    assert r.apps and not r.out(os.path.join(PROF, ".npmrc"))


# ---------- .env files: names only by default ----------
ENV = [os.path.join(PROF, "proj", ".env"), os.path.join(PROF, "proj", ".env.local"),
       os.path.join("D:\\", "work", "api", ".env.production"), os.path.join(PROF, "proj", ".ENV")]


@pytest.mark.parametrize("path", ENV)
def test_env_files_are_names_only_by_default(path):
    for kw in ({}, {"include_secrets": True}, {"include_secrets": False, "include_caches": False}):
        r = rules(**kw)
        assert not r.out(path) and r.names_only(path), (path, kw)   # listed by name, never read
    r = rules(secret_app_files=True)
    assert not r.out(path) and not r.names_only(path), path


def test_env_lookalikes_are_ordinary():
    r = rules()
    for p in (os.path.join(PROF, "proj", "env.txt"), os.path.join(PROF, "proj", "my.env"),
              os.path.join(PROF, "proj", ".envrc"), os.path.join(PROF, "proj", ".environment")):
        assert not r.names_only(p) and not scope.app_file(p), p


def test_env_files_lose_their_content_once_with_the_new_rules(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    d = os.path.join(PROF, "proj")
    s.upsert_files([(os.path.join(d, ".env"), ".env", d, "", "other", 10, 5.0, 5.0, 1),
                    (os.path.join(d, "app.py"), "app.py", d, ".py", "code", 10, 5.0, 5.0, 1)])
    ids = {r[1]: r[0] for r in s.q("SELECT id, name FROM files")}
    s.set_text(ids[".env"], 5.0, ["API_KEY=abc"])
    s.set_text(ids["app.py"], 5.0, ["print()"])
    s.set_meta("scope_rules", "3")
    ix = indexer.Indexer(s, S())
    assert ix._apply_new_rules()[0] == 1
    assert s.one("SELECT count(*) FROM chunks WHERE file_id=?", (ids[".env"],)) == 0
    assert s.one("SELECT count(*) FROM chunks WHERE file_id=?", (ids["app.py"],)) == 1
    assert s.one("SELECT count(*) FROM files") == 2                    # the name stays
    s.close()


# ---------- Recent items: always out, whatever the switches; anchored to the profile (b) ----------
RECENT = [
    os.path.join(ROAMING, "Microsoft", "Windows", "Recent", "lawyer.docx.lnk"),
    os.path.join(ROAMING, "Microsoft", "Windows", "Recent", "AutomaticDestinations", "5f7b.automaticDestinations-ms"),
    os.path.join(ROAMING, "Microsoft", "Office", "Recent", "payslip.pdf.LNK"),
    os.path.join(ROAMING, "Microsoft", "Office", "Recent"),
]


@pytest.mark.parametrize("path", RECENT)
def test_recent_items_stay_out_with_the_opt_in_on(path):
    r = rules(secret_app_files=True, include_secrets=True, include_caches=True, include_system=True)
    assert r.category(path) == "other_profiles" and r.out(path), path


def test_an_unrelated_recent_folder_is_not_locked_out():
    r = rules(secret_app_files=True, include_secrets=True)
    for p in (os.path.join("D:\\", "proj", "office", "recent", "plan.docx"),
              os.path.join("D:\\", "backup", "Microsoft", "Windows", "Recent", "x.txt"),
              os.path.join(PROF, "Documents", "Office", "Recent", "y.txt")):
        assert r.category(p) is None and not r.out(p), p


def test_recent_items_of_the_profile_the_rules_are_for():
    r = scope.Rules(profile="C:\\Users\\me", others=(), secrets=True, apps=True)
    assert r.out("C:\\Users\\me\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\a.lnk")
    assert not r.out("D:\\Users\\me\\AppData\\Roaming\\Microsoft\\Windows\\Recent\\a.lnk")


# ---------- turning it on and off ----------
def _app_index(tmp_path, **kw):
    a, s = make_api(tmp_path)
    if kw:
        a.set_settings(kw, consent=APP_FILES_CONSENT)
    psr = os.path.join(ROAMING, "Microsoft", "Windows", "PowerShell", "PSReadLine")
    proj = os.path.join(PROF, "proj")
    docs = os.path.join(PROF, "Documents")
    rows = [(psr, "PSReadLine", os.path.dirname(psr), "", "folder"),
            (os.path.join(psr, "ConsoleHost_history.txt"), "ConsoleHost_history.txt", psr, ".txt", "text"),
            (os.path.join(PROF, ".npmrc"), ".npmrc", PROF, "", "other"),
            (os.path.join(PROF, ".m2", "settings.xml"), "settings.xml", os.path.join(PROF, ".m2"), ".xml", "text"),
            (os.path.join(proj, ".env"), ".env", proj, "", "other"),
            (os.path.join(docs, "notes.txt"), "notes.txt", docs, ".txt", "text"),
            (os.path.join(docs, "settings.xml"), "settings.xml", docs, ".xml", "text")]
    s.upsert_files([r + (10, 5.0, 5.0, 1) for r in rows])
    ids = {r[0]: r[1] for r in s.q("SELECT path, id FROM files")}
    for p, fid in ids.items():
        if not p.endswith("PSReadLine"):
            s.set_text(fid, 5.0, [f"token {os.path.basename(p)}"])
    return a, s, ids


def _content(s):
    return {r[0] for r in s.q("SELECT DISTINCT f.path FROM chunks c JOIN files f ON f.id = c.file_id")}


def test_turning_it_off_with_secrets_off_takes_out_only_that_class(tmp_path):
    a, s, ids = _app_index(tmp_path, secret_app_files=True)
    docs = os.path.join(PROF, "Documents")
    env = os.path.join(PROF, "proj", ".env")
    assert a.set_settings({"secret_app_files": False})["changed"] == ["secret_app_files"]
    assert "rescan" in a._indexer.calls
    paths = {r[0] for r in s.q("SELECT path FROM files")}
    assert paths == {os.path.join(docs, "notes.txt"), os.path.join(docs, "settings.xml"), env}   # .env: name only
    assert _content(s) == {os.path.join(docs, "notes.txt"), os.path.join(docs, "settings.xml")}
    assert s.one("SELECT text_err FROM files WHERE path=?", (env,)) == indexer.NAMES_ONLY
    s.close()


def test_turning_it_off_with_secrets_on_keeps_the_names_and_drops_the_content(tmp_path):
    a, s, ids = _app_index(tmp_path, secret_app_files=True, include_secrets=True)
    before = {r[0] for r in s.q("SELECT path FROM files")}
    a.set_settings({"secret_app_files": False})
    assert {r[0] for r in s.q("SELECT path FROM files")} == before
    docs = os.path.join(PROF, "Documents")
    assert _content(s) == {os.path.join(docs, "notes.txt"), os.path.join(docs, "settings.xml")}
    s.close()


def test_turning_it_on_reads_the_names_only_rows_again_but_not_keys(tmp_path):
    a, s = make_api(tmp_path)
    a.set_settings({"include_secrets": True})
    ssh = os.path.join(PROF, ".ssh")
    rows = [(os.path.join(PROF, ".npmrc"), ".npmrc", PROF, "", "other"),
            (os.path.join(PROF, "proj", ".env.local"), ".env.local", os.path.join(PROF, "proj"), ".local", "other"),
            (os.path.join(ssh, "id_rsa"), "id_rsa", ssh, "", "other")]
    s.upsert_files([r + (10, 5.0, 5.0, 1) for r in rows])
    for fid, in s.q("SELECT id FROM files"):
        s.set_text(fid, 5.0, [], indexer.NAMES_ONLY)
    assert a.set_settings({"secret_app_files": True})["changed"] == []          # no consent word: stays off
    assert s.one("SELECT count(*) FROM files WHERE text_mtime IS NULL") == 0
    a.set_settings({"secret_app_files": True}, consent="yes")
    assert a.get_settings()["secret_app_files"] is False
    a.set_settings({"secret_app_files": True}, consent=APP_FILES_CONSENT)
    got = {r[0]: r[1] for r in s.q("SELECT name, text_mtime FROM files")}
    assert got[".npmrc"] is None and got[".env.local"] is None        # read again by the text pass
    assert got["id_rsa"] == 5.0                                       # a key stays names only
    s.close()


def test_the_text_pass_reads_app_files_without_a_readable_extension(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    proj = os.path.join(PROF, "proj")
    rows = [(os.path.join(PROF, ".bash_history"), ".bash_history", PROF, "", "other"),
            (os.path.join(proj, ".env.local"), ".env.local", proj, ".local", "other"),
            (os.path.join(proj, ".env"), ".env", proj, "", "folder"),               # a venv named .env
            (os.path.join(PROF, "Documents", "credentials"), "credentials", os.path.join(PROF, "Documents"), "",
             "other"),
            (os.path.join(PROF, ".cargo", "credentials"), "credentials", os.path.join(PROF, ".cargo"), "", "other"),
            (os.path.join(PROF, "Documents", "blob"), "blob", os.path.join(PROF, "Documents"), "", "other")]
    s.upsert_files([r + (10, 5.0, 5.0, 1) for r in rows])
    exts = set(READABLE_EXT)
    assert s.needs_text(exts, 10 ** 6) == []                                       # off: by extension only
    got = s.needs_text(exts, 10 ** 6, names=indexer.APP_READ_NAMES, env=True)
    assert {os.path.basename(r[1]) for r in got} == {".bash_history", ".env.local", "credentials"}
    ix = indexer.Indexer(s, S(secret_app_files=True))
    keep = {r[1] for r in ix._app_extras(got, exts)}
    assert keep == {os.path.join(PROF, ".bash_history"), os.path.join(proj, ".env.local"),
                    os.path.join(PROF, ".cargo", "credentials")}
    assert s.one("SELECT text_err FROM files WHERE path=?", (os.path.join(PROF, "Documents", "credentials"),))
    s.close()


# ---------- fix round 1 (I1): turned off while being read, nothing comes back ----------
def _pass_with_a_flip(tmp_path, monkeypatch, secrets):
    """A text pass with the opt-in on and a queue of its files; the user turns it off while the first one is being
    read (the purge runs then). Returns (store, ids, indexer, api)."""
    import concurrent.futures as cf
    from nobadfind import api as api_mod
    from test_scope_indexer import Ix
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    st.update({"secret_app_files": True, "include_secrets": secrets, "content_max_mb": 1, "ocr": False})
    a = api_mod.Api(s, st, Ix(), None)
    psr = os.path.join(ROAMING, "Microsoft", "Windows", "PowerShell", "PSReadLine")
    docs = os.path.join(PROF, "Documents")
    rows = [(os.path.join(psr, "ConsoleHost_history.txt"), "ConsoleHost_history.txt", psr, ".txt", "text"),
            (os.path.join(PROF, ".bash_history"), ".bash_history", PROF, "", "other"),
            (os.path.join(PROF, ".npmrc"), ".npmrc", PROF, "", "other"),
            (os.path.join(PROF, "proj", ".env"), ".env", os.path.join(PROF, "proj"), "", "other"),
            (os.path.join(docs, "notes.txt"), "notes.txt", docs, ".txt", "text")]
    # the class files are the newest, so they are read first (needs_text: newest first)
    s.upsert_files([r + (10, 9.0 if r[1] != "notes.txt" else 1.0, 9.0 if r[1] != "notes.txt" else 1.0, 1)
                    for r in rows])
    ids = {r[1]: r[0] for r in s.q("SELECT id, name FROM files")}
    ix = indexer.Indexer(s, st)
    ix.status["plan"] = {"text_workers": 1, "text_workers_idle": 1}        # one in flight, the rest queued
    monkeypatch.setattr(ix, "_check_pause", lambda: "")
    monkeypatch.setattr(ix, "_away", lambda: False)
    sent, flipped = [], []

    class Pool:
        def __init__(self, *a, **k):
            pass

        def submit(self, fn, job):
            sent.append(os.path.basename(job[1]))
            if not flipped:
                flipped.append(1)
                a.set_settings({"secret_app_files": False})                # mid-read: off, and the purge runs
            f = cf.Future()
            f.set_result((job[0], job[3], [f"secret text of {os.path.basename(job[1])}"], None))
            return f

        def shutdown(self, **k):
            pass
    monkeypatch.setattr(indexer.cf, "ProcessPoolExecutor", Pool)
    ix._read_texts()
    return s, ids, ix, a, sent


@pytest.mark.parametrize("secrets", [False, True])
def test_turning_it_off_mid_pass_leaves_no_content(tmp_path, monkeypatch, secrets):
    s, ids, ix, a, sent = _pass_with_a_flip(tmp_path, monkeypatch, secrets)
    assert sent[0] != "notes.txt" and "notes.txt" in sent
    assert not {".npmrc", ".env"} & set(sent[1:])                            # the stale queue was dropped
    read = {r[0] for r in s.q("SELECT DISTINCT f.name FROM chunks c JOIN files f ON f.id = c.file_id")}
    assert read == {"notes.txt"}
    assert s.one("SELECT count(*) FROM chunks WHERE file_id NOT IN (SELECT id FROM files)") == 0   # no orphans
    names = {r[0] for r in s.q("SELECT name FROM files")}
    if secrets:                                                              # names only: kept, marked, not read
        assert names == set(ids)
        assert s.one("SELECT text_err FROM files WHERE name='ConsoleHost_history.txt'") == indexer.NAMES_ONLY
    else:                                                                    # out: gone, .env's name stays
        assert names == {"notes.txt", ".env"}
    assert s.one("SELECT text_err FROM files WHERE name='.env'") == indexer.NAMES_ONLY
    # the next pass: nothing of theirs is read again
    sent.clear()
    ix._read_texts()
    assert sent == [] and {r[0] for r in s.q(
        "SELECT DISTINCT f.name FROM chunks c JOIN files f ON f.id = c.file_id")} == {"notes.txt"}
    s.close()


def test_on_again_after_a_flip_reads_them_normally(tmp_path, monkeypatch):
    s, ids, ix, a, sent = _pass_with_a_flip(tmp_path, monkeypatch, True)
    a.set_settings({"secret_app_files": True}, consent=APP_FILES_CONSENT)
    sent.clear()
    ix._read_texts()
    read = {r[0] for r in s.q("SELECT DISTINCT f.name FROM chunks c JOIN files f ON f.id = c.file_id")}
    assert read == {"notes.txt", "ConsoleHost_history.txt", ".bash_history", ".npmrc", ".env"}
    s.close()


# ---------- fix round 2 (I1, meaning vectors): purged while being encoded, no vector survives ----------
def _chunks(s, texts):
    d = os.path.join(PROF, "Docs")
    s.upsert_files([(os.path.join(d, n), n, d, ".txt", "text", 1, 1.0, 1.0, 1) for n in texts])
    for fid, name in s.q("SELECT id, name FROM files"):
        s.set_text(fid, 1.0, [texts[name]])
    return {r[1]: r[0] for r in s.q("SELECT c.id, f.name FROM chunks c JOIN files f ON f.id = c.file_id")}


@pytest.mark.parametrize("next_", [False, True])
def test_vectors_go_only_to_chunks_still_there(tmp_path, next_):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    c = _chunks(s, {"a.txt": "alpha", "b.txt": "token=abc", "c.txt": "gamma"})
    t = "vecs_next" if next_ else "vecs"
    s.drop_content([s.one("SELECT id FROM files WHERE name='b.txt'")], indexer.NAMES_ONLY)   # the purge
    rows = [(c[n], b"\x00" * 8) for n in ("a.txt", "b.txt", "c.txt")]
    assert s.add_vectors(rows, next=next_) == [c["a.txt"], c["c.txt"]]
    assert {r[0] for r in s.q(f"SELECT chunk_id FROM {t}")} == {c["a.txt"], c["c.txt"]}
    assert s.one(f"SELECT count(*) FROM {t} WHERE chunk_id NOT IN (SELECT id FROM chunks)") == 0
    s.close()


def test_a_normal_add_writes_every_vector(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    c = _chunks(s, {"a.txt": "alpha", "b.txt": "beta"})
    bodies = {c["a.txt"]: "alpha", c["b.txt"]: "beta"}
    assert s.add_vectors([(i, b"\x01" * 8) for i in bodies], bodies=bodies) == list(bodies)
    assert s.one("SELECT count(*) FROM vecs") == 2
    s.close()


def test_a_reused_chunk_id_gets_no_vector_of_the_old_text(tmp_path):
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    c = _chunks(s, {"a.txt": "alpha"})
    assert s.add_vectors([(c["a.txt"], b"\x01" * 8)], bodies={c["a.txt"]: "a secret that was purged"}) == []
    assert s.one("SELECT count(*) FROM vecs") == 0
    s.close()


def test_a_purge_while_the_chunks_are_encoded_leaves_nothing_on_disk_or_in_memory(tmp_path):
    import numpy as np
    from nobadfind import embed
    s = Store(str(tmp_path / "i.db"), encrypt=False)
    c = _chunks(s, {"notes.txt": "the garden", ".bash_history": "export TOKEN=abc"})
    vi = embed.VectorIndex(dim=8)
    ix = indexer.Indexer(s, S(), vi)
    ix._meaning_pause = lambda: True
    ix._round_over = lambda: False
    ix._breathe = lambda: None
    secret = s.one("SELECT id FROM files WHERE name='.bash_history'")

    def encode(texts, mid=None):
        if not getattr(encode, "done", False):
            encode.done = True
            s.drop_content([secret], indexer.NAMES_ONLY)          # secret_app_files off, mid-encode
        return np.ones((len(texts), 8), np.float32)
    ix._encode = encode
    ix._chunk_vectors()
    assert {r[0] for r in s.q("SELECT chunk_id FROM vecs")} == {c["notes.txt"]}
    assert set(vi.ids.tolist()) == {c["notes.txt"]}
    s.close()


# ---------- (a) and (c): the protected list of forgotten files can't be read or written ----------
def _forget_one(a, s, name="f0.txt"):
    d = os.path.join(PROF, "Docs")
    s.upsert_files([(os.path.join(d, name), name, d, ".txt", "text", 1, 1.0, 1.0, 1)])
    return a.forget(s.one("SELECT id FROM files WHERE name=?", (name,))), os.path.join(d, name)


def test_an_unreadable_forgotten_list_never_lets_new_forgets_into_settings_json(tmp_path, monkeypatch):
    fdat = tmp_path / settings_mod.FORGOTTEN_FILE
    fdat.write_bytes(b"another account's blob")
    real = settings_mod._unprotect

    def unreadable(data):
        raise OSError("not yours")
    monkeypatch.setattr(settings_mod, "_unprotect", unreadable)
    a, s = make_api(tmp_path)
    r, path = _forget_one(a, s)
    assert r["ok"] is True and "couldn't save" in r["error"]                       # a note, not a failure
    assert path in a._settings.get("exclude")                                      # kept out now, in memory
    assert "f0.txt" not in (tmp_path / "s.json").read_text(encoding="utf-8")
    assert fdat.read_bytes() == b"another account's blob"                          # never overwritten
    assert s.meta("forgotten_moved") != "1"
    # readable again (the blob is now this account's): the next change saves it protected
    fdat.write_bytes(settings_mod._protect(json.dumps([]).encode("utf-8")))
    monkeypatch.setattr(settings_mod, "_unprotect", real)
    assert a._settings.retry_forgotten() is True and a._settings.note == ""
    assert "f0.txt" not in (tmp_path / "s.json").read_text(encoding="utf-8")
    assert settings_mod.Settings(str(tmp_path / "s.json")).forgotten() == [path]
    a._settings._retry_thread.join(5)
    s.close()


def test_a_locked_forgotten_list_is_tried_again_and_settings_still_save(tmp_path, monkeypatch):
    a, s = make_api(tmp_path)
    monkeypatch.setattr(settings_mod.Settings, "FORGOT_WAIT_S", 0.0)
    real = os.replace
    tries = []

    def locked(src, dst):
        if str(dst).endswith(settings_mod.FORGOTTEN_FILE):
            tries.append(1)
            raise PermissionError(13, "in use by another process")
        return real(src, dst)
    monkeypatch.setattr(settings_mod.os, "replace", locked)
    r, path = _forget_one(a, s)
    assert r["ok"] is True and r["error"]
    a._settings._retry_thread.join(5)
    assert len(tries) == settings_mod.Settings.FORGOT_TRIES                       # once now, then in the background
    assert a._settings.update({"theme": "light"}) == ["theme"]                    # (c) other settings still save
    plain = (tmp_path / "s.json").read_text(encoding="utf-8")
    assert '"light"' in plain and "f0.txt" not in plain
    assert not (tmp_path / (settings_mod.FORGOTTEN_FILE + ".tmp")).exists()
    monkeypatch.setattr(settings_mod.os, "replace", real)                          # the lock is gone
    assert a._settings.update({"theme": "dark"}) == ["theme"] and a._settings.note == ""
    assert settings_mod.Settings(str(tmp_path / "s.json")).forgotten() == [path]
    s.close()


def test_a_locked_forgotten_list_never_holds_the_settings_lock_while_it_waits(tmp_path, monkeypatch):
    """Fix round 1 (M3): the save tries once; the waits between retries are on a thread, without the lock."""
    import time
    a, s = make_api(tmp_path)
    monkeypatch.setattr(settings_mod.Settings, "FORGOT_WAIT_S", 0.5)
    real = os.replace

    def locked(src, dst):
        if str(dst).endswith(settings_mod.FORGOTTEN_FILE):
            raise PermissionError(13, "in use by another process")
        return real(src, dst)
    monkeypatch.setattr(settings_mod.os, "replace", locked)
    t0 = time.monotonic()
    r, _path = _forget_one(a, s)
    assert r["ok"] is True and r["error"] and time.monotonic() - t0 < 0.4
    assert a._settings._retry_thread.is_alive()                                     # waiting to try again
    assert a._settings._lock.acquire(timeout=0.2)                                   # ... without the lock
    a._settings._lock.release()
    t0 = time.monotonic()
    assert a._settings.update({"theme": "light"}) == ["theme"] and time.monotonic() - t0 < 0.4
    monkeypatch.setattr(settings_mod.os, "replace", real)                          # the lock is gone
    a._settings._retry_thread.join(5)
    assert a._settings.note == "" and a._settings.forgotten_saved()                # the retry saved it
    s.close()


def test_a_forget_that_works_says_nothing_more(tmp_path):
    a, s = make_api(tmp_path)
    r, _path = _forget_one(a, s)
    assert r == {"ok": True}
    s.close()


def test_the_move_out_of_settings_json_is_not_done_while_entries_stay_there(tmp_path, monkeypatch):
    from nobadfind import api as api_mod
    from test_scope_indexer import Ix
    old_file = tmp_path / "medical.pdf"
    old_file.write_text("x")
    (tmp_path / "s.json").write_text(json.dumps({"exclude": [str(old_file)]}), encoding="utf-8")
    s = Store(str(tmp_path / "i.db"), encrypt=False)

    def no_dpapi(data):
        raise OSError("DPAPI unavailable")
    monkeypatch.setattr(settings_mod, "_protect", no_dpapi)
    monkeypatch.setattr(settings_mod.Settings, "FORGOT_WAIT_S", 0.0)
    a = api_mod.Api(s, settings_mod.Settings(str(tmp_path / "s.json")), Ix(), None)
    assert a._settings.note                                                      # in memory only, said
    assert "medical.pdf" in (tmp_path / "s.json").read_text(encoding="utf-8")   # still there: not lost
    assert s.meta("forgotten_moved") != "1"                                      # so the move isn't done
    a._settings._retry_thread.join(5)                                            # (its retries fail too)
    assert "medical.pdf" in (tmp_path / "s.json").read_text(encoding="utf-8")
    monkeypatch.undo()
    a2 = api_mod.Api(s, settings_mod.Settings(str(tmp_path / "s.json")), Ix(), None)
    assert "medical.pdf" not in (tmp_path / "s.json").read_text(encoding="utf-8")
    assert s.meta("forgotten_moved") == "1" and a2._settings.forgotten() == [str(old_file)]
    s.close()
