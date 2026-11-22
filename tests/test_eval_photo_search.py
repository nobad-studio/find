import importlib.util
import math
import os

_spec = importlib.util.spec_from_file_location(
    "eval_photo_search", os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools", "eval_photo_search.py"))
eps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eps)


def test_perfect_ranking_scores_one():
    rec, ndcg, mrr = eps.metrics(["a", "b", "c"], {"a": 2, "b": 2, "c": 1})
    assert rec == 1.0 and math.isclose(ndcg, 1.0) and mrr == 1.0


def test_partly_relevant_counts_for_ndcg_not_recall():
    rec, ndcg, mrr = eps.metrics(["c", "x", "a"], {"a": 2, "c": 1})
    assert rec == 1.0                      # the one grade-2 photo is in the top 10
    assert 0 < ndcg < 1                    # but not first
    assert mrr == 1 / 3


def test_nothing_found_scores_zero_and_no_judgements_is_skipped():
    assert eps.metrics([], {"a": 2}) == (0.0, 0.0, 0.0)
    assert eps.metrics(["a"], {}) == (None, None, None)
    assert eps.aggregate([dict(recall=None, ndcg=None, mrr=None), dict(recall=1.0, ndcg=0.5, mrr=1.0)]) == \
        {"n": 2, "recall10": 1.0, "ndcg10": 0.5, "mrr10": 1.0}


def test_recall_is_over_at_most_k():
    grades = {f"p{i}": 2 for i in range(15)}
    rec, _n, _m = eps.metrics([f"p{i}" for i in range(10)], grades)
    assert rec == 1.0
