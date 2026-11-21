import math

import numpy as np

from nobadfind import hybrid


def _model():
    return {"version": 1, "channels": {"look": {"a": 4.0, "b": -1.0}, "ocr": {"a": 2.0, "b": -0.5}},
            "weights": {"look": 1.0, "ocr": 0.5}}


def test_missing_channel_is_neutral_not_negative():
    m = _model()
    with_none = hybrid.score({"look": 0.5, "ocr": None}, m)
    without = hybrid.score({"look": 0.5}, m)
    assert with_none == without == 1.0 * (4.0 * 0.5 - 1.0)


def test_channels_add_their_calibrated_log_odds():
    s = hybrid.score({"look": 0.5, "ocr": 1.0}, _model())
    assert math.isclose(s, 1.0 * 1.0 + 0.5 * 1.5)


def test_unknown_channel_is_ignored():
    assert hybrid.score({"look": 0.25, "nope": 9.0}, _model()) == 0.0


def test_platt_fit_orders_scores_and_centres_on_the_base_rate():
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(0.2, 0.05, 400), rng.normal(0.5, 0.05, 40)])
    y = np.concatenate([np.zeros(400), np.ones(40)])
    a, b = hybrid.fit_platt(x, y)
    assert a > 0
    # contributions are log-odds relative to the base rate: added back to it, they predict the base rate on average
    prior = 40 / 440
    p = 1 / (1 + np.exp(-(a * x + b + math.log(prior / (1 - prior)))))
    assert abs(float(p.mean()) - prior) < 0.02
    assert a * 0.5 + b > 1.0 and a * 0.2 + b < -1.0


def test_fit_weights_finds_the_informative_channel():
    rng = np.random.default_rng(1)
    n = 2000
    good = rng.normal(0, 1, n)
    noise = rng.normal(0, 1, n)
    y = (good + rng.normal(0, 0.3, n) > 1.0).astype(float)
    w = hybrid.fit_weights(np.stack([good, noise], 1), y, l2=1e-3)
    assert w[0] > 5 * abs(w[1])


def test_rank_orders_by_score_and_keeps_ties_stable():
    m = _model()
    feats = {"p1": {"look": 0.1}, "p2": {"look": 0.6}, "p3": {"look": 0.6}, "p4": {}}
    assert hybrid.rank(feats, m) == ["p2", "p3", "p4", "p1"]
