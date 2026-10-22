from pathlib import Path

import polars as pl
import pytest

from scripts.data_prep import (
    RAW_DIR,
    SEED,
    add_timeline_and_roles,
    build_history,
    check_no_leakage,
    filter_users,
    load_order_products,
    load_orders,
    make_split,
    prepare,
    sample_users,
)
from src.ml.feature_extractor import extract_features, item_stats


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
            "aisle_id": [1] * len(rows),
        }
    )
    return orders, op


def _toy(train_targets=1):
    orders, op = _toy_raw()
    orders = add_timeline_and_roles(filter_users(orders), train_targets)
    hist = build_history(orders, op)
    prod = item_stats(hist.filter(~pl.col("is_target")))
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


def test_item_stats_ignore_label_orders():
    _, hist, prod = _toy()
    # Product 2 only appears in the test order.
    assert 2 not in prod["product_id"].to_list()
    # Product 3 is only in order 1 (a history order), so it is there.
    assert 3 in prod["product_id"].to_list()


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
            "dsp_capped": [0] * 10,
            "aisle_id": [1] * 10,
            "add_to_cart_order": list(range(1, 11)),
            "reordered": [0] * 10,
            "product_id": list(range(10)),
        }
    )
    targets = pl.DataFrame({"user_id": [1], "t_order": [2], "t_day": [7],
                            "t_dow": [0], "t_hour": [9], "t_dsp": [7],
                            "t_dsp_capped": [0]})
    prod = item_stats(hist)
    assert extract_features(hist, targets, prod, max_candidates=3).height == 3


def test_user_gap_stats_skip_first_order_and_flag_cap():
    # Gaps of user 1: order 1 has none, then 7, 7, 30 (capped), 7, 7.
    orders, hist, prod = _toy()
    expected = {
        "train": (7.0, 0.0),           # past orders 1-3: gaps 7, 7
        "val": (44 / 3, 1 / 3),        # past orders 1-4: gaps 7, 7, 30
        "test": (51 / 4, 1 / 4),       # past orders 1-5: gaps 7, 7, 30, 7
    }
    for role, (mean_dsp, pct_capped) in expected.items():
        df, _ = make_split(orders, hist, prod, role)
        assert df["u_mean_dsp"].unique().to_list() == [pytest.approx(mean_dsp)]
        assert df["u_pct_capped"].unique().to_list() == [pytest.approx(pct_capped)]


REAL_USERS = 300
needs_raw = pytest.mark.skipif(
    not (RAW_DIR / "orders.csv").exists(), reason="no raw data"
)


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    """Run the pipeline once on a small real sample, shared by the tests."""
    out = tmp_path_factory.mktemp("processed")
    report = prepare(RAW_DIR, out, n_users=REAL_USERS)
    splits = {r: pl.read_parquet(out / f"{r}.parquet") for r in report}
    # Rebuild the purchase history independently of build_examples.
    orders = sample_users(filter_users(load_orders(RAW_DIR)), REAL_USERS, SEED)
    hist = load_order_products(RAW_DIR, orders["order_id"]).join(
        orders.select("order_id", "user_id", "order_number"), on="order_id"
    )
    return out, report, splits, hist


@needs_raw
def test_real_data_no_leakage(real):
    out, report, splits, _ = real
    for role, df in splits.items():
        check_no_leakage(df)
        # >= 5 orders, so even the train target (n-2) has >= 2 past orders.
        assert df["u_n_orders"].min() >= 2
        assert report[role]["users"] == REAL_USERS
    assert (out / "meta.json").exists()


@needs_raw
def test_real_data_features_match_recomputation(real):
    """Recompute features from raw history for random rows and compare."""
    _, _, splits, hist = real
    for role, df in splits.items():
        for row in df.sample(50, seed=SEED).iter_rows(named=True):
            past = hist.filter(
                (pl.col("user_id") == row["user_id"])
                & (pl.col("order_number") < row["t_order"])
            )
            mine = past.filter(pl.col("product_id") == row["product_id"])
            assert row["up_cnt"] == mine.height, role
            assert row["up_last_order"] == mine["order_number"].max(), role
            assert row["u_n_orders"] == past["order_number"].n_unique(), role
            assert row["u_n_products"] == past["product_id"].n_unique(), role

            in_target = hist.filter(
                (pl.col("user_id") == row["user_id"])
                & (pl.col("order_number") == row["t_order"])
                & (pl.col("product_id") == row["product_id"])
            ).height
            assert row["label"] == in_target, role


@needs_raw
def test_real_data_candidates_capped_at_100(real):
    _, _, splits, _ = real
    for role, df in splits.items():
        sizes = df.group_by("user_id", "t_order").agg(
            n=pl.len(), n_products=pl.col("u_n_products").first()
        )
        big = sizes.filter(pl.col("n_products") > 100)
        # The sample must contain users above the cap, or the cap is untested.
        assert big.height > 0, role
        assert big["n"].to_list() == [100] * big.height, role
        small = sizes.filter(pl.col("n_products") <= 100)
        assert (small["n"] == small["n_products"]).all(), role
