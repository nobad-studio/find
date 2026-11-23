"""The models methods (contract: models, model_use, model_download, model_remove, auto_configure, model_language)."""
import os

import pytest

from nobadfind import api as api_mod, models

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
    import threading
    ix = a._indexer
    ix._load_embedder = ix._load_photo = lambda: None
    ix.wake, ix.text_model = threading.Event(), None
    yield a
    s.close()


def _fake_download(a, mid):
    m = models.get(mid)
    d = models.model_dir(mid, a._models_dir)
    os.makedirs(d, exist_ok=True)
    for name, (_p, size, _sha) in m["files"].items():
        with open(os.path.join(d, name), "wb") as f:
            f.truncate(size)


def test_models_lists_the_pc_the_tiers_and_every_model(a):
    r = a.models()
    assert r["pc"] == PC and r["tier_recommended"] == "best" and r["language_focus"] == "english"
    assert {m["id"] for m in r["models"]} == set(models.ids())
    by = {m["id"]: m for m in r["models"]}
    assert by["windows-ocr"]["builtin"] and by["minilm-l6-v2"]["state"] == "not_downloaded"
    assert sum(m["recommended"] for m in r["models"] if m["feature"] == "text") == 1
    assert all(m["capable"] for m in r["models"])


def test_models_lists_the_talk_models_and_the_runtime_this_pc_needs(a, monkeypatch):
    """1.1: Settings > Models shows SmolVLM2 and Qwen (feature talk) with their graphics memory and the runtime
    this PC would use, and both runtimes; none of them is in a tier."""
    by = {m["id"]: m for m in a.models()["models"]}
    for mid in ("smolvlm2-500m", "qwen3vl-2b"):
        m = by[mid]
        assert m["feature"] == "talk" and m["state"] == "not_downloaded" and not m["recommended"]
        assert m["runtime"] == "llama-vulkan"                                  # Windows lists a graphics adapter
        assert m["vram_mb"] == models.get(mid)["vram_mb"] and m["ram_mb"] == models.get(mid)["ram_mb"]
        assert m["size_mb"] == models.size_mb(models.get(mid)) and m["source"].startswith("https://huggingface.co/")
    assert {by[r]["feature"] for r in ("llama-cpu", "llama-vulkan")} == {"runtime"}
    assert "vram_mb" not in by["llama-cpu"] and "runtime" not in by["minilm-l6-v2"]
    monkeypatch.setattr(api_mod.hw, "scan", lambda: {**PC, "gpu": "", "vram_gb": 0.0})
    assert {m["runtime"] for m in a.models()["models"] if m["feature"] == "talk"} == {"llama-cpu"}


def test_qwen_says_why_on_a_pc_that_cannot_run_it(a, monkeypatch):
    monkeypatch.setattr(api_mod.hw, "scan", lambda: {**PC, "ram_gb": 7.8, "cores": 4})
    by = {m["id"]: m for m in a.models()["models"]}
    assert by["qwen3vl-2b"]["capable"] is False
    assert by["qwen3vl-2b"]["capable_reason"].startswith("Needs 16 GB of memory")
    assert by["smolvlm2-500m"]["capable"] is True and by["smolvlm2-500m"]["capable_reason"] == ""


def test_talk_model_download_stores_no_consent(a, monkeypatch):
    got = []
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda url, dest, size, sha, name, progress=None, part=".part":
                        got.append(os.path.basename(dest)))
    assert a.model_download("smolvlm2-500m", "no")["ok"] is False and got == []
    assert a.model_download("smolvlm2-500m", "DOWNLOAD") == {"ok": True, "error": ""}
    a._mdl_thread.join(5)
    assert set(got) == {"model.gguf", "mmproj.gguf"}
    assert not a._settings.get("allow_photo_model_download") and not a._settings.get("allow_model_download")


def test_model_remove_deletes_a_runtimes_dlls(a):
    rid = "llama-cpu"
    d = models.model_dir(rid, a._models_dir)
    os.makedirs(d)
    for n, (size, _s) in models.get(rid)["files_in_zip"].items():
        with open(os.path.join(d, n), "wb") as f:
            f.truncate(size)
    assert models.ready(rid, a._models_dir)
    assert a.model_remove(rid) == {"ok": True, "error": ""}
    assert not models.ready(rid, a._models_dir) and not os.path.exists(d)


def test_language_focus_from_windows_then_the_users_choice(a, monkeypatch):
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-IN", "hi-IN"])
    assert a.models()["language_focus"] == "hindi"
    monkeypatch.setattr(api_mod.winapi, "windows_languages", lambda: ["en-US", "fr-FR"])
    assert a.models()["language_focus"] == "multilingual"
    assert a.model_language("english") == {"ok": True, "error": ""}
    assert a.models()["language_focus"] == "english"
    assert a.model_language("klingon")["ok"] is False


def test_model_use_selects_and_says_when_a_download_is_needed(a):
    r = a.model_use("text", "multilingual-e5-small")
    assert r == {"ok": True, "error": "", "needs_download": True}
    assert a._settings.get("text_model") == "multilingual-e5-small" and a._settings.get("semantic") is True
    _fake_download(a, "siglip2-base")
    assert a.model_use("photo", "siglip2-base")["needs_download"] is False
    assert a.model_use("photo", "multilingual-e5-small")["ok"] is False        # a text model for photos
    assert a.model_use("text", "nope")["ok"] is False


def test_model_download_needs_the_consent_word(a, monkeypatch):
    got = []
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda url, dest, size, sha, name, progress=None, part=".part":
                        got.append((url, os.path.basename(dest), size, sha)))
    assert a.model_download("multilingual-e5-small", "yes")["ok"] is False and got == []
    assert a.model_download("windows-ocr", "DOWNLOAD")["ok"] is False
    assert a.model_download("multilingual-e5-small", "DOWNLOAD") == {"ok": True, "error": ""}
    a._mdl_thread.join(5)
    m = models.get("multilingual-e5-small")
    assert {g[1] for g in got} == set(m["files"])
    assert all(g[0].startswith("https://huggingface.co/" + m["repo"] + "/resolve/" + m["rev"] + "/") for g in got)
    assert a._settings.get("allow_model_download") is True        # the stored consent
    assert a.downloads()["multilingual-e5-small"]["state"] in ("ready", "missing")


def test_model_download_installs_a_llama_runtime(a, monkeypatch):
    """The llama.cpp runtimes go through runtime.install (the zip, then only its pinned DLLs), same consent word."""
    from nobadfind.vlm import runtime
    calls = []

    def fake_install(mid, data_dir, progress):
        calls.append((mid, data_dir))
        progress("zip", 7, 10)
        return os.path.join(data_dir, "runtime", mid)
    monkeypatch.setattr(runtime, "install", fake_install)
    monkeypatch.setattr(api_mod.embed, "_fetch_verified", lambda *a, **k: pytest.fail("not the plain model path"))
    assert a.model_download("llama-vulkan", "yes")["ok"] is False and calls == []
    assert a.model_download("llama-cpu", "DOWNLOAD") == {"ok": True, "error": ""}
    a._mdl_thread.join(5)
    assert calls == [("llama-cpu", a._models_dir)]
    st = a._mdl["llama-cpu"]
    assert st["state"] == "ready" and st["got"] == 7 and st["size"] == models.get("llama-cpu")["files"]["zip"][1]
    assert not a._settings.get("allow_photo_model_download")   # a runtime grants no model consent

    def failing(mid, data_dir, progress):
        raise IOError("ggml.dll: checksum mismatch, runtime rejected")
    monkeypatch.setattr(runtime, "install", failing)
    a.model_download("llama-vulkan", "DOWNLOAD")
    a._mdl_thread.join(5)
    assert a._mdl["llama-vulkan"]["state"] == "missing" and "checksum" in a._mdl["llama-vulkan"]["error"]


def test_meaning_and_photo_states_follow_the_model_in_use(a):
    """The Welcome and Index buttons download the chosen model with model_download: the plain meaning / photo
    states (status, download events, Index cards) follow it, not only the old fixed download."""
    a.model_use("text", "multilingual-e5-small")
    assert a.downloads()["meaning"]["state"] == "missing"
    a._mdl = {"multilingual-e5-small": {"state": "downloading", "got": 5, "size": 10, "error": ""}}
    assert a.downloads()["meaning"] == {"state": "downloading", "got": 5, "size": 10, "error": ""}
    assert a.status()["model"]["state"] == "downloading"
    a._mdl = {}
    _fake_download(a, "multilingual-e5-small")
    assert a.downloads()["meaning"]["state"] == "ready"
    a._photo_model.update(state="downloading", got=1, size=2)          # the old download, while it runs
    assert a.status()["photo_model"]["state"] == "downloading"


def test_model_remove_keeps_builtin_and_active_models(a):
    _fake_download(a, "gte-small")
    assert a.model_remove("windows-ocr")["ok"] is False
    a._indexer.text_model = "gte-small"
    assert a.model_remove("gte-small")["ok"] is False
    a._indexer.text_model = "minilm-l6-v2"
    assert a.model_remove("gte-small") == {"ok": True, "error": ""}
    assert not models.ready("gte-small", a._models_dir)


def test_auto_configure_applies_the_tier_and_lists_the_downloads(a):
    r = a.auto_configure()
    assert r["tier"] == "best" and {s["feature"] for s in r["steps"]} == {"text", "photo", "ocr"}
    text = next(s for s in r["steps"] if s["feature"] == "text")
    assert text["needs_download"] is True and a._settings.get("text_model") == text["id"]
    assert next(s for s in r["steps"] if s["feature"] == "ocr")["needs_download"] is False


def test_status_shows_the_rebuild_as_its_own_phase(a):
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["rebuild"]["state"] == "off"
    a._store.set_meta("vec_model_next", "gte-small")
    a._totals = (0, None, {})                                 # counts again now
    a._indexer.status["phase"] = "rebuild"
    ph = {p["id"]: p for p in a.status()["phases"]}
    assert ph["rebuild"]["state"] == "running" and ph["rebuild"]["label"].startswith("Rebuilding")


def test_model_folder_opens_only_a_catalog_models_folder(tmp_path, monkeypatch):
    """0.9.0: Settings > Models shows where each model is downloaded and opens that folder; an id, never a path."""
    from nobadfind import api as api_mod, models, settings
    opened = []
    monkeypatch.setattr(api_mod, "open_folder", lambda p: opened.append(p) or True)
    st = settings.Settings(str(tmp_path / "s.json"))
    a = api_mod.Api(None, st, type("Ix", (), {"embedder": None, "photo_text": None})(), None)
    a._models_dir = str(tmp_path)
    assert a.model_folder("windows-ocr")["ok"] is False                       # built into Windows: no folder
    assert a.model_folder("..\..\Windows")["ok"] is False
    assert opened == []
    assert a.model_folder("siglip-base")["ok"] is True                        # not downloaded: the data folder
    assert opened == [str(tmp_path)]
    d = models.model_dir("siglip-base", str(tmp_path))
    import os
    os.makedirs(d)
    assert a.model_folder("siglip-base")["ok"] and opened[-1] == d            # downloaded: its own folder
    rows = {m["id"]: m for m in a.models()["models"]}
    assert rows["siglip-base"]["dir"] == d and rows["windows-ocr"]["dir"] == ""


def test_keep_models_loaded_skips_the_idle_release(tmp_path):
    from nobadfind import embed, indexer, settings
    st = settings.Settings(str(tmp_path / "s.json"))
    ix = indexer.Indexer.__new__(indexer.Indexer)
    ix.settings = st
    freed = []

    class L(embed.Lazy):
        def __init__(self):
            pass

        def release_if_idle(self, idle=None):
            freed.append(idle)
    ix.embedder, ix.photo_text = L(), None
    ix.release_idle_models()
    assert freed == [None]
    st.update({"models_stay_loaded": True})
    ix.release_idle_models()
    assert freed == [None]                     # kept loaded
    ix.release_models()                        # the window closed: always freed
    assert freed == [None, 0]


def test_auto_configure_and_models_take_the_photo_suggestion(a, monkeypatch):
    """Task 5: the photo model comes from the measured floors (modelsuggest), the text model from the tier; talk is
    offered there but never configured or downloaded with the others."""
    seen = {}

    def fake(facts, classes, live, goal, focus, **_kw):
        seen.update(goal=goal, live=live, classes=classes)
        return {"text": [], "photo_talk": [{"model": "smolvlm2-500m", "outcome": "suggested"}],
                "photo_search": [{"model": "siglip-base", "outcome": "suggested"}]}

    monkeypatch.setattr(api_mod.modelsuggest, "for_pc", fake)
    r = a.auto_configure()
    assert r["tier"] == "best" and a._settings.get("photo_model") == "siglip-base"
    assert {s["feature"] for s in r["steps"]} == {"text", "photo", "ocr"}
    assert seen["goal"] == a._settings.get("performance_goal") and seen["live"]["runtime"] == {
        "photo_talk": "vulkan"} and "gpu" in seen["classes"]
    assert seen["live"]["settings"] == {"gpu_reserve_min_mb": a._settings.get("gpu_reserve_min_mb")}
    by = {m["id"]: m for m in a.models()["models"]}
    assert by["siglip-base"]["recommended"] and not by["siglip2-base"]["recommended"]
    assert not by["smolvlm2-500m"]["recommended"]


def test_auto_configure_turns_photo_off_when_no_measured_model_fits(a, monkeypatch):
    monkeypatch.setattr(api_mod.modelsuggest, "for_pc", lambda *x, **k: {
        "text": [], "photo_talk": [], "photo_search": [{"model": "siglip2-base", "outcome": "not_recommended"}]})
    r = a.auto_configure()
    assert a._settings.get("photo_meaning") is False
    assert next(s for s in r["steps"] if s["feature"] == "photo")["id"] == ""


def test_suggestions_use_the_goal_and_the_users_gpu_reserve(a, monkeypatch):
    seen = {}
    monkeypatch.setattr(api_mod.modelsuggest, "for_pc", lambda f, c, live, goal, focus, **k: seen.update(
        live=live, goal=goal) or {"text": [], "photo_talk": [], "photo_search": []})
    a._settings.update({"power": "boost", "performance_goal": "fast", "gpu_reserve_min_mb": 2048})
    a.auto_configure()
    assert seen["goal"] == "fast" and seen["live"]["settings"]["gpu_reserve_min_mb"] == 2048


def test_real_suggestion_on_the_reference_pc_keeps_siglip2(a):
    assert a.auto_configure()["tier"] == "best"
    assert a._settings.get("photo_model") == "siglip2-base" and a._settings.get("photo_meaning") is True
