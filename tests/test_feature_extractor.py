import polars as pl
import pytest

from src.ml.feature_extractor import (
    FEATURE_COLUMNS,
    FEATURE_SETS,
    KEY_COLUMNS,
    extract_features,
    item_stats,
    prediction_point,
)


def _history():
    # One user, 4 orders, 7 days apart.
    # Product 1 (aisle 10): orders 1, 2, 3.  Product 2 (aisle 10): order 3.
    # Product 3 (aisle 20): order 1, then order 4 (after the prediction point).
    rows = [
        (1, 1, 10, 0), (1, 2, 10, 1), (1, 3, 10, 1),
        (2, 3, 10, 0),
        (3, 1, 20, 0), (3, 4, 20, 1),
    ]
    day = {1: 0, 2: 7, 3: 14, 4: 21}
    return pl.DataFrame(
        {
            "user_id": [1] * len(rows),
            "product_id": [r[0] for r in rows],
            "order_number": [r[1] for r in rows],
            "aisle_id": [r[2] for r in rows],
            "reordered": [r[3] for r in rows],
            "day": [day[r[1]] for r in rows],
            "dsp": [0 if r[1] == 1 else 7 for r in rows],
            "dsp_capped": [0] * len(rows),
            "add_to_cart_order": [1] * len(rows),
        }
    )


def _at(t_order=4, t_day=21):
    return pl.DataFrame(
        {"user_id": [1], "t_order": [t_order], "t_day": [t_day], "t_dow": [2],
         "t_hour": [10], "t_dsp": [7.0], "t_dsp_capped": [0]}
    )


def _features(version="v4"):
    hist = _history()
    return extract_features(hist, _at(), item_stats(hist), version=version)


def _row(df, product_id):
    return df.filter(pl.col("product_id") == product_id).row(0, named=True)


def test_rounds_are_cumulative():
    versions = list(FEATURE_SETS)
    assert versions == ["v0", "v1", "v2", "v3", "v4"]
    for prev, cur in zip(versions, versions[1:]):
        assert FEATURE_SETS[cur][: len(FEATURE_SETS[prev])] == FEATURE_SETS[prev]
    assert FEATURE_COLUMNS == FEATURE_SETS["v4"]


def test_ids_are_never_features():
    for cols in FEATURE_SETS.values():
        assert not [c for c in cols if c.endswith("_id")]


@pytest.mark.parametrize("version", list(FEATURE_SETS))
def test_output_columns_follow_version(version):
    df = _features(version)
    assert df.columns == KEY_COLUMNS + ["up_last_order"] + FEATURE_SETS[version]


def test_same_candidates_for_every_version():
    rows = {v: _features(v).select(KEY_COLUMNS).sort(KEY_COLUMNS) for v in FEATURE_SETS}
    for df in rows.values():
        assert df.equals(rows["v0"])


def test_v0_v2_by_hand():
    df = _features()
    p1 = _row(df, 1)
    assert p1["up_cnt"] == 3
    assert p1["up_orders_since"] == 1
    assert p1["up_rate"] == pytest.approx(1.0)
    assert p1["up_days_since"] == 7          # 21 - 14
    assert p1["up_mean_gap"] == pytest.approx(7.0)
    assert p1["streak_ratio"] == pytest.approx(1.0)
    assert p1["up_decay"] == pytest.approx(0.9 + 0.9**2 + 0.9**3)
    assert (p1["in_last_1"], p1["in_last_2"], p1["in_last_3"]) == (1, 1, 1)

    p3 = _row(df, 3)  # bought only in order 1
    assert p3["up_orders_since"] == 3
    assert p3["up_mean_gap"] is None and p3["streak_ratio"] is None
    assert (p3["in_last_1"], p3["in_last_2"], p3["in_last_3"]) == (0, 0, 1)


def test_v3_customer_and_item_by_hand():
    p1 = _row(_features(), 1)
    assert p1["u_n_orders"] == 3
    assert p1["u_basket"] == pytest.approx(5 / 3)       # baskets 2, 1, 2
    assert p1["u_n_products"] == 3
    # item stats from the whole history passed in, order 4 included.
    assert p1["p_reorder_ratio"] == pytest.approx(2 / 3)
    assert p1["a_reorder_ratio"] == pytest.approx(2 / 4)  # aisle 10
    assert p1["ua_rate"] == pytest.approx(3 / 3)         # aisle 10 in orders 1-3
    assert _row(_features(), 3)["ua_rate"] == pytest.approx(1 / 3)


def test_orders_at_or_after_prediction_point_are_ignored():
    # Same prediction point, with and without the later order 4.
    hist = _history()
    stats = item_stats(hist)
    full = extract_features(hist, _at(), stats)
    cut = extract_features(hist.filter(pl.col("order_number") < 4), _at(), stats)
    assert full.equals(cut)


def test_v3_needs_item_stats():
    with pytest.raises(ValueError):
        extract_features(_history(), _at(), None, version="v3")
    # v0-v2 work without them.
    assert extract_features(_history(), _at(), None, version="v2").height == 3


def test_prediction_point_for_live_user():
    hist = _history()
    at = prediction_point(hist, dow=5, hour=18, days_since_last=45)
    row = at.row(0, named=True)
    assert row["t_order"] == 5 and row["t_day"] == 21 + 45
    assert row["t_dsp"] == 30 and row["t_dsp_capped"] == 1  # capped like Instacart
    df = extract_features(hist, at, item_stats(hist))
    assert sorted(df["product_id"].to_list()) == [1, 2, 3]
