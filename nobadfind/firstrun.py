"""First-run setup (plan 2026-11-22 Task 6): after the first scan, one window offers the models suggested for this
PC (modelsuggest.for_pc), with what each costs here, why, and how long indexing what the scan counted would take.
Download in that window is the consent (setup_accept, consent "DOWNLOAD"); only ticked models are fetched, through
the usual model_download (embed._fetch_verified).

What is listed (the shaping here is pure but for the file checks of what is on disk):
- group "suggested": each workload's suggested model; ticked, except photo_talk (offered, never fetched unless
  ticked). Text has no measured floor yet, so the model the tier picks for this PC's memory and cores is listed
  with outcome "not_measured", unticked, and says so; photo the same when nothing was measured for a PC like this.
- group "more" ("More for this PC"): upgrades and lighter options, with their measured cost; never ticked.
- not_recommended (and other unmeasured models) are not listed: they are on the Models page.
"""
from . import models, modelsuggest

STATES = ("pending", "later", "accepted", "done")
# the kinds whose text is read for meaning search (kinds.KINDS), counted for its estimate
TEXT_KINDS = ("pdf", "document", "spreadsheet", "slides", "text", "code", "email", "ebook")
FEATURE = {"text": "text", "photo_search": "photo", "photo_talk": "talk"}
_ORDER = {"text": 0, "photo_search": 1, "photo_talk": 2}
_HOSTS = {"talk": "huggingface.co", "runtime": "github.com"}


def duration(seconds):
    """"under a minute", "about 10 min", "about 2 h 15 min", "about 3 days"."""
    s = max(0.0, float(seconds))
    if s < 60:
        return "under a minute"
    m = int(round(s / 60))
    if m < 60:
        return f"about {m} min"
    if m < 48 * 60:
        h, mm = divmod(m, 60)
        return f"about {h} h" + (f" {mm} min" if mm else "")
    return f"about {int(round(m / 1440))} days"


def _n(x, word):
    return f"{x:,} {word}{'' if x == 1 else 's'}"


def _place(cost):
    on = cost.get("measured_on")
    return "" if on == "this PC" else f" (on the {on})" if on == "reference PC" else " (on a similar PC)"


def est_index(workload, cost, counts):
    """How long the first pass over what the first scan counted would take, from the measured items a second:
    photos for photo search (one item each), documents for meaning search (each is one piece of text or more, so
    it is the least it takes). "" for talk, before the scan, or with no speed measured."""
    rate = (cost or {}).get("items_s")
    if workload == "photo_talk" or not rate or counts is None:
        return ""
    if workload == "photo_search":
        n = int(counts.get("photos") or 0)
        if not n:
            return "the first scan found no photos"
        return f"{duration(n / rate)} for {_n(n, 'photo')}{_place(cost)}"
    n = int(counts.get("documents") or 0)
    if not n:
        return "the first scan found no documents"
    t = duration(n / rate)
    t = t if t == "under a minute" else f"{t} or more"
    return f"{t} for {_n(n, 'document')}{_place(cost)}"


def _tier_cost(mid):
    """A text model's figures from its measured row (docs/measurements.md, the reference PC)."""
    try:
        cpu = models.variants(mid)[0]["backends"]["cpu"]
    except (KeyError, IndexError):
        return {}
    return {k: v for k, v in {"ram_mb": cpu.get("ram_mb"), "items_s": cpu.get("items_s"),
                              "measured_on": "reference PC"}.items() if v}


def _tier_why(workload, name, pc):
    what = "text models have no measured floor yet" if workload == "text" else \
        "no photo model was measured on a PC like this one yet"
    return (f"For this PC's {float(pc.get('ram_gb') or 0):g} GB of memory and {int(pc.get('cores') or 0)} cores: "
            f"{name}. Not a measured suggestion: {what}.")


def _host(m):
    if m["feature"] == "runtime":
        return "github.com"
    parts = (m.get("source") or "").split("/")
    return parts[2] if len(parts) > 2 and parts[0] == "https:" else "huggingface.co"


def items(sugg, choice, pc, counts, data_dir, talk_runtime, states=None):
    """The listed items (module docstring). sugg: for_pc's result; choice: models.recommend_choice; counts:
    {"photos", "documents"} from the first scan, or None before it; talk_runtime: the runtime id talk uses here;
    states: {model id: (state, error)} of downloads this run."""
    states = states or {}
    out = []
    for w in ("text", "photo_search", "photo_talk"):
        entries = (sugg or {}).get(w) or []
        listed = [dict(e, group="suggested") for e in entries if e["outcome"] == "suggested"]
        tier = (choice or {}).get(FEATURE[w]) or ""
        measured = any(e["outcome"] != "not_measured" for e in entries)
        if not listed and w != "photo_talk" and tier and (w == "text" or not measured):
            # the tier's pick (what auto_configure uses) when nothing was measured to suggest
            m = models.get(tier)
            name = m["name"] if m else tier
            listed.append({"model": tier, "name": name, "outcome": "not_measured", "group": "suggested",
                           "cost_here": _tier_cost(tier) if w == "text" else {}, "why": _tier_why(w, name, pc)})
        listed += [dict(e, group="more") for e in entries if e["outcome"] in ("upgrade", "lighter")]
        for e in listed:
            m = models.get(e["model"])
            if m is None:
                continue
            missing = models.missing_mb(m["id"], data_dir)
            rt = None
            if w == "photo_talk":
                r = models.get(talk_runtime)
                rt = {"id": r["id"], "name": r["name"], "size_mb": models.missing_mb(r["id"], data_dir),
                      "source": "github.com"}
            st, err = states.get(m["id"], ("", ""))
            if rt is not None:
                rst, rerr = states.get(rt["id"], ("", ""))
                if rerr and not err:
                    st, err = rst, rerr
                elif rst == "downloading":
                    st = rst
            on_disk = models.ready(m["id"], data_dir) and (rt is None or rt["size_mb"] == 0)
            state = st or ("ready" if on_disk else "not_downloaded")
            cost = {k: v for k, v in (e.get("cost_here") or {}).items()}
            out.append({"workload": w, "model": m["id"], "name": e.get("name") or m["name"],
                        "outcome": e["outcome"], "group": e["group"],
                        "size_mb": int(missing + (rt["size_mb"] if rt else 0)), "cost_here": cost,
                        "why": e["why"], "est_index": est_index(w, cost, counts),
                        "checked": e["outcome"] == "suggested" and w != "photo_talk",
                        "on_disk": bool(on_disk), "state": state, "error": err or "",
                        "licence": m.get("licence") or "", "source": _host(m), "runtime": rt})
    out.sort(key=lambda i: (i["group"] != "suggested", _ORDER[i["workload"]]))
    return out


def total_mb(items):
    """MB to download for the ticked items: each model once, and a runtime two talk models share once."""
    seen, total = set(), 0
    for i in items:
        if not i["checked"]:
            continue
        rt = i["runtime"]
        total += i["size_mb"] - (rt["size_mb"] if rt else 0)
        if rt and rt["id"] not in seen:
            seen.add(rt["id"])
            total += rt["size_mb"]
    return int(total)


def notes(sugg):
    """Plain reasons for a workload with no suggestion (photo search, talk): from modelsuggest.none_reason."""
    out = []
    for w in ("photo_search", "photo_talk"):
        entries = (sugg or {}).get(w) or []
        why = modelsuggest.none_reason(w, entries)
        if why and any(e["outcome"] != "not_measured" for e in entries):
            out.append(why)
    return out
