"""Photo search evaluation (dev only, not shipped): judged searches over a folder of real photos.

    python tools/eval_photo_search.py <set folder> [--models-dir DIR] [--json OUT] [--features OUT] [--no-ocr]

<set folder> holds queries.json ({"queries": [{"id", "text", "channels"}]}), qrels.json ({"photos": {name: desc},
"qrels": {query id: {name: 1 or 2}}}) and photos/. The photos are COPIED into a throwaway home folder (temp, never
the user's Find data) and indexed by the engine's own walk, text reading (Windows OCR unless --no-ocr) and photo
vectors (SigLIP, from --models-dir's photo-model/; MiniLM from model/ when present). Every query goes through the
real search.search(), and is scored on the photos only:

- recall@10: share of the clearly relevant photos (grade 2) in the top 10 (over min(#relevant, 10));
- nDCG@10 with gains 2^grade - 1 (grade 1 counts as partly relevant);
- MRR@10 on grade 2.

Reported overall and per channel the query mostly needs (V look, C caption, O objects, R actions, E mood, T text,
M photo type). --features writes, for every query x photo, the raw signals the hybrid ranker will learn from
(SigLIP similarity, OCR text match and meaning, Find's own rank), plus the grade.
"""
import argparse
import json
import math
import os
import shutil
import statistics
import sys
import tempfile
import time

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)

K = 10


def load_set(folder):
    q = json.load(open(os.path.join(folder, "queries.json"), encoding="utf-8"))["queries"]
    d = json.load(open(os.path.join(folder, "qrels.json"), encoding="utf-8"))
    return q, d["photos"], d["qrels"]


def metrics(ranked, grades, k=K):
    """ranked: photo names in rank order; grades: {name: 1 or 2}. -> (recall@k, nDCG@k, MRR@k)."""
    rel2 = {n for n, g in grades.items() if g == 2}
    top = ranked[:k]
    recall = len(rel2 & set(top)) / min(len(rel2), k) if rel2 else None
    dcg = sum((2 ** grades.get(n, 0) - 1) / math.log2(i + 2) for i, n in enumerate(top))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    ndcg = dcg / idcg if idcg else None
    mrr = next((1 / (i + 1) for i, n in enumerate(top) if n in rel2), 0.0) if rel2 else None
    return recall, ndcg, mrr


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 3) if xs else None


def aggregate(rows):
    return {"n": len(rows), "recall10": _mean(r["recall"] for r in rows), "ndcg10": _mean(r["ndcg"] for r in rows),
            "mrr10": _mean(r["mrr"] for r in rows)}


def build(root, home, data_dir, ocr=True):
    """The engine's own walk, text reading (with OCR) and vectors, like tools/eval_search.build_index."""
    from nobadfind import embed, extract, models, photo
    from nobadfind.store import Store
    from nobadfind.walker import Walker
    store = Store(os.path.join(root, "i.db"), encrypt=False)
    Walker([home], gen=1, on_batch=store.upsert_files).run()
    store.upgrade_name_index()
    for fid, p, ext, mtime in store.q("SELECT id, path, ext, mtime FROM files WHERE kind != 'folder'"):
        _fid, _mt, chunks, err = extract.work((fid, p, ext, mtime, 25 << 20, ocr))
        store.set_text(fid, mtime, chunks, err)
    ctx = {"store": store, "embedder": None, "vindex": None, "photo_text": None, "pindex": None, "ran": []}
    if models.ready("minilm-l6-v2", data_dir):
        import importlib.util
        spec_ = importlib.util.spec_from_file_location("eval_text", os.path.join(APP, "tools", "eval_text.py"))
        et = importlib.util.module_from_spec(spec_)
        spec_.loader.exec_module(et)
        spec = models.get("minilm-l6-v2")
        d = models.model_dir("minilm-l6-v2", data_dir)
        emb = embed.Embedder(d, threads=4, gpu=False, spec=spec)
        vindex = embed.VectorIndex(spec["dim"])
        vindex.model = "minilm-l6-v2"
        et.index_vectors(store, emb, vindex)
        ctx.update(embedder=embed.Embedder(d, threads=4, gpu=False, spec=spec, query=True), vindex=vindex)
        ctx["ran"].append("meaning")
    pdir = os.path.join(data_dir, "photo-model")
    if photo.model_ready(pdir):
        pindex = embed.VectorIndex(photo.PHOTO_DIM, ("SELECT file_id, v FROM pvecs WHERE length(v) > 0",))
        for fid, p, mtime in store.q("SELECT id, path, mtime FROM files WHERE kind = 'image'"):
            _f, _m, blob, err = photo.embed_photo((fid, p, mtime, pdir))
            store.set_photo_vector(fid, mtime, blob, err)
        pindex.reset(photo.PHOTO_DIM, "siglip-base")
        pindex.load(store)
        ctx.update(photo_text=photo.TextEncoder(pdir, threads=4), pindex=pindex)
        ctx["ran"].append("photo")
    return ctx


def run(folder, models_dir, ocr=True, features_out=None, variant_sets=None):
    from nobadfind import search
    queries, photos, qrels = load_set(folder)
    root = tempfile.mkdtemp(prefix="nobadfind-evalphoto-")
    data_dir, home = os.path.join(root, "data"), os.path.join(root, "home")
    pics = os.path.join(home, "Pictures")
    os.makedirs(data_dir)
    os.makedirs(pics)
    store = None
    try:
        for sub in ("model", "photo-model"):
            src = os.path.join(models_dir, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(data_dir, sub))
        # neutral camera-style names: the set's names ("dog-01.jpg") would hand the name channel the answer
        alias = {}
        for i, name in enumerate(sorted(photos)):
            alias[f"IMG_{i + 1:04}.jpg"] = name
            shutil.copy2(os.path.join(folder, "photos", name), os.path.join(pics, f"IMG_{i + 1:04}.jpg"))
        t0 = time.perf_counter()
        ctx = build(root, home, data_dir, ocr=ocr)
        build_s = time.perf_counter() - t0
        store = ctx["store"]
        name_of = {fid: alias.get(os.path.basename(p), "") for fid, p in store.q("SELECT id, path FROM files WHERE kind = 'image'")}
        ocr_text = {}
        for fid, txt in store.q("SELECT c.file_id, group_concat(c.body, ' ') FROM chunks c GROUP BY c.file_id"):
            if fid in name_of:
                ocr_text[name_of[fid]] = txt or ""
        rows, lat, feats = [], [], []
        for item in queries:
            t = time.perf_counter()
            r = search.search(store, item["text"], embedder=ctx["embedder"], vindex=ctx["vindex"], limit=60,
                              roots=[home], photo_text=ctx["photo_text"], pindex=ctx["pindex"])
            lat.append((time.perf_counter() - t) * 1000)
            ranked = [alias.get(os.path.basename(x["path"]), "") for x in r["results"]]
            ranked = [n for n in ranked if n in photos]
            grades = qrels.get(item["id"], {})
            rec, ndcg, mrr = metrics(ranked, grades)
            sig_rank, sig = [], {}
            if ctx["pindex"] is not None:
                ask = getattr(ctx["photo_text"], "encode_question", None) or ctx["photo_text"].encode
                hits = ctx["pindex"].search(ask(item["text"]), k=ctx["pindex"].n)
                sig = {name_of[f]: float(s) for f, s in hits if f in name_of}
                sig_rank = sorted(sig, key=sig.get, reverse=True)
            srec, sndcg, smrr = metrics(sig_rank, grades)
            rows.append(dict(id=item["id"], q=item["text"], channels=item["channels"], recall=rec, ndcg=ndcg,
                             mrr=mrr, siglip_recall=srec, siglip_ndcg=sndcg, siglip_mrr=smrr, top=ranked[:5],
                             found=len(ranked)))
            if features_out:
                pos = {n: i for i, n in enumerate(ranked)}
                words = {w for w in item["text"].lower().split() if len(w) > 2}
                for n in photos:
                    txt = ocr_text.get(n, "").lower()
                    feats.append({"q": item["id"], "photo": n, "grade": grades.get(n, 0), "siglip": sig.get(n),
                                  "find_rank": pos.get(n), "ocr_chars": len(txt),
                                  "ocr_word_hits": sum(1 for w in words if w in txt)})
        rep = {"models": ctx["ran"], "ocr": ocr, "photos": len(photos), "queries": len(queries),
               "build_s": round(build_s, 1), "rows": rows,
               "lat_p50_ms": round(statistics.median(lat), 1), "lat_max_ms": round(max(lat), 1),
               "ocr_photos": sum(1 for v in ocr_text.values() if v.strip())}
        rep["find"] = aggregate(rows)
        rep["siglip_only"] = aggregate([dict(recall=r["siglip_recall"], ndcg=r["siglip_ndcg"], mrr=r["siglip_mrr"])
                                        for r in rows])
        rep["by_channel"] = {}
        for ch in "VCORETM":
            sub = [r for r in rows if ch in r["channels"]]
            if sub:
                rep["by_channel"][ch] = {"find": aggregate(sub), "siglip_only": aggregate(
                    [dict(recall=r["siglip_recall"], ndcg=r["siglip_ndcg"], mrr=r["siglip_mrr"]) for r in sub])}
        # ranking variants (search.VARIANTS), each measured on the same index; today's ranking is "" (none on)
        rep["variants"] = {}
        sig_by_q = {r["id"]: (r["siglip_recall"], r["siglip_ndcg"]) for r in rows}
        for vs in variant_sets or ():
            old = set(search.VARIANTS)
            search.VARIANTS.clear()
            search.VARIANTS.update(vs)
            try:
                vrows = []
                for item in queries:
                    r = search.search(store, item["text"], embedder=ctx["embedder"], vindex=ctx["vindex"], limit=60,
                                      roots=[home], photo_text=ctx["photo_text"], pindex=ctx["pindex"])
                    ranked = [n for n in (alias.get(os.path.basename(x["path"]), "") for x in r["results"])
                              if n in photos]
                    rec, ndcg, mrr = metrics(ranked, qrels.get(item["id"], {}))
                    why = {alias.get(os.path.basename(x["path"]), ""): x["why"] for x in r["results"]}
                    vrows.append(dict(id=item["id"], recall=rec, ndcg=ndcg, mrr=mrr, found=len(ranked),
                                      top=[(n, why.get(n)) for n in ranked[:10]]))
            finally:
                search.VARIANTS.clear()
                search.VARIANTS.update(old)
            a = aggregate(vrows)
            d = [r["ndcg"] - sig_by_q[r["id"]][1] for r in vrows if r["ndcg"] is not None]
            a.update(vs_siglip_better=sum(x > 0.005 for x in d), vs_siglip_worse=sum(x < -0.005 for x in d),
                     empty=sum(1 for r in vrows if not r["found"]), per_query={r["id"]: r["ndcg"] for r in vrows},
                     tops={r["id"]: r["top"] for r in vrows})
            rep["variants"]["+".join(sorted(vs)) or "today"] = a
        if features_out:
            with open(features_out, "w", encoding="utf-8") as f:
                json.dump({"rows": feats, "ocr_text": ocr_text}, f, ensure_ascii=False)
        return rep
    finally:
        if store is not None:
            store.close()
        shutil.rmtree(root, ignore_errors=True)


def _print(rep):
    print(f"{rep['photos']} photos, {rep['queries']} searches, models {rep['models']}, OCR {rep['ocr']} "
          f"({rep['ocr_photos']} photos with text), index built in {rep['build_s']} s, "
          f"search p50 {rep['lat_p50_ms']} ms")
    print(f"{'':12}{'recall@10':>10}{'nDCG@10':>10}{'MRR@10':>10}")
    for label, a in (("Find today", rep["find"]), ("SigLIP only", rep["siglip_only"])):
        print(f"{label:12}{a['recall10']!s:>10}{a['ndcg10']!s:>10}{a['mrr10']!s:>10}")
    print("by channel (Find today / SigLIP only, nDCG@10):")
    for ch, v in rep["by_channel"].items():
        print(f"  {ch}  n={v['find']['n']:<3} {v['find']['ndcg10']!s:>6} / {v['siglip_only']['ndcg10']!s:<6}")
    if rep.get("variants"):
        print("ranking variants (nDCG@10 / recall@10; searches better/worse than SigLIP alone; empty results):")
        for k, v in rep["variants"].items():
            print(f"  {k:40} {v['ndcg10']!s:>6} / {v['recall10']!s:<6} {v['vs_siglip_better']:>3}/{v['vs_siglip_worse']:<3}"
                  f" empty {v['empty']}")
    worst = sorted((r for r in rep["rows"] if r["ndcg"] is not None), key=lambda r: r["ndcg"])[:8]
    print("weakest searches (nDCG@10):")
    for r in worst:
        print(f"  {r['id']} {r['ndcg']:.2f}  {r['q']}  -> {r['top'][:3]}")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--models-dir", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "NOBAD", "Find"))
    ap.add_argument("--json")
    ap.add_argument("--features")
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--variants", help='ranking variant sets to measure, e.g. ";photo_nofloor;noweak,noguess" ("" = today)')
    a = ap.parse_args(argv)
    sets = [[v for v in part.split(",") if v] for part in a.variants.split(";")] if a.variants else None
    rep = run(a.folder, a.models_dir, ocr=not a.no_ocr, features_out=a.features, variant_sets=sets)
    _print(rep)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
