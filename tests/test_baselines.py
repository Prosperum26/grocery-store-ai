import math

import polars as pl
import pytest

from scripts.baselines import evaluate, personal_freq, popularity, true_baskets
from scripts.tifuknn import order_weights, tifuknn, user_vectors
from scripts.data_prep import add_timeline_and_roles, build_history, targets_of


def _toy():
    # One user, 6 orders: train target 4, val 5, test 6.
    # Product 1: orders 1-6. Product 2: orders 1, 2. Product 3: order 3.
    # Product 4: only order 6 (test), never seen before.
    orders = pl.DataFrame(
        {
            "order_id": [10, 11, 12, 13, 14, 15],
            "user_id": [1] * 6,
            "order_number": [1, 2, 3, 4, 5, 6],
            "order_dow": [0] * 6,
            "order_hour_of_day": [9] * 6,
            "days_since_prior_order": [None, 7.0, 7.0, 7.0, 7.0, 7.0],
        }
    )
    rows = [(o, 1) for o in range(10, 16)] + [(10, 2), (11, 2), (12, 3), (15, 4)]
    op = pl.DataFrame(
        {
            "order_id": [r[0] for r in rows],
            "product_id": [r[1] for r in rows],
            "add_to_cart_order": [1] * len(rows),
            "reordered": [0] * len(rows),
        }
    )
    orders = add_timeline_and_roles(orders)
    return orders, build_history(orders, op)


def test_personal_freq_uses_only_past_and_ranks():
    orders, hist = _toy()
    targets = targets_of(orders, "test")
    preds = personal_freq(hist, targets, n=2)
    # Product 1 (5x) then product 2 (2x); product 4 is in the target itself.
    assert preds["product_id"].to_list() == [1, 2]
    assert preds["rank"].to_list() == [1, 2]


def test_personal_freq_tie_prefers_recent():
    orders, hist = _toy()
    targets = targets_of(orders, "train")  # past orders 1-3
    preds = personal_freq(hist, targets, n=3)
    # Product 1: 3x. Products 2 (2x) and 3 (1x).
    assert preds["product_id"].to_list() == [1, 2, 3]


def test_popularity_ignores_label_orders():
    orders, hist = _toy()
    targets = targets_of(orders, "test")
    preds = popularity(hist, targets, n=10)
    # Product 4 appears only in the test order, a label order.
    assert 4 not in preds["product_id"].to_list()
    assert preds["rank"].to_list() == list(range(1, preds.height + 1))


def test_evaluate_metrics_by_hand():
    orders, hist = _toy()
    targets = targets_of(orders, "test")
    truth = true_baskets(hist, targets)  # products 1 and 4
    m = evaluate(personal_freq(hist, targets, n=20), truth, targets)
    # Ranked [1, 2, 3]: only product 1 (rank 1) is a hit; product 4 is new.
    assert m["recall@15"] == pytest.approx(0.5)
    assert m["precision@20"] == pytest.approx(round(1 / 20, 4))
    assert m["f1@15"] == pytest.approx(round(2 / 17, 4))
    idcg = 1 + 1 / math.log2(3)  # 2 true products at ranks 1, 2
    assert m["ndcg@15"] == pytest.approx(round(1 / idcg, 4))


def test_evaluate_ignores_hits_beyond_k():
    targets = pl.DataFrame({"user_id": [1], "t_order": [5]})
    truth = pl.DataFrame({"user_id": [1], "t_order": [5], "product_id": [7]})
    preds = pl.DataFrame({"user_id": [1], "t_order": [5], "product_id": [7], "rank": [16]})
    m = evaluate(preds, truth, targets)
    assert m["recall@15"] == 0 and m["ndcg@15"] == 0
    assert m["precision@20"] == pytest.approx(0.05)


def test_evaluate_order_without_prediction_scores_zero():
    targets = pl.DataFrame({"user_id": [1, 2], "t_order": [5, 5]})
    truth = pl.DataFrame({"user_id": [1, 2], "t_order": [5, 5], "product_id": [7, 8]})
    preds = pl.DataFrame({"user_id": [1], "t_order": [5], "product_id": [7], "rank": [1]})
    m = evaluate(preds, truth, targets)
    assert m["recall@15"] == pytest.approx(0.5)


# ---------- TIFU-KNN ----------

def _hist(rows):
    """rows: (user_id, order_number, product_id)."""
    return pl.DataFrame(
        {
            "user_id": [r[0] for r in rows],
            "order_number": [r[1] for r in rows],
            "product_id": [r[2] for r in rows],
        }
    )


def test_tifu_order_weights_by_hand():
    # 5 past orders, groups of 2 counted from the newest: {5,4} {3,2} {1}.
    hist = _hist([(1, o, 1) for o in range(1, 7)])
    targets = pl.DataFrame({"user_id": [1], "t_order": [6]})
    w = order_weights(hist, targets, group_size=2, r_b=0.5, r_g=0.5)
    got = dict(zip(w["order_number"], w["w"]))
    expected = {5: 1 / 6, 4: 1 / 12, 3: 1 / 12, 2: 1 / 24, 1: 1 / 12}
    assert got == pytest.approx(expected)


def test_tifu_user_vector_ignores_target_and_later_orders():
    hist = _hist([(1, 1, 1), (1, 2, 1), (1, 3, 2), (1, 4, 3)])
    targets = pl.DataFrame({"user_id": [1], "t_order": [3]})
    _, products, x = user_vectors(hist, targets)
    assert products.tolist() == [1]  # products 2, 3 come at/after the target
    assert x.shape == (1, 1)


def test_tifu_neighbours_bring_new_products():
    # Users 1 and 2 buy product 1; user 2 also buys product 9.
    hist = _hist([(1, 1, 1), (1, 2, 1), (2, 1, 1), (2, 1, 9), (2, 2, 1)])
    targets = pl.DataFrame({"user_id": [1, 2], "t_order": [3, 3]})
    preds = tifuknn(hist, targets, n=5, k_neighbors=1, alpha=0.9)
    user1 = preds.filter(pl.col("user_id") == 1).sort("rank")
    # Own product first, neighbour's product next.
    assert user1["product_id"].to_list() == [1, 9]
