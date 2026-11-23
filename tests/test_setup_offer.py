"""First-run setup (plan Task 6): setup_offer / setup_accept / setup_later. After the first scan the window offers
the models suggested for this PC once, with sizes, memory, why and the time to index what the scan counted;
Download is the consent and fetches only the ticked models; Later leaves a reminder; a failed download leaves the
window working and the offer ready to try again."""
import threading

import pytest

from nobadfind import api as api_mod, firstrun, models, notify, settings as settings_mod

from test_api_status import make

PC = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "avx512_vnni": False, "gpu": "Iris Xe",
      "vram_gb": 0.1, "directml": False, "disk_free_gb": 200.0, "ssd": True}


@pytest.fixture
def a(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod.hw, "scan", lambda: dict(PC))
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-GB"])
    monkeypatch.setattr(models, "DATA_DIR", str(tmp_path / "data"))
    a, s = make(tmp_path)
    a._models_dir = str(tmp_path / "data")
    ix = a._indexer
    ix._load_embedder = ix._load_photo = lambda: None
    ix.wake, ix.text_model = threading.Event(), None
    ix.status["last_scan"] = 1763400000.0               # the first walk is done
    a._notify = notify.Center(a._settings, store=None, toast=lambda t, b: True, run=lambda fn: fn())
    yield a
    s.close()


def _no_network(monkeypatch, got):
    """Downloads that don't go out: each file appears at its pinned size (as _fetch_verified leaves it)."""
    def fetch(url, dest, size, sha, name, progress=None, part=".part"):
        got.append(name)
        with open(dest, "wb") as f:
            f.truncate(size)
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", fetch)
    monkeypatch.setattr(api_mod.vlm_runtime, "install", lambda mid, d, progress=None: got.append(mid))


def _join():
    for t in threading.enumerate():
        if t.name == "model-download":
            t.join(5)


def _by(r):
    return {i["model"]: i for i in r["items"]}


def test_offer_lists_suggested_items_with_sizes_memory_why_and_index_time(a):
    r = a.setup_offer()
    assert r["show"] is True and r["state"] == "pending"
    assert r["pc"]["like"] == "mid" and r["pc"]["summary"].startswith("This PC is like: Mid")
    assert r["pc"]["hardware"]["ram_gb"] == 15.7 and "gpu" in r["pc"]["classes"]
    by = _by(r)
    photo = by["siglip2-base"]
    assert photo["outcome"] == "suggested" and photo["group"] == "suggested" and photo["checked"] is True
    assert photo["size_mb"] == models.missing_mb("siglip2-base", a._models_dir) > 0
    assert photo["cost_here"]["ram_mb"] == 621 and photo["cost_here"]["measured_on"] == "similar PC"
    assert photo["why"].startswith("Suggested: SigLIP 2")
    # one photo in the index at 1.416 photos a second, measured on a similar PC
    assert photo["est_index"] == "under a minute for 1 photo (on a similar PC)"
    # text has no floor: the tier's model is listed, never called suggested, so it isn't ticked
    text = [i for i in r["items"] if i["workload"] == "text"]
    assert len(text) == 1 and text[0]["outcome"] == "not_measured" and text[0]["checked"] is False
    assert "no measured floor" in text[0]["why"] and text[0]["cost_here"]["measured_on"] == "reference PC"
    assert text[0]["est_index"].endswith("for 2 documents (on the reference PC)")
    assert r["total_mb"] == sum(i["size_mb"] for i in r["items"] if i["checked"])     # no talk model ticked
    assert r["est_download"] is None                        # no download has measured this PC's speed yet


def test_talk_is_offered_unticked_with_its_runtime(a):
    by = _by(a.setup_offer())
    talk = by["smolvlm2-500m"]
    assert talk["outcome"] == "suggested" and talk["checked"] is False      # photo_talk is never ticked for you
    assert talk["runtime"]["id"] == "llama-vulkan" and talk["runtime"]["size_mb"] > 0
    assert talk["size_mb"] == models.missing_mb("smolvlm2-500m", a._models_dir) + talk["runtime"]["size_mb"]
    assert talk["est_index"] == ""


def test_upgrades_are_under_more_and_not_recommended_ones_are_not_listed(a):
    r = a.setup_offer()
    for i in r["items"]:
        assert i["outcome"] in ("suggested", "upgrade", "lighter", "not_measured")
        assert i["group"] == ("suggested" if i["outcome"] in ("suggested", "not_measured") else "more")
        if i["group"] == "more":
            assert i["checked"] is False and i["cost_here"]
    sugg = a._suggestions(PC, "english")
    hidden = {e["model"] for w in sugg.values() for e in w if e["outcome"] == "not_recommended"}
    assert not hidden & set(_by(r))


def test_offer_waits_for_the_first_scan(a):
    del a._indexer.status["last_scan"]
    r = a.setup_offer()
    assert r["show"] is False and all(i["est_index"] == "" for i in r["items"])


def test_offer_shown_once_then_on_models_page(a, monkeypatch):
    assert a.setup_offer()["show"] is True
    got = []
    _no_network(monkeypatch, got)
    assert a.setup_accept(["siglip2-base"], "DOWNLOAD")["ok"] is True
    _join()
    again = a.setup_offer()
    assert again["show"] is False and again["state"] == "done"
    # still there for Settings > Models' "Suggested for this PC"
    assert _by(again)["siglip2-base"]["on_disk"] is True and again["items"]
    # a new engine (the next start) doesn't show it either: the answer is saved
    st = settings_mod.Settings(a._settings.path)
    assert st.get("setup_offer") == "done"


def test_accept_is_the_consent_and_downloads_only_checked_items(a, monkeypatch):
    got = []
    _no_network(monkeypatch, got)
    before = dict(a._settings.data)
    r = a.setup_accept(["siglip2-base"], "yes")
    assert r["ok"] is False and r["started"] == [] and got == []           # nothing before the click's word
    assert a._settings.data == before
    r = a.setup_accept(["siglip2-base", "not-a-model"], "DOWNLOAD")
    assert r["ok"] is False and got == [] and a._settings.data == before   # only what the offer lists
    r = a.setup_accept(["siglip2-base"], "DOWNLOAD")
    assert r == {"ok": True, "error": "", "started": ["siglip2-base"]}
    _join()
    assert got and all(n in models.get("siglip2-base")["files"] for n in got)     # nothing for the unticked
    st = a._settings
    # the settings auto_configure sets: the chosen photo model and photo meaning on, OCR on; the text model was
    # not ticked, so meaning search stays as it was
    assert st.get("photo_model") == "siglip2-base" and st.get("photo_meaning") is True and st.get("ocr") is True
    assert st.get("semantic") is False and st.get("allow_photo_model_download") is True


def test_ticked_talk_model_brings_its_runtime_in_the_same_consent(a, monkeypatch):
    got = []
    _no_network(monkeypatch, got)
    r = a.setup_accept(["smolvlm2-500m"], "DOWNLOAD")
    assert r["ok"] is True and r["started"] == ["smolvlm2-500m", "llama-vulkan"]
    _join()
    assert "llama-vulkan" in got and {"model.gguf", "mmproj.gguf"} <= set(got)
    assert not a._settings.get("photo_meaning") and not a._settings.get("allow_model_download")


def test_accepting_the_text_tier_model_turns_meaning_search_on(a, monkeypatch):
    got = []
    _no_network(monkeypatch, got)
    text = next(i for i in a.setup_offer()["items"] if i["workload"] == "text")
    assert a.setup_accept([text["model"]], "DOWNLOAD")["ok"] is True
    _join()
    assert a._settings.get("semantic") is True and a._settings.get("text_model") == text["model"]


def test_first_run_offer_survives_download_failure(a, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("No internet connection")
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", fail)
    assert a.setup_accept(["siglip2-base"], "DOWNLOAD")["ok"] is True
    _join()
    r = a.setup_offer()
    # the offer comes back to try again, with the reason; nothing else changed
    assert r["show"] is True and r["state"] == "accepted"
    item = _by(r)["siglip2-base"]
    assert item["state"] == "failed" and "No internet" in item["error"] and item["checked"] is True
    # the window keeps working with what is on disk: names search answers
    assert a.search("a.docx")["results"]
    # and trying again works
    got = []
    _no_network(monkeypatch, got)
    assert a.setup_accept(["siglip2-base"], "DOWNLOAD")["ok"] is True
    _join()
    assert a.setup_offer()["state"] == "done"


def test_later_leaves_a_reminder(a):
    assert a.setup_later() == {"ok": True, "error": ""}
    r = a.setup_offer()
    assert r["show"] is False and r["state"] == "later" and r["items"]
    note = a._notify.list()["items"][0]
    assert note["kind"] == "suggestion" and note["action"]["id"] == "open_models"
    assert "Settings > Models" in note["body"] and "Nothing was downloaded" in note["body"]
    a.setup_later()
    assert len(a._notify.list()["items"]) == 1                              # one reminder, not one per Later


def test_later_after_a_failed_download_is_later_with_a_reminder(a, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("No internet connection")
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", fail)
    a.setup_accept(["siglip2-base"], "DOWNLOAD")
    _join()
    assert a.setup_offer()["show"] is True                                  # the retry window
    assert a.setup_later()["ok"] is True
    r = a.setup_offer()
    assert r["state"] == "later" and r["show"] is False
    note = a._notify.list()["items"][0]
    assert note["action"]["id"] == "open_models" and "tried again" in note["body"]


def test_details_is_later_without_a_reminder(a):
    assert a.setup_later(remind=False)["ok"] is True
    assert a.setup_offer()["show"] is False and a._settings.get("setup_offer") == "later"
    assert a._notify.list()["items"] == []


def test_later_after_download_changes_nothing(a, monkeypatch):
    _no_network(monkeypatch, [])
    a.setup_accept(["siglip2-base"], "DOWNLOAD")
    _join()
    assert a.setup_later()["ok"] is True
    assert a._settings.get("setup_offer") == "done" and a._notify.list()["items"] == []


def test_est_download_after_a_download_measured_this_pc(a, monkeypatch):
    a._dl_bps = 2 * 1048576                                 # 2 MB a second, measured by a download
    r = a.setup_offer()
    assert r["est_download"] == firstrun.duration(r["total_mb"] / 2)
    _no_network(monkeypatch, [])
    a.setup_accept(["siglip2-base"], "DOWNLOAD")
    _join()
    after = a.setup_offer()
    assert after["total_mb"] == 0 and after["est_download"] is None         # nothing left to download


def test_upgrade_install_with_models_set_up_is_not_asked_again(tmp_path):
    p = tmp_path / "old.json"
    p.write_text('{"semantic": true, "text_model": "gte-small"}', encoding="utf-8")
    assert settings_mod.Settings(str(p)).get("setup_offer") == "done"
    p.write_text('{"theme": "dark"}', encoding="utf-8")
    assert settings_mod.Settings(str(p)).get("setup_offer") == "pending"
    assert settings_mod.Settings(str(tmp_path / "new.json")).get("setup_offer") == "pending"
    assert settings_mod.coerce("setup_offer", "bogus") == "pending"


def test_total_counts_a_shared_runtime_once(a):
    items = a.setup_offer()["items"]
    talk = [dict(i, checked=True) for i in items if i["workload"] == "photo_talk"]
    assert len(talk) == 2 and talk[0]["runtime"]["id"] == talk[1]["runtime"]["id"]
    rt = talk[0]["runtime"]["size_mb"]
    assert firstrun.total_mb(talk) == talk[0]["size_mb"] + talk[1]["size_mb"] - rt


def test_duration_words():
    assert firstrun.duration(20) == "under a minute"
    assert firstrun.duration(600) == "about 10 min"
    assert firstrun.duration(2 * 3600 + 15 * 60) == "about 2 h 15 min"
    assert firstrun.duration(3 * 86400) == "about 3 days"


def test_no_photo_model_meets_the_floor_says_why(a, monkeypatch):
    monkeypatch.setattr(api_mod.hw, "scan", lambda: {**PC, "ram_gb": 3.8, "threads": 4, "cores": 2})
    r = a.setup_offer()
    assert not [i for i in r["items"] if i["workload"] == "photo_search" and i["checked"]]

