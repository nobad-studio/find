"""tools/bench_profiles.py (dev only): how it emulates the reference profiles, what it runs, when it refuses, and
how it judges the floor. A fake runner only: nothing here loads a model or starts a process."""
import importlib.util
import json
import os

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "bench_profiles.py")
_spec = importlib.util.spec_from_file_location("bench_profiles", PATH)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

PHOTO = [("siglip2-base", "fp16-vision")]
TALK = ["smolvlm2-500m", "qwen3vl-2b"]


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, spec, emu):
        self.calls.append((dict(spec), dict(emu)))
        return {"ok": True}


def _run(tmp_path, specs, runner, free=4000, game=False, **kw):
    return bench.run_all(specs, runner, str(tmp_path / "runs.jsonl"), free_mb=lambda: free, game=lambda: game,
                         total_threads=16, **kw)


def test_no_personal_paths():
    src = open(PATH, encoding="utf-8").read()
    assert "Users\\" not in src and "Users/" not in src and "aassw" not in src


def test_bench_profiles_emulates_low_mid_high(tmp_path):
    runner = FakeRunner()
    _run(tmp_path, bench.matrix(PHOTO, TALK), runner)
    by = {}
    for spec, emu in runner.calls:
        by.setdefault(spec["profile"], []).append((spec, emu))
    assert set(by) == {"low", "mid", "high"}
    low = by["low"][0][1]
    assert low["affinity"] == [0, 1, 2, 3] and low["threads"] == 4      # 4 threads by affinity
    assert low["job_memory_mb"] == 2048                                  # Find's worker cap on an 8 GB PC
    assert low["cpu_only"] is True and low["ram_mb"] == 8192
    mid = by["mid"][0][1]
    assert mid["affinity"] == list(range(8)) and mid["job_memory_mb"] == 4096 and mid["cpu_only"] is False
    high = by["high"][0][1]
    assert high["affinity"] == list(range(16)) and high["job_memory_mb"] == 4096 and high["cpu_only"] is False
    # Gentle on a PC with that many threads: 35 % of ITS threads, as a share of this PC's (job CPU rate, 1/100 %)
    assert (low["cpu_rate"], mid["cpu_rate"], high["cpu_rate"]) == (875, 1750, 3500)
    assert low["level"] == mid["level"] == high["level"] == "gentle"
    # the photo worker's threads at Gentle as the governor would give them on that PC
    assert (low["photo_threads"], mid["photo_threads"], high["photo_threads"]) == (2, 4, 8)
    # processor only on low: no Vulkan run there; Vulkan allowed on mid and high
    backends = {p: {s["backend"] for s, _e in rows if s["workload"] == "photo_talk"} for p, rows in by.items()}
    assert backends == {"low": {"cpu"}, "mid": {"cpu", "vulkan"}, "high": {"cpu", "vulkan"}}
    # mid (this PC's native profile) first, then low, then high
    order = [s["profile"] for s, _e in runner.calls]
    assert order == sorted(order, key=["mid", "low", "high"].index)


def test_resumable_skips_finished_runs(tmp_path):
    specs = bench.matrix(PHOTO, TALK)
    first = FakeRunner()
    _run(tmp_path, specs, first, max_runs=3)
    assert len(first.calls) == 3
    lines = [json.loads(x) for x in open(tmp_path / "runs.jsonl", encoding="utf-8")]
    assert [x["key"] for x in lines] == [s["key"] for s in specs[:3]]
    again = FakeRunner()
    _run(tmp_path, specs, again)
    assert [s["key"] for s, _e in again.calls] == [s["key"] for s in specs[3:]]


def test_refuses_with_little_free_memory_and_stops_for_a_game(tmp_path):
    specs = bench.matrix(PHOTO, TALK)
    runner = FakeRunner()
    out = _run(tmp_path, specs, runner, free=2400)
    assert not runner.calls and out["stopped"].startswith("only 2400 MB free")
    out = _run(tmp_path, specs, runner, game=True)
    assert not runner.calls and "full-screen" in out["stopped"]
    assert not (tmp_path / "runs.jsonl").exists() or not open(tmp_path / "runs.jsonl").read()   # nothing recorded
    # a model's own need counts too: Qwen on Vulkan needs its measured memory + 1 GB beside it
    qv = [s for s in specs if s["model"] == "qwen3vl-2b" and s["backend"] == "vulkan"][:1]
    out = _run(tmp_path, qv, runner, free=3000)
    assert not runner.calls and "needs" in out["stopped"]


def _search(**kw):
    r = {"photos": 500, "items_s": 1.0, "crashes": 0, "kills": 0, "errors": 0, "worker_peak_mb": 300,
         "searches": 50, "search_crashes": 0, "query_p95_ms": 120.0}
    r.update(kw)
    return r


def test_judge_photo_search_floor():
    use = {"visual_ndcg10": 0.78, "visual_recall10": 0.86}
    d = bench.judge_search(_search(), "mid", use, smaller=None)
    assert d["usefulness"] == d["reliability"] == d["responsiveness"] == d["memory"] == d["availability"] == "pass"
    assert d["degradation"] == "not measured"
    assert bench.judge_search(_search(items_s=0.34), "mid", use, None)["responsiveness"] == "fail"
    assert bench.judge_search(_search(query_p95_ms=301), "mid", use, None)["responsiveness"] == "fail"
    assert bench.judge_search(_search(kills=1), "mid", use, None)["reliability"] == "fail"
    assert bench.judge_search(_search(photos=499), "mid", use, None)["reliability"] == "fail"    # not the full run
    assert bench.judge_search(_search(worker_peak_mb=900), "low", use, None)["memory"] == "fail"  # 10 % of 8 GB
    assert bench.judge_search(_search(worker_peak_mb=900), "mid", use, None)["memory"] == "pass"
    assert bench.judge_search(_search(), "mid", {"visual_ndcg10": 0.59, "visual_recall10": 0.9}, None)[
        "usefulness"] == "fail"
    assert bench.judge_search(_search(), "mid", None, None)["usefulness"] == "not measured"
    assert bench.judge_search(_search(), "mid", use, smaller=_search())["degradation"] == "pass"
    assert bench.judge_search(_search(), "mid", use, smaller=_search(crashes=1))["degradation"] == "fail"


def _talk(**kw):
    r = {"runs": 10, "cold": 1, "crashes": 0, "hang_kills": 0, "kills": 0, "first_word_p95_s": 9.0, "load_s": 2.0,
         "peak_mb": 1800, "checks_passed": 3, "checks": 3, "backend": "cpu"}
    r.update(kw)
    return r


def test_judge_photo_talk_floor():
    d = bench.judge_talk(_talk(), "low", cpu_ok=True, smaller=None)
    assert all(d[k] == "pass" for k in ("usefulness", "reliability", "responsiveness", "memory", "availability"))
    assert bench.judge_talk(_talk(first_word_p95_s=15.1), "mid", True, None)["responsiveness"] == "fail"
    assert bench.judge_talk(_talk(load_s=31), "mid", True, None)["responsiveness"] == "fail"
    assert bench.judge_talk(_talk(peak_mb=2100), "low", True, None)["memory"] == "fail"      # 25 % of 8 GB
    assert bench.judge_talk(_talk(peak_mb=2100), "mid", True, None)["memory"] == "pass"
    assert bench.judge_talk(_talk(checks_passed=2), "mid", True, None)["usefulness"] == "fail"
    assert bench.judge_talk(_talk(hang_kills=1), "mid", True, None)["reliability"] == "fail"
    assert bench.judge_talk(_talk(runs=9), "mid", True, None)["reliability"] == "fail"
    assert bench.judge_talk(_talk(backend="vulkan"), "mid", cpu_ok=False, smaller=None)["availability"] == "fail"
    assert bench.judge_talk(_talk(), "mid", True, smaller=None)["degradation"] == "not measured"


def test_p95_is_nearest_rank_never_rounded_down():
    assert bench.p95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 10          # 10 samples: the slowest
    assert bench.p95(list(range(1, 51))) == 48
    assert bench.p95([]) is None


def test_floors_are_the_apps_one_table_and_fp32_has_no_borrowed_usefulness():
    from nobadfind import modelsuggest as suggest
    assert bench.FLOORS is suggest.FLOORS
    assert bench.usefulness("siglip2-base", "fp16-vision") is not None
    assert bench.usefulness("siglip2-base", "fp32-vision") is None
