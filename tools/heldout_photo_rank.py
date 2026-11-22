"""Held-out evaluation of photo ranking candidates (dev only, not shipped). Rules fixed 2026-11-22 BEFORE grading:

    python tools/heldout_photo_rank.py <set folder> [--models-dir DIR]

Needs <set>/split.json (made once, before grading), qrels.json, results/features-baseline.json
(tools/eval_photo_search.py --features), results/v2.json (per-search nDCG of Find's own ranking, default v2), and
caption files results/facts-smolvlm2.json and results/facts-qwen.json.

Candidates (SigLIP is always the primary signal; captions are supplementary evidence):
  H0  SigLIP alone (+ the black-and-white saturation rule, which needs no model)
  H1  H0 + SmolVLM2 caption / objects / words + OCR channels, one weight set
  H2  H0 + Qwen captions, same channels, one weight set
  H3  H2 with query-dependent weights, decided from the QUERY'S OWN WORDS (what Find has at search time):
      - asks for writing or a screenshot -> PROTECTED: no caption channels at all (SigLIP + OCR + rules)
      - about people or actions           -> its own learned weights for every channel
      - anything else                     -> the general weights
Selection: 5-fold cross-validation over the TRAINING searches only picks one candidate by nDCG@10. Then the
held-out searches are scored once for SigLIP alone, ranking v2 and every candidate (the chosen one is marked).
Pass (all must hold, chosen candidate vs SigLIP alone on held-out, negatives excluded from nDCG):
  - paired bootstrap 95 % CI of the nDCG@10 difference entirely above 0;
  - no category with a mean drop > 0.03 whose CI is entirely below 0;
  - negatives: the chosen candidate is not more confident on them than SigLIP alone (mean calibrated top-3
    probability).
"""
import argparse
import importlib.util
import json
import math
import os
import random
import re
import sys

os.environ["HYBRID_SPLIT_TEXT"] = "0"          # this tool does the query-dependent split itself
APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)
_spec = importlib.util.spec_from_file_location("fit_hybrid", os.path.join(APP, "tools", "fit_hybrid.py"))
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

from nobadfind import hybrid  # noqa: E402

CAPTION = ("caption", "objects", "words")
BASE = ("look", "look_gap", "gray")
OCR = ("ocr_t", "ocr_words_t", "has_text_t")
SCREEN = re.compile(r"\bscreen ?shots?\b", re.I)
MORE_TEXT = re.compile(r"\b(price|prices|title|plate|banner|newspaper|whiteboard|ausgang|eingang|caption|"
                       r"label|logo|receipt|ticket)\b", re.I)
PEOPLE = re.compile(r"\b(person|people|man|men|woman|women|child|children|kid|kids|boy|girl|someone|couple|"
                    r"crowd|doctor|chef|musicians?|workers?|family|baby|passengers?|tourist)\b", re.I)
ACTION = re.compile(r"\b\w{3,}ing\b", re.I)
NOT_ACTION = {"building", "buildings", "something", "nothing", "anything", "everything", "morning", "evening",
              "ceiling", "painting", "paintings", "clothing", "wedding", "ring", "king", "spring", "string", "thing",
              "things", "darkness", "railing", "parking", "living", "dining", "ping", "evening"}


def intent(text):
    """What the query asks for, from its own words (all Find has at search time)."""
    if F.TEXT.search(text) or SCREEN.search(text) or MORE_TEXT.search(text):
        return "text"
    if PEOPLE.search(text) or any(m.group(0).lower() not in NOT_ACTION for m in ACTION.finditer(text)):
        return "people"
    return "other"


def shape(feats, queries, cand):
    """Channels per candidate. Returns (feats, channels)."""
    out, chans = {}, set()
    for q in queries:
        it = intent(q["text"])
        rows = {}
        for n, f in feats[q["id"]].items():
            keep = dict((k, f.get(k)) for k in BASE + OCR)
            if cand in ("H1", "H2", "H3") and not (cand == "H3" and it == "text"):
                keep.update((k, f.get(k)) for k in CAPTION)
            if cand == "H3" and it == "people":
                keep = {(k if k == "gray" or k.endswith("_t") else k + "_p"): v for k, v in keep.items()}
            rows[n] = keep
            chans.update(keep)
        out[q["id"]] = rows
    return out, tuple(sorted(chans))


def cv_train(train, qrels, feats, chans, folds=5, seed=13):
    ids = list(train)
    random.Random(seed).shuffle(ids)
    parts = [ids[i::folds] for i in range(folds)]
    got = []
    for i, test in enumerate(parts):
        model = F.fit([q for j, p in enumerate(parts) if j != i for q in p], qrels, feats, chans)
        got += F.evaluate(test, qrels, feats, model)
    return F._agg(got)


def top_prob(qid, feats, model, prior, k=3):
    scores = sorted((hybrid.score(f, model) for f in feats[qid].values()), reverse=True)[:k]
    lp = math.log(prior / (1 - prior))
    return sum(1 / (1 + math.exp(-(s + lp))) for s in scores) / len(scores)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--models-dir", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "NOBAD", "Find"))
    a = ap.parse_args(argv)
    split = json.load(open(os.path.join(a.folder, "split.json"), encoding="utf-8"))
    v2 = json.load(open(os.path.join(a.folder, "results", "v2.json"), encoding="utf-8"))["variants"]["today"]["per_query"]
    built = {}
    for model_name, facts in (("smol", "facts-smolvlm2.json"), ("qwen", "facts-qwen.json")):
        built[model_name] = F.build_features(a.folder, a.models_dir, facts)
    queries, qrels, _f = built["qwen"]
    cat = {q["id"]: q.get("category", "original") for q in queries}
    neg = [q for q in split["heldout"] if cat[q] == "negative"]
    held = [q for q in split["heldout"] if cat[q] != "negative" and qrels.get(q)]
    train = [q for q in split["train"] if cat[q] != "negative" and qrels.get(q)]
    cands = {"H0": "qwen", "H1": "smol", "H2": "qwen", "H3": "qwen"}
    shaped = {c: shape(built[src][2], queries, c) for c, src in cands.items()}
    print(f"{len(train)} training searches, {len(held)} held-out, {len(neg)} held-out negatives")
    print("selection on TRAINING searches only (5-fold CV, nDCG@10 / recall@10):")
    cvs = {}
    for c, (feats, chans) in shaped.items():
        cvs[c] = cv_train(train, qrels, feats, chans)
        print(f"  {c}  {cvs[c]['ndcg10']} / {cvs[c]['recall10']}")
    chosen = max(cvs, key=lambda c: cvs[c]["ndcg10"])
    print(f"chosen by training CV: {chosen}")
    print("\nHELD-OUT (fitted on all training searches, scored once):")
    per = {}
    models = {}
    for c, (feats, chans) in shaped.items():
        models[c] = F.fit(train, qrels, feats, chans)
        per[c] = dict(zip(held, F.evaluate(held, qrels, feats, models[c])))
    sig = dict(zip(held, F.siglip_only(held, qrels, shaped["H0"][0])))
    rows = {"SigLIP alone": sig, **per}
    print(f"  {'':14}{'nDCG@10':>9}{'recall@10':>11}")
    for k, v in rows.items():
        g = F._agg(list(v.values()))
        mark = "  <- chosen" if k == chosen else ""
        print(f"  {k:14}{g['ndcg10']!s:>9}{g['recall10']!s:>11}{mark}")
    print(f"  {'v2 (Find)':14}{round(sum(v2[q] or 0 for q in held) / len(held), 3)!s:>9}")
    d = [per[chosen][q][1] - sig[q][1] for q in held]
    lo, hi = F._boot(d)
    ok_main = lo > 0
    print(f"\n{chosen} - SigLIP alone, held-out nDCG@10: {sum(d) / len(d):+.3f} (95 % CI {lo:+.3f} to {hi:+.3f}); "
          f"better {sum(x > 0.005 for x in d)}, worse {sum(x < -0.005 for x in d)}")
    print("by category (held-out, chosen vs SigLIP alone, mean nDCG@10 difference and CI):")
    ok_cat = True
    for c in sorted({cat[q] for q in held}):
        qs = [q for q in held if cat[q] == c]
        dd = [per[chosen][q][1] - sig[q][1] for q in qs]
        clo, chi = F._boot(dd) if len(dd) > 1 else (dd[0], dd[0])
        bad = (sum(dd) / len(dd) < -0.03) and chi < 0
        ok_cat &= not bad
        print(f"  {c:16} n={len(qs):<2} {sum(dd) / len(dd):+.3f}  [{clo:+.3f}, {chi:+.3f}]{'  REGRESSION' if bad else ''}")
    prior = sum(1 for q in train for g in qrels.get(q, {}).values() if g) / (len(train) * len(next(iter(shaped['H0'][0].values()))))
    pn = {c: sum(top_prob(q, shaped[c][0], models[c], prior) for q in neg) / max(1, len(neg)) for c in shaped}
    pp = {c: sum(top_prob(q, shaped[c][0], models[c], prior) for q in held) / len(held) for c in shaped}
    print("confidence (mean calibrated probability of the top 3): negatives vs real searches")
    for c in shaped:
        print(f"  {c}  negatives {pn[c]:.3f}   real searches {pp[c]:.3f}")
    ok_neg = pn[chosen] <= pn["H0"] + 1e-9 or chosen == "H0"
    print(f"\nPASS: {ok_main and ok_cat and ok_neg}  (CI above 0: {ok_main}; no category regression: {ok_cat}; "
          f"negatives not more confident: {ok_neg})")


if __name__ == "__main__":
    main()
