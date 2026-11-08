import numpy as np
import polars as pl
import pytest

from scripts.eval_topk import compare, paired_bootstrap, per_order_metrics

TARGETS = pl.DataFrame({"user_id": [1, 2], "t_order": [5, 5]})
TRUTH = pl.DataFrame({"user_id": [1, 1, 2], "t_order": [5, 5, 5], "product_id": [10, 11, 20]})


def preds(rows):
    return pl.DataFrame(rows, schema=["user_id", "t_order", "product_id", "rank"], orient="row")


def test_metrics_only_count_the_top_k():
    # User 1: rank 1 is right, rank 3 is right but outside k = 2.
    p = preds([(1, 5, 10, 1), (1, 5, 99, 2), (1, 5, 11, 3)])
    m = per_order_metrics(p, TRUTH, TARGETS, 2)
    u1 = m.filter(pl.col("user_id") == 1).row(0, named=True)
    assert u1["recall"] == 0.5
    assert u1["precision"] == 0.5
    assert u1["hit_rate"] == 1.0


def test_order_without_predictions_scores_zero_and_is_kept():
    m = per_order_metrics(preds([(1, 5, 10, 1)]), TRUTH, TARGETS, 5)
    assert m.height == 2
    u2 = m.filter(pl.col("user_id") == 2).row(0, named=True)
    assert (u2["recall"], u2["precision"], u2["ndcg"], u2["hit_rate"]) == (0.0, 0.0, 0.0, 0.0)


def test_perfect_ranking_has_ndcg_one():
    p = preds([(1, 5, 10, 1), (1, 5, 11, 2), (2, 5, 20, 1)])
    m = per_order_metrics(p, TRUTH, TARGETS, 5)
    assert m["ndcg"].to_list() == pytest.approx([1.0, 1.0])


def test_bootstrap_ci_contains_the_difference_and_excludes_zero_when_clear():
    rng = np.random.default_rng(0)
    b = rng.random(2000)
    r = paired_bootstrap(b + 0.1 + rng.normal(0, 0.01, 2000), b, n_boot=200)
    assert r["ci_low"] <= r["diff"] <= r["ci_high"]
    assert r["ci_low"] > 0


def test_bootstrap_of_identical_lists_is_exactly_zero():
    a = np.array([0.1, 0.5, 0.9])
    assert paired_bootstrap(a, a, n_boot=50) == {"diff": 0.0, "ci_low": 0.0, "ci_high": 0.0}


def test_bootstrap_refuses_different_lengths():
    with pytest.raises(ValueError):
        paired_bootstrap(np.zeros(2), np.zeros(3), n_boot=5)


def test_compare_only_diffs_models_against_baselines():
    runs = {"lightgbm": preds([(1, 5, 10, 1)]), "tifuknn": preds([(2, 5, 20, 1)])}
    res = compare(runs, TRUTH, TARGETS, 5)
    assert set(res["means"]) == {"lightgbm", "tifuknn"}
    assert set(res["diffs"]) == {"lightgbm - tifuknn"}
