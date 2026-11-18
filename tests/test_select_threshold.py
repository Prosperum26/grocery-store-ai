import numpy as np
import polars as pl
import pytest

from scripts.select_threshold import calibration_stats, f1_at_tau, oracle_recall, ranked, reliability


def test_reliability_perfect_and_biased():
    p = np.array([0.15] * 20 + [0.85] * 20)
    y = np.array([1] * 3 + [0] * 17 + [1] * 17 + [0] * 3)
    _, ece = reliability(p, y)
    assert ece == pytest.approx(0.0)
    _, ece = reliability(np.full(10, 0.9), np.zeros(10))
    assert ece == pytest.approx(0.9)


def _toy():
    # One order, true basket {1, 2}. Scores: 1 -> .9, 3 -> .5, 2 -> .1
    cand = pl.DataFrame({"user_id": [1, 1, 1], "t_order": [5, 5, 5], "product_id": [1, 2, 3]})
    truth = pl.DataFrame({"user_id": [1, 1], "t_order": [5, 5], "product_id": [1, 2]})
    return ranked(cand, np.array([0.9, 0.1, 0.5])), truth


def test_f1_at_tau_cuts_list_and_divides_by_items_shown():
    scored, truth = _toy()
    low = f1_at_tau(scored, truth, 0.05)    # recommend 1, 3, 2: 2 hits
    assert (low["precision"], low["recall"]) == (pytest.approx(2 / 3, abs=1e-4), 1.0)
    high = f1_at_tau(scored, truth, 0.6)    # recommend only 1
    assert (high["precision"], high["recall"]) == (1.0, 0.5)
    assert high["f1@15"] == pytest.approx(round(2 / 3, 4))


def test_f1_at_tau_empty_list_scores_zero():
    scored, truth = _toy()
    r = f1_at_tau(scored, truth, 0.95)
    assert r["f1@15"] == 0 and r["empty_orders"] == 1


def test_quantile_ece_sees_miscalibration_hidden_in_one_wide_bin():
    # All p in [0, 0.1): one equal-width bin, where over- and under-confidence
    # cancel out. Quantile bins split them apart.
    p = np.array([0.01] * 50 + [0.09] * 50)
    y = np.array(([1] + [0] * 9) * 5 + [0] * 50)
    _, ece_w = reliability(p, y)
    _, ece_q = reliability(p, y, quantile=True)
    assert ece_w == pytest.approx(0.0, abs=1e-9)
    assert ece_q == pytest.approx(0.09)


def test_calibration_stats_brier():
    s = calibration_stats(np.array([1.0, 0.0]), np.array([1, 0]))
    assert s["brier"] == 0 and s["brier_base_rate"] == pytest.approx(0.25)


def test_oracle_recall_caps_at_k_and_ignores_new_products():
    # Order A: 3 true, 2 of them candidates -> 2/3. Order B: 20 true, all
    # candidates -> min(20, 15) / 20.
    cand = pl.DataFrame({"user_id": [1] * 2 + [2] * 20, "t_order": [5] * 22,
                         "product_id": [1, 2] + list(range(20))})
    truth = pl.DataFrame({"user_id": [1] * 3 + [2] * 20, "t_order": [5] * 23,
                          "product_id": [1, 2, 99] + list(range(20))})
    assert oracle_recall(cand, truth) == pytest.approx(round((2 / 3 + 15 / 20) / 2, 4))
