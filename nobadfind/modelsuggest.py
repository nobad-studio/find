"""Suggested models from the floors (spec 2026-11-22 hardware intelligence §5.2; plan "Reference profiles,
workloads, floors and outcomes"). Pure: no I/O, no model names in the logic.

A PC is never put in a tier. Its budget is its own: installed RAM and the safety limits (the RAM kept for Windows,
the WORKERS cap, the GPU reserve), live usable memory when known, and its per-axis classes (which graphics backends
are usable). Each model's MEASURED cost, from the nearest reference profile ("like", an explanation only) or from
this PC, is checked against that budget and against FLOORS. Per workload (text, photo_search, photo_talk), each
model gets one outcome:
  suggested        the most useful model that meets every required floor (ties: the lighter);
  upgrade          a stronger model (as useful or more, heavier) that fits the safety limits but costs more than
                   the suggestion or misses its experience (slower answers, more memory than the floor allows);
  lighter          meets the floors too, but is weaker or lighter than the suggestion (finds less, less memory);
  not_recommended  its measured needs exceed what this PC can give, or it failed Reliability or Usefulness, or
                   it misses the floor while finding less than the suggestion;
  not_measured     no measurement for a PC like this one (or no floor for the workload): never suggested.
Shared GPU memory (built-in graphics) is system RAM: counted against the RAM need once, never as GPU capacity.
A GPU-backend row applies only to the kind of graphics it was measured on (built-in or a card with its own memory):
on the other kind it is not measured. Processor rows apply everywhere.
"""
from . import jobs, models
from .governor import LIMITS, gpu_reserve_mb

WORKLOADS = ("text", "photo_search", "photo_talk")
_FEATURE = {"text": "text", "photo": "photo_search", "talk": "photo_talk"}
_FAMILY = {"text": "onnx", "photo_search": "onnx", "photo_talk": "llamacpp"}
_LABEL = {"text": "meaning search", "photo_search": "searching photos", "photo_talk": "talking about a photo"}
DIMENSIONS = ("usefulness", "reliability", "responsiveness", "memory", "availability", "degradation")
# graceful degradation needs a run on the next smaller profile, not measured yet (Task 4): it is reported, and only
# gates a suggestion once it is listed in "required"
_REQUIRED = ("usefulness", "reliability", "responsiveness", "memory", "availability")

# The floor table (plan, maintainer 2026-11-22; the first proposal, tuned here without code changes). Text has no
# floor yet, so text models are "not_measured" until one is set and measured.
FLOORS = {
    "photo_search": {"ndcg10": 0.60, "recall10": 0.70,             # usefulness: visual / described searches
                     "photos": 500, "searches": 50,                # reliability: 0 crashes, 0 watchdog kills
                     "query_p95_ms": 300, "items_s": 0.35,         # responsiveness (10,000 photos in <= 8 h)
                     "ram_share": 0.10, "workers_cap": True,       # memory: 10 % of installed, within WORKERS
                     "required": _REQUIRED},
    "photo_talk": {"checks": 3,                                    # usefulness: describe / ask / compare
                   "runs": 10, "cold_loads": 1,                    # reliability: 0 crashes, 0 hang kills
                   "first_word_p95_s": 15, "load_s": 30,           # responsiveness
                   "ram_share": 0.25, "workers_cap": False,        # memory: 25 % (shared graphics counted)
                   "required": _REQUIRED},
}
_RANK = {"meets": 0, "upgrade": 1, "not_measured": 2, "not_recommended": 3}
_ORDER = {"suggested": 0, "upgrade": 1, "lighter": 2, "not_recommended": 3, "not_measured": 4}
_KIND = {"integrated": "built-in graphics", "discrete": "a graphics card with its own memory"}


def _mb(x):
    return f"{int(round(x)):,} MB"


def _n(x):
    return f"{round(float(x), 2):g}"


def like(facts, classes):
    """{"profile": "low" | "mid" | "high", "similar": bool, "why", "text"}: the nearest reference profile whose
    emulated resources this PC meets on every axis (high: 16 threads, 16 GB and a graphics card with 4 GB of its
    own; mid: 8 threads, 16 GB; low: 4 threads, 8 GB). Below low it is still "low" with similar False: speed
    measured there would claim more than this PC gives. An explanation and a row key, never a budget."""
    ram = float(facts.get("ram_gb") or 0)
    threads = int(facts.get("threads") or facts.get("cores") or 0)
    gpu = any(c in ("balanced", "performance") for c in ((classes or {}).get("gpu") or {}).values())
    mem, thr = f"memory: {ram:g} GB installed", f"{threads} processor threads"
    if threads >= 16 and ram >= 15 and gpu:
        p, similar, why = "high", True, f"{thr}, {ram:g} GB and a graphics card with 4 GB or more of its own"
    elif threads >= 8 and ram >= 15:
        p, similar = "mid", True
        why = f"{thr} and {ram:g} GB; " + ("High needs 16 threads" if threads < 16 else
                                            "High needs a graphics card with 4 GB or more of its own")
    else:
        p, similar = "low", threads >= 4 and ram >= 7.5
        lim = [mem + " (Mid was measured with 16 GB)"] if ram < 15 else []
        lim += [f"{thr} (Mid was measured with 8)"] if threads < 8 else []
        why = "; ".join(lim) + ("" if similar else "; smaller than Low (4 threads, 8 GB): its speed isn't measured")
    return {"profile": p, "similar": similar, "why": why, "text": f"This PC is like: {p.title()}"}


def _catalog(focus):
    text_ok = set((models.TEXT_CHOICE.get(focus) or models.TEXT_CHOICE["multilingual"]).values())
    out = []
    for m in models.CATALOG:
        w = _FEATURE.get(m["feature"])
        if w is None or (w == "text" and m["id"] not in text_ok):
            continue
        out.append({"id": m["id"], "workload": w, "name": m["name"],
                    "variants": [{"id": v["id"], "equivalent_to": list(v["equivalent_to"])}
                                 for v in models.variants(m["id"])]})
    return out


def _adapter(facts):
    """The adapter a GPU backend would use: the discrete card with the most dedicated memory, else built-in."""
    gpus = list(facts.get("gpus") or [])
    if not gpus and facts.get("gpu"):
        mb = int(float(facts.get("vram_gb") or 0) * 1024)
        gpus = [{"name": facts["gpu"], "dedicated_mb": mb, "integrated": mb < 512}]
    discrete = [g for g in gpus if not g.get("integrated")]
    if discrete:
        return max(discrete, key=lambda g: int(g.get("dedicated_mb") or 0))
    return gpus[0] if gpus else None


def _backend(workload, facts, live):
    got = ((live or {}).get("runtime") or {}).get(workload)
    if got:
        return got
    if workload == "photo_talk":
        return "vulkan" if "vulkan" in ((facts.get("backends") or {}).get("llamacpp") or []) else "cpu"
    return "cpu"


def _reliable(w, r, f):
    if w == "photo_search":
        if any(r.get(k) is None for k in ("photos", "searches", "crashes", "kills")):
            return None
        return r["photos"] >= f["photos"] and r["searches"] >= f["searches"] and not r["crashes"] and not r["kills"]
    if any(r.get(k) is None for k in ("runs", "crashes", "kills")):
        return None
    return (r["runs"] >= f["runs"] and (r.get("cold_first_word_s") is not None or f["cold_loads"] <= 0)
            and not r["crashes"] and not r.get("hang_kills") and not r["kills"])


def _useful(w, r, f):
    if w == "photo_search":
        n, rc = r.get("visual_ndcg10"), r.get("visual_recall10")
        return None if n is None or rc is None else (n >= f["ndcg10"] and rc >= f["recall10"])
    k = r.get("checks_passed")
    return None if k is None else k >= f["checks"]


def _score(w, r):
    return (r.get("visual_ndcg10") or 0) if w == "photo_search" else (r.get("checks_passed") or 0)


def _quick(w, r, f):
    if w == "photo_search":
        q, i = r.get("query_ms"), r.get("items_s")
        return None if q is None or i is None else (q <= f["query_p95_ms"] and i >= f["items_s"])
    fw, ld = r.get("first_word_s"), r.get("load_s")
    return None if fw is None or ld is None else (fw <= f["first_word_p95_s"] and ld <= f["load_s"])


def _evaluate(w, cand, variant, backend, facts, classes, live, rows, lk):
    """One (model, variant, backend) on this PC: a dict with status (meets | upgrade | not_measured |
    not_recommended), the floors, the cost here and the reasons."""
    mid = cand["id"]
    ref = rows.get((mid, variant, backend, lk["profile"]))
    mine = ((live or {}).get("measured") or {}).get((mid, variant, backend))
    e = {"model": mid, "variant": variant, "backend": backend, "name": cand.get("name") or mid,
         "floors": {}, "cost_here": {}, "reasons": [], "ram_need": 0, "gpu_need": 0, "score": 0, "row": None}
    f = FLOORS.get(w)
    if f is None:
        e.update(status="not_measured", reasons=["not measured against a floor yet"])
        return e
    if ref is None and mine is None:
        e.update(status="not_measured", reasons=["not measured on a PC like this one yet"])
        return e
    r = dict(ref or {}, **(mine or {}))
    e["row"], e["score"] = r, _score(w, r)
    installed = float(facts.get("ram_gb") or 0) * 1024
    ad = _adapter(facts) if backend != "cpu" else None
    gpu_usable = None
    need = int(r.get("need_mb") or max(r.get("ram_mb") or 0, r.get("ws_mb") or 0, r.get("shared_mb") or 0))
    vram = int(r.get("vram_mb") or 0)
    gpu_need, shared = 0, 0
    if backend != "cpu":
        # a discrete card's own memory is GPU capacity, unless its family has no usable backend on it
        fam_class = ((classes or {}).get("gpu") or {}).get(_FAMILY[w])
        own = ad is not None and not ad.get("integrated") and fam_class != "compatibility"
        pc_kind = "discrete" if own else "integrated"
        row_kind = r.get("gpu") or ("discrete" if vram else "integrated" if r.get("shared_mb") else None)
        if row_kind != pc_kind:
            e.update(status="not_measured", row=None, reasons=[
                f"measured on {_KIND.get(row_kind, 'unknown graphics')} only; this PC has {_KIND[pc_kind]}"])
            return e
        if own:
            gpu_need = vram
            v_free = (live or {}).get("gpu_free_mb")
            v_free = int(ad.get("dedicated_mb") or 0) if v_free is None else int(v_free)
            gpu_usable = max(0, v_free - gpu_reserve_mb(v_free, (live or {}).get("settings")))
        else:
            # built-in graphics: its memory is system RAM, already in need_mb (the biggest single figure); only
            # rows from built-in graphics apply here, so nothing is added a second time (spec 6.1)
            shared = int(r.get("shared_mb") or 0)
    e["ram_need"], e["gpu_need"] = need, gpu_need
    cap = installed - LIMITS["LOW_FREE_MB"]
    floor_mb = f["ram_share"] * installed
    if f["workers_cap"]:
        wcap = jobs.worker_memory_limit_mb(installed)
        cap, floor_mb = min(cap, wcap), min(floor_mb, wcap)
    e["cap"], e["floor_mb"] = int(max(0, cap)), int(floor_mb)

    cpu_row = r if backend == "cpu" else rows.get((mid, variant, "cpu", lk["profile"]))
    degr = (r.get("floor") or {}).get("degradation")
    dims = {"usefulness": _useful(w, r, f), "reliability": _reliable(w, r, f),
            "responsiveness": _quick(w, r, f) if (lk["similar"] or mine) else None,
            "memory": need <= floor_mb,
            "availability": None if cpu_row is None else _reliable(w, cpu_row, f),
            "degradation": {"pass": True, "fail": False}.get(degr)}
    e["floors"] = dims
    c = {"load_s": r.get("load_s"), "items_s": r.get("items_s"), "ram_mb": need,
         "measured_on": "this PC" if mine else "similar PC"}
    if w == "photo_talk":
        c["answer_s"] = r.get("first_word_s")
    else:
        c["query_ms"] = r.get("query_ms")
    if gpu_need:
        c["gpu_mb"] = gpu_need
    if shared:
        c["shared_mb"] = shared
    count = (live or {}).get("photos" if w == "photo_search" else "files")
    if count and r.get("items_s"):
        c["index_h"] = round(count / r["items_s"] / 3600, 1)
    e["cost_here"] = {k: v for k, v in c.items() if v is not None}
    e["shared"] = shared

    reasons = []
    if need > cap:
        reasons.append(f"needs about {_mb(need)} of memory; this PC can give it {_mb(max(0, cap))}")
    if gpu_usable is not None and gpu_need > gpu_usable:
        reasons.append(f"needs {_mb(gpu_need)} on the graphics card; {_mb(gpu_usable)} of it is usable after "
                       "the reserve")
    if reasons:
        e.update(status="not_recommended", reasons=reasons)
        return e
    if dims["reliability"] is False:
        stops = int(r.get("kills") or 0) + int(r.get("hang_kills") or 0)
        e.update(status="not_recommended", reasons=[f"it crashed or was stopped in the test "
                                                    f"({int(r.get('crashes') or 0)} crashes, {stops} stops)"])
        return e
    if dims["usefulness"] is False:
        why = (f"finds too little (nDCG@10 {r['visual_ndcg10']:.2f}, recall@10 {r['visual_recall10']:.2f}; the "
               f"floor is {f['ndcg10']:.2f} and {f['recall10']:.2f})" if w == "photo_search" else
               f"answered {r.get('checks_passed')} of {f['checks']} checks")
        e.update(status="not_recommended", reasons=[why])
        return e
    missing = [d for d in f["required"] if dims.get(d) is None]
    if missing:
        e.update(status="not_measured", reasons=["not measured on a PC like this one yet (" + ", ".join(missing)
                                                 + ")"])
        return e
    if dims["responsiveness"] is False:
        if w == "photo_search":
            if r["query_ms"] > f["query_p95_ms"]:
                reasons.append(f"a search takes {_n(r['query_ms'])} ms (the floor is {f['query_p95_ms']} ms)")
            if r["items_s"] < f["items_s"]:
                reasons.append(f"indexes {_n(r['items_s'])} photos a second (the floor is {f['items_s']})")
        else:
            if r["first_word_s"] > f["first_word_p95_s"]:
                reasons.append(f"first word about {_n(r['first_word_s'])} s (the floor is "
                               f"{f['first_word_p95_s']} s)")
            if r["load_s"] > f["load_s"]:
                reasons.append(f"loading takes {_n(r['load_s'])} s (the floor is {f['load_s']} s)")
    if dims["memory"] is False:
        reasons.append(f"more memory ({_mb(need)}; the floor is {_mb(floor_mb)})")
    if dims["availability"] is False:
        reasons.append("its processor-only path didn't pass the test")
    for d in f["required"]:
        if d not in ("responsiveness", "memory", "availability") and dims.get(d) is False:
            reasons.append(f"{d} not met")
    e.update(status="upgrade" if reasons else "meets", reasons=reasons)
    return e


def _groups(cand):
    """The model's variants in equivalence groups (vectors interchangeable), in catalog order."""
    seen, out = set(), []
    by = {v["id"]: v for v in cand.get("variants") or []}
    for v in cand.get("variants") or []:
        if v["id"] in seen:
            continue
        group, todo = [], [v["id"]]
        while todo:
            x = todo.pop()
            if x in seen or x not in by:
                continue
            seen.add(x)
            group.append(x)
            todo += by[x].get("equivalent_to") or []
        out.append(sorted(group, key=[u["id"] for u in cand["variants"]].index))
    return out


def _pick(evals, goal, live):
    """Among equivalent variants (spec 5.2 step 3): the best status first, then by goal. quiet and balanced: least
    RAM, then least graphics memory; fast: the highest items_s whose peak x 2 fits the usable budget now."""
    best = min(_RANK[e["status"]] for e in evals)
    pool = [e for e in evals if _RANK[e["status"]] == best]
    light = min(pool, key=lambda e: (e["ram_need"], e["gpu_need"]))
    if goal != "fast":
        return light
    free = (live or {}).get("free_ram_mb")
    budget = min(e.get("cap", 0) for e in pool) if free is None else max(0, int(free) - LIMITS["LOW_FREE_MB"])
    roomy = [e for e in pool if e["row"] is not None and 2 * e["ram_need"] <= budget]
    return max(roomy, key=lambda e: (e["row"].get("items_s") or 0, -e["ram_need"])) if roomy else light


def _here(e):
    return e["cost_here"].get("measured_on") == "this PC"


def _place(e):
    return "here" if _here(e) else "on a similar PC"


def _suggested_why(w, e):
    c, tail = e["cost_here"], "" if _here(e) else " (measured on a similar PC)"
    if w == "photo_talk":
        # only built-in graphics rows have shared memory: it is the PC's memory, never a card's (task D2 wording)
        mem = (f"{_mb(e['shared'])} of memory, shared with the built-in graphics" if e.get("shared") else
               f"{_mb(c['ram_mb'])} of memory")
        return f"Suggested: {e['name']}: first word about {round(c['answer_s'])} s, {mem}{tail}"
    return (f"Suggested: {e['name']}: a search takes about {round(c['query_ms'])} ms, it indexes "
            f"{_n(c['items_s'])} photos a second, {_mb(c['ram_mb'])} of memory{tail}")


def _finds_less(w, e, top):
    return (f"finds less than {top['name']} (nDCG@10 {e['score']:.2f} against {top['score']:.2f})"
            if w == "photo_search" else f"answers fewer checks than {top['name']}")


def _is_lighter(e, top):
    """A floor-meeting model that is weaker, or as useful and lighter, than the suggestion."""
    return e["score"] < top["score"] or (e["ram_need"], e["gpu_need"]) < (top["ram_need"], top["gpu_need"])


def _lighter_why(w, e, top):
    parts = [_finds_less(w, e, top)] if e["score"] < top["score"] else []
    if e["ram_need"] < top["ram_need"]:
        parts.append(f"uses less memory ({_mb(e['ram_need'])} {_place(e)})")
    return f"Lighter option: {e['name']}: " + " and ".join(parts)


def _heavier_why(w, e, top):
    """Why a stronger model that also meets the floor isn't the suggestion: it costs more."""
    a, b, parts = e["cost_here"], top["cost_here"], []
    if e["ram_need"] > top["ram_need"]:
        parts.append(f"more memory ({_mb(e['ram_need'])})")
    if e["gpu_need"] > top["gpu_need"]:
        parts.append(f"more graphics memory ({_mb(e['gpu_need'])})")
    place = _place(e)
    if w == "photo_talk":
        slow_load = (a.get("load_s") or 0) > (b.get("load_s") or 0)
        slow_ans = (a.get("answer_s") or 0) > (b.get("answer_s") or 0)
        n = f"{round(a.get('answer_s') or 0)} s {place}"
        if slow_load and slow_ans:
            parts.append(f"longer loading and answers ({n})")
        elif slow_ans:
            parts.append(f"longer answers ({n})")
        elif slow_load:
            parts.append(f"longer loading ({_n(a['load_s'])} s {place})")
    else:
        if (a.get("query_ms") or 0) > (b.get("query_ms") or 0):
            parts.append(f"slower searches ({round(a['query_ms'])} ms {place})")
        if (a.get("items_s") or 0) < (b.get("items_s") or 0):
            parts.append(f"slower indexing ({_n(a['items_s'])} photos a second {place})")
    return f"Upgrade: {e['name']}: " + (", ".join(parts) or
                                        f"as good as {top['name']} {place}, and {top['name']} is suggested")


def _now_note(e, live):
    free = (live or {}).get("free_ram_mb")
    if free is None or e["status"] == "not_recommended" or e["row"] is None:
        return None, ""
    usable = max(0, int(free) - LIMITS["LOW_FREE_MB"])
    if e["ram_need"] <= usable:
        return True, ""
    return False, f" Not now: {_mb(usable)} of memory is free after what Windows keeps."


def for_pc(facts, classes, live, goal="balanced", focus="multilingual", *, rows=None, catalog=None):
    """{workload: [{"model", "variant", "backend", "outcome", "why", "cost_here", "floors", "name", ...}]}
    (outcome: suggested | upgrade | lighter | not_recommended | not_measured, see the module docstring) for
    text, photo_search and photo_talk on this PC and the selected runtime (live["runtime"][workload], else
    llama.cpp's Vulkan when installed for talk, else the processor). facts: hardware.scan(); classes:
    profile.classify / effective; live: {"free_ram_mb", "gpu_free_mb", "runtime", "measured": {(model, variant,
    backend): row measured in the app}, "photos", "files"} (all optional; unknown never counts against a model).
    floors: {dimension: True | False | None (not measured)}. rows / catalog: models.MEASURED and the catalog by
    default (tests pass synthetic ones). photo_talk is offered here, never downloaded with the others."""
    facts, live = facts or {}, live or {}
    rows = models.MEASURED if rows is None else rows
    lk = like(facts, classes)
    out = {w: [] for w in WORKLOADS}
    for cand in (_catalog(focus) if catalog is None else catalog):
        w = cand["workload"]
        backend = _backend(w, facts, live)
        for group in _groups(cand):
            evals = [_evaluate(w, cand, v, backend, facts, classes, live, rows, lk) for v in group]
            out[w].append(_pick(evals, goal, live))
    res = {}
    for w, entries in out.items():
        meets = [e for e in entries if e["status"] == "meets"]
        top = max(meets, key=lambda e: (e["score"], -e["ram_need"], -e["gpu_need"])) if meets else None
        items = []
        for e in entries:
            if e is top:
                outcome, why = "suggested", _suggested_why(w, e)
            elif e["status"] == "meets" and _is_lighter(e, top):
                outcome, why = "lighter", _lighter_why(w, e, top)
            elif e["status"] == "meets":
                outcome, why = "upgrade", _heavier_why(w, e, top)
            elif e["status"] == "upgrade" and top is not None and e["score"] < top["score"]:
                # misses the floor and finds less than the suggestion: not an upgrade
                outcome = "not_recommended"
                why = f"Not recommended: {e['name']}: {_finds_less(w, e, top)}; " + "; ".join(e["reasons"])
            elif e["status"] == "upgrade":
                outcome = "upgrade"
                why = f"Upgrade: {e['name']}: " + "; ".join(e["reasons"])
                why += "" if _here(e) else " (measured on a similar PC)"
            elif e["status"] == "not_recommended":
                outcome, why = "not_recommended", f"Not recommended: {e['name']}: " + "; ".join(e["reasons"])
            else:
                outcome = "not_measured"
                why = f"Not measured: {e['name']}: " + "; ".join(e["reasons"])
            fits, note = _now_note(e, live)
            item = {"model": e["model"], "variant": e["variant"], "backend": e["backend"], "name": e["name"],
                    "outcome": outcome, "why": why + note, "cost_here": e["cost_here"], "floors": e["floors"],
                    "like": lk["profile"]}
            if fits is not None:
                item["fits_now"] = fits
            items.append(item)
        items.sort(key=lambda i: _ORDER[i["outcome"]])
        res[w] = items
    return res


def none_reason(workload, entries):
    """A plain sentence when no model is suggested for the workload, from the first measured reason; "" when one
    is suggested."""
    if any(e["outcome"] == "suggested" for e in entries):
        return ""
    label = _LABEL.get(workload, workload)
    for e in entries:
        if e["outcome"] in ("not_recommended", "upgrade"):
            return f"No model for {label} meets the floor on this PC: {e['why'].split(': ', 1)[-1]}"
    return f"No model for {label} is suggested: none was measured on a PC like this one yet"
