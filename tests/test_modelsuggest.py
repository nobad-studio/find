"""Suggestions from the floors (spec 2026-11-22 hardware intelligence §5.2, plan "Reference profiles, workloads,
floors and outcomes"). Every test but the last few uses synthetic measured rows and a synthetic catalog: the logic
holds no model names."""
from nobadfind import models, profile
from nobadfind import modelsuggest as suggest

GB = 1024

# an Iris Xe-like PC: 12 cores / 16 threads, 15.7 GB, built-in graphics on shared memory, Vulkan for llama.cpp
MID_PC = {"ram_gb": 15.7, "cores": 12, "threads": 16, "avx2": True, "ssd": True, "gpu": "Iris Xe", "vram_gb": 0.1,
          "directml": False,
          "gpus": [{"vendor": "intel", "name": "Iris Xe", "dedicated_mb": 128, "shared_mb": 8000, "integrated": True}],
          "backends": {"onnx": ["cpu"], "llamacpp": ["vulkan", "cpu"]}}
# a discrete card with its own memory
GPU_PC = dict(MID_PC, gpu="RTX", vram_gb=8.0,
              gpus=[{"vendor": "nvidia", "name": "RTX", "dedicated_mb": 8192, "shared_mb": 8000, "integrated": False}])
LOW_PC = {"ram_gb": 7.8, "cores": 4, "threads": 8, "avx2": True, "ssd": True, "gpu": "", "vram_gb": 0.0,
          "directml": False, "gpus": [], "backends": {"onnx": ["cpu"], "llamacpp": ["cpu"]}}


def _cat(*entries):
    """[(workload, id, [(variant, equivalent_to)])] -> a synthetic catalog."""
    return [{"id": mid, "workload": w, "name": mid.upper(), "variants": [{"id": v, "equivalent_to": list(eq)}
                                                                     for v, eq in vs]}
            for w, mid, vs in entries]


def talk(**kw):
    r = {"workload": "photo_talk", "first_word_s": 5.0, "load_s": 1.0, "ram_mb": 900, "ws_mb": 800, "vram_mb": 0,
         "shared_mb": 600, "runs": 10, "crashes": 0, "hang_kills": 0, "kills": 0, "checks_passed": 3,
         "cold_first_word_s": 4.0}
    r.update(kw)
    r.setdefault("need_mb", max(r["ram_mb"], r["ws_mb"], r["shared_mb"]))
    return r


def search(**kw):
    r = {"workload": "photo_search", "items_s": 1.5, "query_ms": 200.0, "ram_mb": 500, "ws_mb": 520, "vram_mb": 0,
         "shared_mb": 0, "photos": 500, "searches": 50, "crashes": 0, "kills": 0, "visual_ndcg10": 0.8,
         "visual_recall10": 0.85}
    r.update(kw)
    r.setdefault("need_mb", max(r["ram_mb"], r["ws_mb"], r["shared_mb"]))
    return r


def _talk_rows(mid, profile_="mid", cpu=None, **kw):
    """A talk model measured on llama-vulkan and on the processor (the availability floor needs the CPU path)."""
    return {(mid, "v", "vulkan", profile_): talk(**kw), (mid, "v", "cpu", profile_): talk(shared_mb=0, **(cpu or {}))}


def run(facts, rows, catalog, goal="balanced", live=None):
    return suggest.for_pc(facts, profile.classify(facts), live or {}, goal, "multilingual", rows=rows,
                          catalog=catalog)


def by_model(entries):
    return {e["model"]: e for e in entries}


def test_outcomes_suggested_upgrade_not_recommended():
    rows = {}
    rows.update(_talk_rows("light", need_mb=1000))
    rows.update(_talk_rows("heavy", ram_mb=2500, need_mb=2500, first_word_s=12.0, load_s=6.0))
    rows.update(_talk_rows("slow", first_word_s=20.0))                              # misses the 15 s floor
    rows.update(_talk_rows("crashy", crashes=1))                                    # fails reliability
    rows.update(_talk_rows("huge", ram_mb=20000, need_mb=20000))                    # over the PC itself
    cat = _cat(*[("photo_talk", m, [("v", ())]) for m in ("light", "heavy", "slow", "crashy", "huge")])
    out = by_model(run(MID_PC, rows, cat)["photo_talk"])
    assert out["light"]["outcome"] == "suggested" and out["light"]["backend"] == "vulkan"
    assert out["heavy"]["outcome"] == "upgrade" and out["slow"]["outcome"] == "upgrade"
    assert out["crashy"]["outcome"] == "not_recommended" and out["huge"]["outcome"] == "not_recommended"
    assert out["light"]["why"].startswith("Suggested: LIGHT: first word about 5 s")
    assert "shared with the built-in graphics" in out["light"]["why"] and "similar PC" in out["light"]["why"]
    assert out["heavy"]["why"].startswith("Upgrade: HEAVY: more memory (2,500 MB), longer loading and answers")
    assert "20 s" in out["slow"]["why"] and "15 s" in out["slow"]["why"]
    assert "crash" in out["crashy"]["why"] and "20,000 MB" in out["huge"]["why"]
    assert out["slow"]["floors"]["responsiveness"] is False and out["light"]["floors"]["memory"] is True
    c = out["light"]["cost_here"]
    assert c["answer_s"] == 5.0 and c["load_s"] == 1.0 and c["ram_mb"] == 1000 and c["measured_on"] == "similar PC"


def test_8_cores_8_gb_is_memory_limited_not_high():
    pc = dict(GPU_PC, ram_gb=7.8, cores=8, threads=16, backends={"onnx": ["cpu", "directml"],
                                                                 "llamacpp": ["vulkan", "cpu"]})
    like = suggest.like(pc, profile.classify(pc))
    assert like["profile"] == "low" and "memory" in like["why"].lower()
    rows = {("m", "v", "cpu", "high"): search(), ("m", "v", "cpu", "mid"): search()}
    out = run(pc, rows, _cat(("photo_search", "m", [("v", ())])))["photo_search"]
    assert out[0]["outcome"] == "not_measured"                    # only measured on bigger PCs


def test_shared_gpu_memory_counts_against_ram():
    """Built-in graphics (Iris Xe-like): the graphics memory is system RAM, counted in the RAM need once."""
    cat = _cat(("photo_talk", "m", [("v", ())]))
    # a measured shared figure overlaps private memory: the biggest single figure, never a sum
    rows = _talk_rows("m", ram_mb=1000, ws_mb=900, shared_mb=1500, need_mb=1500)
    e = run(MID_PC, rows, cat)["photo_talk"][0]
    assert e["cost_here"]["ram_mb"] == 1500 and e["outcome"] == "suggested"
    # shared memory over the floor makes it miss Memory, though it is not GPU capacity
    rows = _talk_rows("m", ram_mb=1000, ws_mb=900, shared_mb=4500, need_mb=4500)
    e = run(MID_PC, rows, cat)["photo_talk"][0]
    assert e["outcome"] == "upgrade" and e["floors"]["memory"] is False       # 4,500 > 25 % of 15.7 GB


def test_builtin_graphics_memory_is_not_added_a_second_time():
    # a row measured on built-in graphics whose adapter also reported a little "dedicated" memory: need_mb already
    # holds its graphics memory (spec 6.1: never added a second time)
    rows = _talk_rows("m", ram_mb=1000, ws_mb=900, shared_mb=1500, vram_mb=128, need_mb=1500, gpu="integrated")
    e = run(MID_PC, rows, _cat(("photo_talk", "m", [("v", ())])))["photo_talk"][0]
    assert e["cost_here"]["ram_mb"] == 1500 and "gpu_mb" not in e["cost_here"]


def test_gpu_rows_apply_only_to_the_same_kind_of_graphics():
    """A GPU-backend row measured on built-in graphics says nothing about a discrete card, and the reverse: not
    measured. Processor rows still apply."""
    rtx = dict(GPU_PC, threads=12, gpus=[{"vendor": "nvidia", "name": "RTX", "dedicated_mb": 6144,
                                          "shared_mb": 8000, "integrated": False}])
    assert suggest.like(rtx, profile.classify(rtx))["profile"] == "mid"
    out = by_model(suggest.for_pc(rtx, profile.classify(rtx), {}, "balanced", "multilingual")["photo_talk"])
    assert {e["outcome"] for e in out.values()} == {"not_measured"}
    assert "built-in graphics" in out["qwen3vl-2b"]["why"]
    out = by_model(suggest.for_pc(rtx, profile.classify(rtx), {"runtime": {"photo_talk": "cpu"}}, "balanced",
                                  "multilingual")["photo_talk"])
    assert out["smolvlm2-500m"]["outcome"] == "suggested"
    # the reverse: a row from a discrete card on built-in graphics
    rows = _talk_rows("m", ram_mb=1000, ws_mb=900, shared_mb=0, vram_mb=2000, need_mb=1000)
    e = run(MID_PC, rows, _cat(("photo_talk", "m", [("v", ())])))["photo_talk"][0]
    assert e["outcome"] == "not_measured" and "its own memory" in e["why"]


def test_dedicated_vram_is_gpu_capacity():
    cat = _cat(("photo_talk", "m", [("v", ())]))
    assert suggest.like(GPU_PC, profile.classify(GPU_PC))["profile"] == "high"
    rows = _talk_rows("m", "high", ram_mb=1000, ws_mb=900, shared_mb=0, vram_mb=2000, need_mb=1000)
    e = run(GPU_PC, rows, cat, live={"gpu_free_mb": 3072})["photo_talk"][0]
    assert e["outcome"] == "suggested" and e["cost_here"]["ram_mb"] == 1000 and e["cost_here"]["gpu_mb"] == 2000
    # 3,072 MB free -> reserve 512 -> 2,560 usable: a 2,700 MB peak is not scheduled on that card
    rows = _talk_rows("m", "high", ram_mb=1000, ws_mb=900, shared_mb=0, vram_mb=2700, need_mb=1000)
    rows.update(_talk_rows("m", ram_mb=1000, ws_mb=900, shared_mb=0, vram_mb=2700, need_mb=1000))
    e = run(GPU_PC, rows, cat, live={"gpu_free_mb": 3072})["photo_talk"][0]
    assert e["outcome"] == "not_recommended" and "2,560 MB" in e["why"]


def test_the_users_gpu_reserve_minimum_is_a_safety_limit():
    cat = _cat(("photo_talk", "m", [("v", ())]))
    rows = _talk_rows("m", "high", ram_mb=1000, ws_mb=900, shared_mb=0, vram_mb=2000, need_mb=1000)
    live = {"gpu_free_mb": 3072}
    assert run(GPU_PC, rows, cat, live=live)["photo_talk"][0]["outcome"] == "suggested"
    live["settings"] = {"gpu_reserve_min_mb": 1536}                  # 3,072 - 1,536 = 1,536 MB usable
    e = run(GPU_PC, rows, cat, live=live)["photo_talk"][0]
    assert e["outcome"] == "not_recommended" and "1,536 MB" in e["why"]


def test_unmeasured_model_is_never_suggested():
    cat = _cat(("photo_search", "a", [("v", ())]), ("photo_search", "b", [("v", ())]),
               ("photo_search", "c", [("v", ())]))
    rows = {("a", "v", "cpu", "low"): search(),                                # measured on another profile only
            ("b", "v", "cpu", "mid"): search(visual_ndcg10=None, visual_recall10=None)}    # usefulness missing
    out = by_model(run(MID_PC, rows, cat)["photo_search"])
    assert {e["outcome"] for e in out.values()} == {"not_measured"}
    assert "not measured" in out["c"]["why"].lower()
    # the real table: only mid was measured, so a low-like and a high-like PC get no suggestion at all
    for pc in (LOW_PC, dict(GPU_PC, backends={"onnx": ["cpu", "directml"], "llamacpp": ["vulkan", "cpu"]})):
        res = suggest.for_pc(pc, profile.classify(pc), {}, "balanced", "multilingual")
        assert suggest.like(pc, profile.classify(pc))["profile"] in ("low", "high")
        assert not [e for w in res.values() for e in w if e["outcome"] == "suggested"]


def test_suggest_none_when_no_model_meets_floors():
    """Review Focus 1: a very-low-RAM PC fits no photo model under the floors: no suggestion, a plain reason."""
    pc = dict(LOW_PC, ram_gb=3.9, cores=4, threads=4)
    rows = {("a", "v", "cpu", "low"): search(ram_mb=700, ws_mb=700, need_mb=700),
            ("b", "v", "cpu", "low"): search(ram_mb=3000, ws_mb=3000, need_mb=3000)}
    cat = _cat(("photo_search", "a", [("v", ())]), ("photo_search", "b", [("v", ())]))
    out = run(pc, rows, cat)["photo_search"]
    assert not [e for e in out if e["outcome"] == "suggested"]
    assert by_model(out)["b"]["outcome"] == "not_recommended"
    why = suggest.none_reason("photo_search", out)
    assert why.startswith("No model for searching photos meets the floor on this PC") and "MB" in why
    assert suggest.none_reason("photo_search", run(MID_PC, {("a", "v", "cpu", "mid"): search()}, cat[:1])[
        "photo_search"]) == ""


def test_best_usefulness_among_those_meeting_floors():
    rows = {("ok", "v", "cpu", "mid"): search(visual_ndcg10=0.70, ram_mb=300, ws_mb=300, need_mb=300),
            ("better", "v", "cpu", "mid"): search(visual_ndcg10=0.80, ram_mb=600, ws_mb=600, need_mb=600),
            ("best_slow", "v", "cpu", "mid"): search(visual_ndcg10=0.90, query_ms=500.0),
            ("useless", "v", "cpu", "mid"): search(visual_ndcg10=0.50)}
    cat = _cat(*[("photo_search", m, [("v", ())]) for m in ("ok", "better", "best_slow", "useless")])
    out = by_model(run(MID_PC, rows, cat)["photo_search"])
    assert out["better"]["outcome"] == "suggested"
    assert out["best_slow"]["outcome"] == "upgrade" and "500 ms" in out["best_slow"]["why"]
    assert out["ok"]["outcome"] == "lighter"
    assert out["ok"]["why"].startswith("Lighter option: OK: finds less than BETTER")
    assert "uses less memory (300 MB on a similar PC)" in out["ok"]["why"]
    assert not [e for e in out.values() if e["outcome"] == "upgrade" and "finds less" in e["why"]]
    assert out["useless"]["outcome"] == "not_recommended"
    assert out["better"]["cost_here"]["query_ms"] == 200.0 and out["better"]["cost_here"]["items_s"] == 1.5


def test_workloads_are_suggested_separately():
    rows = {("s", "v", "cpu", "mid"): search()}
    rows.update(_talk_rows("t", crashes=2))
    cat = _cat(("photo_search", "s", [("v", ())]), ("photo_talk", "t", [("v", ())]))
    out = run(MID_PC, rows, cat)
    assert set(out) == {"text", "photo_search", "photo_talk"}
    assert [e["model"] for e in out["photo_search"]] == ["s"] and out["photo_search"][0]["outcome"] == "suggested"
    assert [e["model"] for e in out["photo_talk"]] == ["t"] and out["photo_talk"][0]["outcome"] == "not_recommended"
    assert out["text"] == []


def test_goal_quiet_picks_lighter_equivalent():
    rows = {("m", "small", "cpu", "mid"): search(ram_mb=200, ws_mb=200, need_mb=200, items_s=2.9),
            ("m", "big", "cpu", "mid"): search(ram_mb=370, ws_mb=370, need_mb=370, items_s=4.6)}
    cat = _cat(("photo_search", "m", [("small", ("big",)), ("big", ("small",))]))
    for goal, want in (("quiet", "small"), ("balanced", "small"), ("fast", "big")):
        out = run(MID_PC, rows, cat, goal=goal)["photo_search"]
        assert [(e["model"], e["variant"]) for e in out] == [("m", want)], goal
    # fast takes the faster one only with 2x margin: 370 x 2 > the 600 MB free now (after Windows' 1.5 GB)
    out = run(MID_PC, rows, cat, goal="fast", live={"free_ram_mb": 2100})["photo_search"]
    assert out[0]["variant"] == "small"


def test_floors_are_data(monkeypatch):
    rows = _talk_rows("m", first_word_s=5.0)
    cat = _cat(("photo_talk", "m", [("v", ())]))
    assert run(MID_PC, rows, cat)["photo_talk"][0]["outcome"] == "suggested"
    monkeypatch.setitem(suggest.FLOORS["photo_talk"], "first_word_p95_s", 4)
    assert run(MID_PC, rows, cat)["photo_talk"][0]["outcome"] == "upgrade"
    monkeypatch.setitem(suggest.FLOORS["photo_talk"], "first_word_p95_s", 15)
    monkeypatch.setitem(suggest.FLOORS["photo_talk"], "ram_share", 0.01)
    assert run(MID_PC, rows, cat)["photo_talk"][0]["outcome"] == "upgrade"


def test_reference_pc_from_the_measured_table():
    """The real MEASURED rows on the reference PC (the mid example): SmolVLM2 suggested on the graphics card's shared
    memory, Qwen3-VL an upgrade; SigLIP 2 fp16 suggested for search; the unmeasured models are not_measured."""
    pc = dict(MID_PC, threads=16)
    like = suggest.like(pc, profile.classify(pc))
    assert like["profile"] == "mid" and like["text"] == "This PC is like: Mid"
    out = suggest.for_pc(pc, profile.classify(pc), {}, "balanced", "multilingual")
    t = by_model(out["photo_talk"])
    smol, qwen = models.get("smolvlm2-500m")["name"], models.get("qwen3vl-2b")["name"]
    assert t["smolvlm2-500m"]["outcome"] == "suggested"
    assert t["smolvlm2-500m"]["why"].startswith(f"Suggested: {smol}: first word about 6 s, 663 MB of memory, "
                                                "shared with the built-in graphics")
    assert t["qwen3vl-2b"]["outcome"] == "upgrade"
    assert t["qwen3vl-2b"]["why"].startswith(f"Upgrade: {qwen}: more memory (2,491 MB), longer loading and answers")
    s = by_model(out["photo_search"])
    assert (s["siglip2-base"]["outcome"], s["siglip2-base"]["variant"]) == ("suggested", "fp16-vision")
    assert s["siglip-base"]["outcome"] == "not_measured"
    assert {e["outcome"] for e in out["text"]} == {"not_measured"} and out["text"]
    # on the processor runtime Qwen misses the 15 s first word
    out = suggest.for_pc(pc, profile.classify(pc), {"runtime": {"photo_talk": "cpu"}}, "balanced", "multilingual")
    t = by_model(out["photo_talk"])
    assert t["smolvlm2-500m"]["outcome"] == "suggested" and t["qwen3vl-2b"]["outcome"] == "upgrade"
    assert t["qwen3vl-2b"]["floors"]["responsiveness"] is False


def test_fp32_variant_has_no_usefulness_of_its_own():
    rows = dict(models.MEASURED)
    fp16 = rows[("siglip2-base", "fp16-vision", "cpu", "mid")]
    rows[("siglip2-base", "fp32-vision", "cpu", "mid")] = dict(fp16, visual_ndcg10=None, visual_recall10=None)
    out = suggest.for_pc(MID_PC, profile.classify(MID_PC), {}, "fast", "multilingual", rows=rows)
    e = by_model(out["photo_search"])["siglip2-base"]
    assert e["variant"] == "fp16-vision"                  # fp32 can't meet the floor without its own usefulness


def test_recommend_choice_takes_the_photo_suggestion_and_never_talk():
    sug = {"text": [], "photo_talk": [{"model": "smolvlm2-500m", "outcome": "suggested"}],
           "photo_search": [{"model": "siglip2-base", "outcome": "suggested"}]}
    pc = dict(MID_PC, ram_gb=11.8, cores=6)                         # the tier alone would take SigLIP base
    c = models.recommend_choice(pc, "multilingual", sug)
    assert c["photo"] == "siglip2-base" and "talk" not in c and c["text"] == "multilingual-e5-small"
    none = dict(sug, photo_search=[{"model": "siglip2-base", "outcome": "not_recommended"}])
    assert models.recommend_choice(pc, "multilingual", none)["photo"] == ""          # measured: nothing fits
    unknown = dict(sug, photo_search=[{"model": "siglip2-base", "outcome": "not_measured"}])
    assert models.recommend_choice(pc, "multilingual", unknown)["photo"] == "siglip-base"   # the tier, as before
