"""Hybrid photo ranking: calibrated channel scores added as log-odds, with learned weights.

Each channel (photo look, caption meaning, objects, words, text in the photo, ...) gives a raw score on its own
scale; a SigLIP 0.3 and a MiniLM 0.8 don't mean the same thing. On judged searches each channel's raw score is
mapped to the log-odds that the photo is relevant, RELATIVE to the base rate (Platt scaling: a*raw + b). A photo's
score is the weighted sum of its channels' log-odds. A channel the photo doesn't have (no text in it, not
understood yet) adds 0: no evidence either way, so it never pushes the photo down.

The model is plain data ({"channels": {name: {"a", "b"}}, "weights": {name: w}}), fitted by tools/fit_hybrid.py
and stored with its measured gain in docs/measurements.md. numpy only.
"""
import math

import numpy as np


def contribution(channel, raw, model):
    """Calibrated log-odds (relative to the base rate) of one channel's raw score; 0 when missing or unknown."""
    cal = model["channels"].get(channel)
    if raw is None or cal is None:
        return 0.0
    return cal["a"] * float(raw) + cal["b"]


def score(feats, model):
    """feats: {channel: raw score or None}."""
    w = model["weights"]
    return sum(w.get(ch, 0.0) * contribution(ch, raw, model) for ch, raw in feats.items())


def rank(feats_by_item, model):
    """Item ids by descending score; ties keep the input order."""
    scored = [(score(f, model), i, k) for i, (k, f) in enumerate(feats_by_item.items())]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [k for _s, _i, k in scored]


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def _logistic(X, y, l2, offset=0.0, iters=500):
    """L2-regularized logistic regression (Newton steps). X: (n, d) with a ones column if a bias is wanted."""
    n, d = X.shape
    w = np.zeros(d)

    def loss(v):
        z = X @ v + offset
        return float(np.mean(np.logaddexp(0.0, z) - y * z)) + 0.5 * l2 * float(v @ v)
    cur = loss(w)
    for _ in range(iters):
        p = _sigmoid(X @ w + offset)
        g = X.T @ (p - y) / n + l2 * w
        h = (X * (p * (1 - p))[:, None]).T @ X / n + l2 * np.eye(d)
        step = np.linalg.solve(h, g)
        # backtracking: a full Newton step can overshoot on a sparse channel (review 2026-11-22: it swung between
        # a=81 and a=-391 forever); halve it until the loss goes down
        t = 1.0
        while t > 1e-8:
            cand = w - t * step
            new = loss(cand)
            if new <= cur:
                break
            t *= 0.5
        else:
            break
        w, done = cand, abs(cur - new) < 1e-12 or np.max(np.abs(t * step)) < 1e-8
        cur = new
        if done:
            break
    return w


def fit_platt(x, y, l2=1e-4):
    """(a, b) so that a*x + b is the log-odds of relevance minus the base rate's log-odds."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    prior = min(max(float(y.mean()), 1e-6), 1 - 1e-6)
    a, b = _logistic(np.stack([x, np.ones_like(x)], 1), y, l2, offset=math.log(prior / (1 - prior)))
    return float(a), float(b)


def fit_weights(X, y, l2=1e-2):
    """Channel weights over calibrated contributions X (n, channels); no bias (the base rate is already in them)."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    prior = min(max(float(y.mean()), 1e-6), 1 - 1e-6)
    return _logistic(X, y, l2, offset=math.log(prior / (1 - prior)))
