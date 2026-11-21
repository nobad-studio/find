"""Fit and test the hybrid photo ranker on a judged photo set (dev only, not shipped).

    python tools/fit_hybrid.py <set folder> [--models-dir DIR] [--folds 5] [--out model.json]

Needs, in <set>/results/: features-baseline.json (tools/eval_photo_search.py --features: SigLIP similarity per
query x photo and each photo's OCR text) and facts-smolvlm2.json (SmolVLM2 caption + objects per photo, and
its colour saturation). MiniLM (the text meaning model) comes from --models-dir/model.

Channels per query x photo (None = the photo doesn't have it: adds 0):
  look      SigLIP similarity              look_gap  SigLIP similarity minus the query's best photo
  caption   MiniLM(query, caption)         objects   MiniLM(query, object list)
  words     share of the query's words found in caption + objects
  ocr       MiniLM(query, OCR text)        ocr_words share of the query's words in the OCR text
  gray      1/0 black-and-white, only when the query asks for black and white

Cross-validation over QUERIES (k folds): calibration and weights are fitted on the other folds' queries only,
then every photo is ranked for each held-out query and scored (recall@10, nDCG@10, MRR@10) against SigLIP alone on
the same queries. --out fits on all queries and writes the model for nobadfind/hybrid.py.
"""
import argparse
import importlib.util
import json
import os
import random
import re
import sys

import numpy as np

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

from nobadfind import hybrid  # noqa: E402

_spec = importlib.util.spec_from_file_location("eval_photo_search", os.path.join(APP, "tools", "eval_photo_search.py"))
eps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eps)

CHANNELS = ("look", "look_gap", "caption", "objects", "words", "ocr_t", "ocr_words_t", "has_text_t", "gray",
            "look_t", "look_gap_t", "caption_t", "objects_t", "words_t")
SPLIT_TEXT = os.environ.get("HYBRID_SPLIT_TEXT", "1") == "1"
# Query-dependent channels (suffix _t): only when the query asks for writing. "gray" is a rule, not learned: one
# judged search asks for black and white, too few to fit; saturation is a direct, explainable measurement.
FIXED = {"gray": ({"a": 3.0, "b": 0.0}, 1.0)}
GRAY_MAX = 30          # mean HSV saturation (0-255) of black-and-white and sepia photos measured under ~26
TEXT = re.compile(r"\b(sign|signs|signboard|writing|written|text|menu|note|notes|page|screen|screenshot|label|"
                  r"poster|letter|document|handwritten|printed)\b", re.I)
STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "with", "and", "or", "is", "are", "someone", "something",
        "photo", "picture", "image", "some", "each", "other", "while", "by", "from", "for", "that", "this"}
BW = re.compile(r"\b(black and white|black-and-white|monochrome|b&w)\b", re.I)


def words(text):
    out = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def build_features(folder, models_dir, facts_file="facts-smolvlm2.json"):
    from nobadfind import embed, models
    queries, photos, qrels = eps.load_set(folder)
    res = os.path.join(folder, "results")
    base = json.load(open(os.path.join(res, "features-baseline.json"), encoding="utf-8"))
    facts = json.load(open(os.path.join(res, facts_file), encoding="utf-8"))
    facts.pop("_peak", None)
    sig = {(r["q"], r["photo"]): r["siglip"] for r in base["rows"]}
    ocr_text = {n: t for n, t in base["ocr_text"].items() if t and len(t.strip()) >= 3}
    names = sorted(photos)
    spec = models.get("minilm-l6-v2")
    d = os.path.join(models_dir, "model")
    q_enc = embed.Embedder(d, threads=4, gpu=False, spec=spec, query=True)
    p_enc = embed.Embedder(d, threads=4, gpu=False, spec=spec)
    cap = {n: (facts.get(n) or {}).get("caption") or "" for n in names}
    obj = {n: (facts.get(n) or {}).get("objects") or "" for n in names}
    qv = _unit(q_enc.encode([q["text"] for q in queries]))
    cv = _unit(p_enc.encode([cap[n] or "-" for n in names]))
    ov = _unit(p_enc.encode([obj[n] or "-" for n in names]))
    t_names = [n for n in names if n in ocr_text]
    tv = dict(zip(t_names, _unit(p_enc.encode([ocr_text[n][:2000] for n in t_names])))) if t_names else {}
    capw = {n: words(cap[n]) | words(obj[n]) for n in names}
    ocrw = {n: words(ocr_text[n]) for n in t_names}
    gray = {n: (facts.get(n) or {}).get("gray") for n in names}
    feats = {}
    for qi, q in enumerate(queries):
        qw = words(q["text"])
        best = max((sig.get((q["id"], n)) or -1) for n in names)
        asks_bw = bool(BW.search(q["text"]))
        asks_text = bool(TEXT.search(q["text"]))
        rows = {}
        for pi, n in enumerate(names):
            s = sig.get((q["id"], n))
            f = {"look": s, "look_gap": None if s is None else s - best,
                 "caption": float(cv[pi] @ qv[qi]) if cap[n] else None,
                 "objects": float(ov[pi] @ qv[qi]) if obj[n] else None,
                 "words": (len(qw & capw[n]) / len(qw)) if qw and (cap[n] or obj[n]) else None,
                 "ocr_t": (float(tv[n] @ qv[qi]) if n in tv else None) if asks_text else None,
                 "ocr_words_t": ((len(qw & ocrw[n]) / len(qw)) if qw and n in ocrw else None) if asks_text else None,
                 "has_text_t": (1.0 if n in tv else 0.0) if asks_text else None,
                 "gray": (1.0 if gray[n] < GRAY_MAX else -1.0) if asks_bw and gray[n] is not None else None}
            if asks_text and SPLIT_TEXT:
                # a query asking for writing gets its own weights for every channel (captions say less there)
                f = {(k if k.endswith("_t") or k == "gray" else k + "_t"): v for k, v in f.items()}
            rows[n] = f
        feats[q["id"]] = rows
    return queries, qrels, feats


def fit(train_q, qrels, feats, channels, l2=1e-2):
    xs = {ch: [] for ch in channels}
    ys = {ch: [] for ch in channels}
    for qid in train_q:
        for n, f in feats[qid].items():
            y = qrels.get(qid, {}).get(n, 0) / 2
            for ch in channels:
                if f.get(ch) is not None:
                    xs[ch].append(f[ch])
                    ys[ch].append(y)
    model = {"version": 1, "channels": {}, "weights": {}}
    for ch in channels:
        if ch in FIXED:
            continue
        if len(set(xs[ch])) > 1 and sum(ys[ch]) > 0:
            a, b = hybrid.fit_platt(xs[ch], ys[ch])
            model["channels"][ch] = {"a": a, "b": b}
    used = list(model["channels"])
    X, Y = [], []
    for qid in train_q:
        for n, f in feats[qid].items():
            X.append([hybrid.contribution(ch, f.get(ch), model) for ch in used])
            Y.append(qrels.get(qid, {}).get(n, 0) / 2)
    w = hybrid.fit_weights(np.array(X), np.array(Y), l2=l2)
    model["weights"] = {ch: float(x) for ch, x in zip(used, w)}
    for ch in channels:
        if ch in FIXED:
            model["channels"][ch], model["weights"][ch] = FIXED[ch]
    return model


def evaluate(qids, qrels, feats, model):
    out = []
    for qid in qids:
        ranked = hybrid.rank(feats[qid], model)
        out.append(eps.metrics(ranked, qrels.get(qid, {})))
    return out


def siglip_only(qids, qrels, feats):
    out = []
    for qid in qids:
        f = feats[qid]
        look = {n: f[n].get("look", f[n].get("look_t")) for n in f}
        ranked = sorted(f, key=lambda n: -(look[n] if look[n] is not None else -9))
        out.append(eps.metrics(ranked, qrels.get(qid, {})))
    return out


def _agg(ms):
    return eps.aggregate([dict(recall=r, ndcg=n, mrr=m) for r, n, m in ms])


def cross_validate(queries, qrels, feats, channels, folds=5, seed=13, l2=1e-2):
    qids = [q["id"] for q in queries]
    random.Random(seed).shuffle(qids)
    parts = [qids[i::folds] for i in range(folds)]
    got, ref, per_q = [], [], {}
    for i, test in enumerate(parts):
        train = [q for j, p in enumerate(parts) if j != i for q in p]
        model = fit(train, qrels, feats, channels, l2=l2)
        m = evaluate(test, qrels, feats, model)
        got += m
        ref += siglip_only(test, qrels, feats)
        per_q.update({qid: x for qid, x in zip(test, m)})
    return _agg(got), _agg(ref), per_q


GROUPS = {  # the kinds of search the maintainer asked to see (2026-11-21), by query channel or id
    "people and actions": lambda q: "R" in q["channels"] or "E" in q["channels"],
    "relationships": lambda q: "R" in q["channels"],
    "screenshots and documents": lambda q: q["id"] in ("q28", "q29", "q56"),
    "text-heavy": lambda q: "T" in q["channels"],
    "Hindi signs": lambda q: q["id"] == "q25",
    "black and white": lambda q: q["id"] == "q54",
    "ambiguous (mood)": lambda q: "E" in q["channels"],
    "objects": lambda q: "O" in q["channels"],
    "all": lambda q: True,
}


def _boot(d, seed=1, n=5000):
    rng = random.Random(seed)
    b = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n))
    return b[int(0.025 * n)], b[int(0.975 * n) - 1]


def report(folder, queries, qrels, feats, folds):
    """Cross-validated hybrid vs SigLIP alone vs ranking v2, per kind of search: nDCG@10, recall@10, searches
    better/worse, paired bootstrap CI over all searches."""
    v2 = json.load(open(os.path.join(folder, "results", "v2.json"), encoding="utf-8"))["variants"]
    v2 = v2.get("today") or v2["photo_v2"]          # "today" = the default ranking (v2 since 2026-11-22)
    _g, _r, per_q = cross_validate(queries, qrels, feats, CHANNELS, folds)
    ids = [q["id"] for q in queries]
    sig = dict(zip(ids, siglip_only(ids, qrels, feats)))
    print(f"{'kind of search':28}{'n':>3}  {'hybrid':>13}  {'SigLIP':>13}  {'v2':>6}  vs SigLIP +/-  vs v2 +/-")
    for name, pick in GROUPS.items():
        qs = [q["id"] for q in queries if pick(q)]
        h = _agg([per_q[i] for i in qs])
        s_ = _agg([sig[i] for i in qs])
        v = round(sum(v2["per_query"][i] for i in qs) / len(qs), 3)
        dn = [per_q[i][1] - sig[i][1] for i in qs]
        dv = [per_q[i][1] - v2["per_query"][i] for i in qs]
        print(f"{name:28}{len(qs):>3}  {h['ndcg10']!s:>6}/{h['recall10']!s:<6}  {s_['ndcg10']!s:>6}/{s_['recall10']!s:<6}"
              f"  {v!s:>6}  {sum(x > 0.005 for x in dn):>5}/{sum(x < -0.005 for x in dn):<5}"
              f"  {sum(x > 0.005 for x in dv):>4}/{sum(x < -0.005 for x in dv):<4}")
    d = [per_q[i][1] - sig[i][1] for i in ids]
    lo, hi = _boot(d)
    print(f"hybrid - SigLIP alone, nDCG@10: {sum(d) / len(d):+.3f} (95 % CI {lo:+.3f} to {hi:+.3f})")
    d = [per_q[i][1] - v2["per_query"][i] for i in ids]
    lo, hi = _boot(d)
    print(f"hybrid - v2,           nDCG@10: {sum(d) / len(d):+.3f} (95 % CI {lo:+.3f} to {hi:+.3f})")
    T = {q["id"]: q["text"] for q in queries}
    order = sorted(ids, key=lambda i: per_q[i][1] - sig[i][1])
    print("helps most:", [(T[i], round(per_q[i][1] - sig[i][1], 2)) for i in order[-5:]])
    print("hurts most:", [(T[i], round(per_q[i][1] - sig[i][1], 2)) for i in order[:5]])


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--models-dir", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "NOBAD", "Find"))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--out")
    ap.add_argument("--facts", default="facts-smolvlm2.json", help="caption file in <set>/results")
    ap.add_argument("--report", action="store_true", help="per kind of search vs SigLIP alone and v2 (results/v2.json)")
    a = ap.parse_args(argv)
    queries, qrels, feats = build_features(a.folder, a.models_dir, a.facts)
    if a.report:
        report(a.folder, queries, qrels, feats, a.folds)
        return
    print(f"{len(queries)} searches; cross-validated over {a.folds} folds of searches (nDCG@10 / recall@10)")
    sets = {"SigLIP alone (calibrated)": ("look",),
            "look + caption + objects": ("look", "look_gap", "caption", "objects", "words"),
            "+ black-and-white rule": ("look", "look_gap", "caption", "objects", "words", "gray"),
            "all channels": CHANNELS}
    for label, chans in sets.items():
        got, ref, _pq = cross_validate(queries, qrels, feats, chans, a.folds)
        print(f"  {label:28} {got['ndcg10']} / {got['recall10']}   (SigLIP alone {ref['ndcg10']} / {ref['recall10']})")
    for ch in CHANNELS:
        rest = tuple(c for c in CHANNELS if c != ch)
        got, _ref, _pq = cross_validate(queries, qrels, feats, rest, a.folds)
        print(f"  without {ch:10} {got['ndcg10']} / {got['recall10']}")
    _g, _r, per_q = cross_validate(queries, qrels, feats, CHANNELS, a.folds)
    by_ch = {}
    for q in queries:
        for ch in q["channels"]:
            by_ch.setdefault(ch, []).append(per_q[q["id"]])
    print("all channels by what the search needs (nDCG@10):",
          {ch: _agg(v)["ndcg10"] for ch, v in sorted(by_ch.items())})
    if a.out:
        model = fit([q["id"] for q in queries], qrels, feats, CHANNELS)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(model, f, indent=1)
        print("weights:", {k: round(v, 3) for k, v in model["weights"].items()})


if __name__ == "__main__":
    main()
