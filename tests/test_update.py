"""In-app updates (0.9.0): only this repository's own release asset, checked by size and SHA-256 (the .sha256 file
and GitHub's digest must agree), installed only after the user's Install, never an older version."""
import hashlib
import os

from nobadfind import settings as settings_mod, update


def release(ver="0.9.1", body=b"installer bytes", digest=True, **over):
    sha = hashlib.sha256(body).hexdigest()
    exe = f"NobadFind-Setup-{ver}.exe"
    base = f"https://github.com/nobad-studio/find/releases/download/find-v{ver}/{exe}"
    rel = {"tag_name": f"find-v{ver}", "draft": False, "prerelease": False,
           "html_url": f"https://github.com/nobad-studio/find/releases/tag/find-v{ver}",
           "assets": [{"name": exe, "browser_download_url": base, "size": len(body),
                       "digest": f"sha256:{sha}" if digest else None},
                      {"name": exe + ".sha256", "browser_download_url": base + ".sha256", "size": 90}]}
    rel.update(over)
    return rel, sha, body


def make(tmp_path, rel, sha, current="0.9.0"):
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    started = []

    def get(url, raw=False, **k):
        if url == update.LATEST:
            if isinstance(rel, Exception):
                raise rel
            return rel
        if url.endswith(".sha256"):
            return f"{sha}  NobadFind-Setup.exe\n"
        raise AssertionError(url)
    u = update.Updater(st, data_dir=str(tmp_path), get=get, start=started.append, current=current)
    return u, started


def fake_fetch(body):
    def fetch(url, dest, size, sha, name, progress):
        assert hashlib.sha256(body).hexdigest() == sha and len(body) == size
        with open(dest, "wb") as f:
            f.write(body)
        progress(name, size, size)
    return fetch


def test_only_this_repositorys_own_installer_counts():
    rel, _sha, _ = release()
    assert update.read_release(rel)["version"] == "0.9.1"
    bad = release()[0]
    bad["assets"][0]["browser_download_url"] = "https://example.com/NobadFind-Setup-0.9.1.exe"
    assert update.read_release(bad) is None                                    # a link elsewhere
    assert update.read_release(release(prerelease=True)[0]) is None
    assert update.read_release(release(tag_name="vpn-v1.7.0")[0]) is None      # not a Find release
    nosha = release()[0]
    nosha["assets"] = nosha["assets"][:1]
    assert update.read_release(nosha) is None                                  # no .sha256: never installed
    huge = release()[0]
    huge["assets"][0]["size"] = update.MAX_INSTALLER + 1
    assert update.read_release(huge) is None


def test_check_download_and_install(tmp_path):
    rel, sha, body = release()
    u, started = make(tmp_path, rel, sha)
    seen = []
    u.on_change = lambda snap: seen.append(snap["state"])
    assert u.check()["state"] == "available" and u.snapshot()["latest"] == "0.9.1"
    assert u.download(fetch=fake_fetch(body)) is True and u.state == "ready"
    assert u.install() is True
    exe = os.path.join(str(tmp_path), "updates", "NobadFind-Setup-0.9.1.exe")
    assert started[0][0] == exe and "/VERYSILENT" in started[0] and u.state == "installing"
    assert seen == ["checking", "available", "downloading", "verifying", "ready", "verifying", "installing"]


def test_no_update_when_the_newest_is_this_one_or_older(tmp_path):
    rel, sha, _ = release("0.9.0")
    u, _ = make(tmp_path, rel, sha, current="0.9.0")
    assert u.check()["state"] == "uptodate"
    rel, sha, _ = release("0.8.5")
    u, _ = make(tmp_path, rel, sha, current="0.9.0")
    assert u.check()["state"] == "uptodate"
    assert u.download(fetch=fake_fetch(b"x")) is False                         # never an older version


def test_a_checksum_that_disagrees_is_never_installed(tmp_path):
    rel, sha, body = release()
    rel["assets"][0]["digest"] = "sha256:" + "0" * 64                          # GitHub's digest says otherwise
    u, started = make(tmp_path, rel, sha)
    u.check()
    assert u.download(fetch=fake_fetch(body)) is False and u.state == "error"
    assert u.install() is False and started == []


def test_a_changed_download_is_not_run(tmp_path):
    rel, sha, body = release()
    u, started = make(tmp_path, rel, sha)
    u.check()
    u.download(fetch=fake_fetch(body))
    with open(os.path.join(str(tmp_path), "updates", "NobadFind-Setup-0.9.1.exe"), "wb") as f:
        f.write(b"something else entirely")
    assert u.install() is False and started == [] and u.state == "error"


def test_offline_is_an_error_not_a_crash_and_the_daily_check(tmp_path):
    u, _ = make(tmp_path, OSError("no network"), "0" * 64)
    assert u.due() is True
    assert u.check()["state"] == "error" and "GitHub" in u.error
    assert u.due() is False                                                    # not again for a day
    u.settings.update({"update_check": False})
    u.checked_at = 0
    assert u.due() is False                                                    # switched off: never by itself


def test_api_install_needs_the_consent_word(tmp_path):
    from nobadfind import api as api_mod
    rel, sha, body = release()
    u, started = make(tmp_path, rel, sha)
    a = api_mod.Api(None, u.settings, type("Ix", (), {"embedder": None, "photo_text": None})(), None)
    assert a.update_install("INSTALL")["ok"] is False                          # no updater yet
    a._updater = u
    assert a.update_install("INSTALL") == {"ok": False, "error": "Check for updates first."}
    u.check()
    assert a.update_install("yes")["ok"] is False
    assert a.update_state()["state"] == "available"


def chunked_fetch(body, clock, step_s, chunk):
    """Like _fetch_verified on a fake clock: chunk bytes every step_s seconds, progress after each."""
    def fetch(url, dest, size, sha, name, progress):
        assert hashlib.sha256(body).hexdigest() == sha and len(body) == size
        with open(dest, "wb") as f:
            for i in range(0, len(body), chunk):
                f.write(body[i:i + chunk])
                clock[0] += step_s
                progress(name, min(i + chunk, len(body)), size)
    return fetch


def test_download_progress_is_throttled_and_measures_the_speed(tmp_path):
    rel, sha, body = release(body=bytes(range(256)) * 400)          # 102,400 bytes
    st = settings_mod.Settings(str(tmp_path / "s.json"))
    clock = [100.0]
    u = update.Updater(st, data_dir=str(tmp_path), current="0.9.0", mono=lambda: clock[0], start=lambda a: None,
                       get=lambda url, raw=False, **k: f"{sha}  x\n" if url.endswith(".sha256") else rel)
    u.check()
    seen = []
    u.on_change = seen.append
    # 1,024 bytes every 10 ms: 100 progress calls over a second, 102,400 bytes a second
    assert u.download(fetch=chunked_fetch(body, clock, 0.01, 1024)) is True
    states = [s["state"] for s in seen]
    assert states[0] == "downloading" and states[-2:] == ["verifying", "ready"]
    moving = [s for s in seen[1:] if s["state"] == "downloading"]
    assert 3 <= len(moving) <= 5                                    # a second of bytes: about 4 events, not 100
    assert all(0 < a["got"] < b["got"] for a, b in zip(moving, moving[1:]))
    assert moving[0]["bps"] == 0                                    # one sample: no speed claimed yet
    assert all(abs(s["bps"] - 102_400) < 2_000 for s in moving[1:])  # the speed the bytes really came at
    assert seen[-1]["got"] == len(body) and seen[-1]["bps"] == 0


def test_install_goes_downloading_verifying_installing_without_ready(tmp_path):
    rel, sha, body = release()
    u, started = make(tmp_path, rel, sha)
    u.check()
    seen = []
    u.on_change = lambda snap: seen.append(snap["state"])
    assert u.download(fetch=fake_fetch(body), then_install=True) is True and u.state == "verifying"
    assert u.install() is True and started
    assert seen == ["downloading", "verifying", "installing"]
    assert u.check()["state"] == "installing" and u.due() is False          # no check in the middle of it


def test_a_failed_download_stops_the_speed(tmp_path):
    rel, sha, _ = release()
    u, _ = make(tmp_path, rel, sha)
    u.check()

    def broken(url, dest, size, sha, name, progress):
        u.bps = 1234
        progress(name, 3, size)
        raise IOError("cut off")
    assert u.download(fetch=broken, then_install=True) is False
    assert u.state == "error" and u.snapshot()["bps"] == 0 and "Try again" in u.error
