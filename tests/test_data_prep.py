from pathlib import Path

import polars as pl
import pytest

from src.ml.data_prep import (
    RAW_DIR,
    add_timeline_and_roles,
    build_history,
    check_no_leakage,
    filter_users,
    make_split,
    prepare,
    sample_users,
)
from src.ml.feature_extractor import build_examples, product_features


def _toy_raw():
    # User 1: 6 orders. Product 1 in every order, product 2 only in the
    # last (test) order, product 3 only in order 1.
    # User 2: 4 orders, must be dropped by the >= 5 orders filter.
    orders = pl.DataFrame(
        {
            "order_id": [10, 11, 12, 13, 14, 15, 20, 21, 22, 23],
            "user_id": [1] * 6 + [2] * 4,
            "order_number": [1, 2, 3, 4, 5, 6, 1, 2, 3, 4],
            "order_dow": [0] * 10,
            "order_hour_of_day": [9] * 10,
            "days_since_prior_order": [None, 7.0, 7.0, 30.0, 7.0, 7.0,
                                       None, 1.0, 1.0, 1.0],
        }
    )
    rows = [(oid, 1) for oid in range(10, 16)] + [(15, 2), (10, 3)]
    rows += [(oid, 1) for oid in range(20, 24)]
    op = pl.DataFrame(
        {
            "order_id": [r[0] for r in rows],
            "product_id": [r[1] for r in rows],
            "add_to_cart_order": [1] * len(rows),
            "reordered": [0] * len(rows),
        }
    )
    return orders, op


def _toy(train_targets=1):
    orders, op = _toy_raw()
    orders = add_timeline_and_roles(filter_users(orders), train_targets)
    hist = build_history(orders, op)
    prod = product_features(hist.filter(~pl.col("is_target")))
    return orders, hist, prod


def test_min_orders_filter():
    orders, _ = _toy_raw()
    assert filter_users(orders)["user_id"].unique().to_list() == [1]


def test_roles_follow_spec():
    orders, _, _ = _toy()
    roles = dict(zip(orders["order_number"], orders["role"]))
    assert roles == {1: "train", 2: "train", 3: "train", 4: "train",
                     5: "val", 6: "test"}
    targets = orders.filter(pl.col("is_target"))["order_number"].to_list()
    assert targets == [4, 5, 6]


def test_more_train_targets():
    orders, _, _ = _toy(train_targets=2)
    targets = orders.filter(pl.col("is_target"))["order_number"].to_list()
    assert targets == [3, 4, 5, 6]


def test_cumulative_day_and_cap_flag():
    orders, _, _ = _toy()
    assert orders["day"].to_list() == [0, 7, 14, 44, 51, 58]
    assert orders["dsp_capped"].to_list() == [0, 0, 0, 1, 0, 0]


def test_sample_is_reproducible_and_exact():
    orders = pl.DataFrame({"user_id": list(range(100)), "x": [0] * 100})
    a = sample_users(orders, 10, seed=1)["user_id"].sort().to_list()
    b = sample_users(orders, 10, seed=1)["user_id"].sort().to_list()
    assert a == b and len(a) == 10


def test_no_leakage_and_labels():
    orders, hist, prod = _toy()
    for role, t_order in [("train", 4), ("val", 5), ("test", 6)]:
        df, n_truth = make_split(orders, hist, prod, role)
        check_no_leakage(df)
        assert df["t_order"].unique().to_list() == [t_order]
        assert df["u_n_orders"].unique().to_list() == [t_order - 1]
        labels = dict(zip(df["product_id"], df["label"]))
        # Product 2 is first bought in the test order: never a candidate.
        assert 2 not in labels
        assert labels == {1: 1, 3: 0}
        assert n_truth == (2 if role == "test" else 1)


def test_product_features_ignore_label_orders():
    _, hist, prod = _toy()
    # Product 2 only appears in the test order.
    assert 2 not in prod["product_id"].to_list()
    # Product 1: orders 1-3 only, not 4/5/6.
    assert prod.filter(pl.col("product_id") == 1)["p_cnt"].item() == 3


def test_check_no_leakage_raises():
    bad = pl.DataFrame({"user_id": [1], "t_order": [4], "product_id": [1],
                        "up_last_order": [4], "u_n_orders": [3]})
    with pytest.raises(ValueError):
        check_no_leakage(bad)


def test_candidates_capped():
    hist = pl.DataFrame(
        {
            "user_id": [1] * 10,
            "order_number": [1] * 10,
            "day": [0] * 10,
            "dsp": [0] * 10,
            "add_to_cart_order": list(range(1, 11)),
            "reordered": [0] * 10,
            "product_id": list(range(10)),
        }
    )
    targets = pl.DataFrame({"user_id": [1], "t_order": [2], "t_day": [7],
                            "t_dow": [0], "t_hour": [9], "t_dsp": [7],
                            "t_dsp_capped": [0]})
    prod = product_features(hist)
    assert build_examples(hist, targets, prod, max_candidates=3).height == 3


@pytest.mark.skipif(not (RAW_DIR / "orders.csv").exists(), reason="no raw data")
def test_real_data_no_leakage(tmp_path: Path):
    report = prepare(RAW_DIR, tmp_path, n_users=300)
    for role in ("train", "val", "test"):
        df = pl.read_parquet(tmp_path / f"{role}.parquet")
        check_no_leakage(df)
        # >= 5 orders, so even the train target (n-2) has >= 2 past orders.
        assert df["u_n_orders"].min() >= 2
        assert df.group_by("user_id", "t_order").len()["len"].max() <= 100
        assert report[role]["users"] <= 300
