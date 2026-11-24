"""The catalog's variants (spec 5.1): each model's variants, the backends they run on with measured needs, and the
reference-profile rows measured by tools/bench_profiles.py (models.measured). Only measured rows exist."""
import pytest

from nobadfind import models

PROFILES = ("low", "mid", "high")


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


@pytest.mark.parametrize("mid", [m["id"] for m in models.CATALOG if m["feature"] in ("text", "photo", "talk")])
def test_every_variant_has_numbers_for_each_backend_it_lists(mid):
    vs = models.variants(mid)
    assert vs, mid
    for v in vs:
        assert v["id"] and v["backends"], (mid, v)
        for backend, need in v["backends"].items():
            assert backend in models.BACKENDS, (mid, v["id"], backend)
            assert _number(need["ram_mb"]) and _number(need["vram_mb"]), (mid, v["id"], backend)
            speed = need.get("items_s") if models.get(mid)["feature"] != "talk" else need.get("first_word_s")
            assert _number(speed) and speed > 0, (mid, v["id"], backend)
            assert need["source"], (mid, v["id"], backend)       # the measurements.md row it comes from


def test_siglip2_has_fp16_and_fp32_vision_equivalent_to_each_other():
    by = {v["id"]: v for v in models.variants("siglip2-base")}
    assert set(by) == {"fp16-vision", "fp32-vision"}
    assert by["fp16-vision"]["equivalent_to"] == ["fp32-vision"]
    assert by["fp32-vision"]["equivalent_to"] == ["fp16-vision"]
    assert by["fp16-vision"]["session"] == {"basic_opt": True, "no_arena": True}
    from nobadfind import const
    assert tuple(by) == tuple(const.VARIANTS["siglip2-base"])        # the setting's choices, lighter first


def test_siglip_base_has_its_own_tag():
    (v,) = models.variants("siglip-base")
    assert v["equivalent_to"] == []
    assert models.vector_tag("siglip-base") != models.vector_tag("siglip2-base")
    assert v["tag"] == models.vector_tag("siglip-base")
    for s2 in models.variants("siglip2-base"):
        assert s2["tag"] == models.vector_tag("siglip2-base")


def test_measured_rows_only_for_what_the_benchmark_ran():
    for (mid, variant, backend, profile), row in models.MEASURED.items():
        assert profile in PROFILES
        assert variant in {v["id"] for v in models.variants(mid)}, (mid, variant)
        assert backend in next(v for v in models.variants(mid) if v["id"] == variant)["backends"]
        assert row["workload"] in ("photo_search", "photo_talk", "text")
        assert row["source"]
        got = models.measured(mid, variant, backend, profile)
        assert got == row and got is not row                      # a copy: callers can't change the catalog
        for k in ("items_s", "query_ms", "ram_mb", "vram_mb"):
            assert k in got
        if row["workload"] == "photo_talk":
            assert "first_word_s" in got
        if backend == "vulkan":
            assert profile != "low"                               # low is processor only


def test_not_measured_is_none():
    assert models.measured("siglip-base", "8bit", "cpu", "mid") is None       # SigLIP base isn't on the bench PC
    assert models.measured("siglip2-base", "fp16-vision", "cpu", "nowhere") is None
    assert models.measured("nope", "x", "cpu", "mid") is None
    with pytest.raises(KeyError):
        models.variants("nope")
