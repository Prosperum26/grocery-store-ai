"""Candidate generation and features for next-basket prediction.

One entry point, used both offline (scripts/data_prep.py) and later by the
/predict endpoint:

    extract_features(history, at, item_stats=None, version="v4")

history     purchase history, one row per (order, product):
            user_id, order_number, day, dsp, dsp_capped,
            add_to_cart_order, reordered, product_id, aisle_id
at          prediction points, one row per (user, order to predict):
            user_id, t_order, t_day, t_dow, t_hour, t_dsp, t_dsp_capped
            (use `prediction_point` to build one for a live user)
item_stats  catalog-level stats from `item_stats()`, needed from v3 on.

Only orders with order_number < t_order are used, so the same history can
hold orders after the prediction point without leaking them.

Features are added in rounds (FEATURE_SETS) to measure what helps.
product_id and aisle_id are keys, never features, so a model trained on
Instacart can be applied to another catalog (e.g. Bach Hoa Xanh).
See docs/features.md for names, meaning and formulas.
"""

import polars as pl

MAX_CANDIDATES = 100
DECAY = 0.9  # weight of a purchase k orders ago = DECAY ** k

KEY_COLUMNS = ["user_id", "t_order", "product_id"]
# Kept next to the features for checks, never given to the model.
INFO_COLUMNS = ["up_last_order"]

_ROUNDS = {
    "v0": ["up_cnt", "up_orders_since", "up_rate"],
    "v1": ["streak_ratio", "up_days_since", "up_mean_gap"],
    "v2": ["up_decay", "in_last_1", "in_last_2", "in_last_3"],
    "v3": [
        # customer
        "u_n_orders", "u_basket", "u_reorder_rate", "u_n_products",
        "u_mean_dsp", "u_pct_capped",
        # item
        "p_reorder_ratio", "a_reorder_ratio", "ua_rate",
    ],
    "v4": ["t_dow", "t_hour", "t_dsp", "t_dsp_capped"],
}
# Each round contains all features of the previous ones.
FEATURE_SETS: dict[str, list[str]] = {}
_acc: list[str] = []
for _v, _cols in _ROUNDS.items():
    _acc = _acc + _cols
    FEATURE_SETS[_v] = _acc
FEATURE_COLUMNS = FEATURE_SETS["v4"]


def item_stats(history: pl.DataFrame) -> pl.DataFrame:
    """Global reorder rate per product and per aisle.

    Pass only orders that are never a label (~is_target), otherwise other
    users' val/test baskets leak into these numbers. Rates, not counts, so
    they do not depend on the size of the dataset.
    """
    aisle = history.group_by("aisle_id").agg(a_reorder_ratio=pl.col("reordered").mean())
    return (
        history.group_by("product_id")
        .agg(
            aisle_id=pl.col("aisle_id").first(),
            p_reorder_ratio=pl.col("reordered").mean(),
        )
        .join(aisle, on="aisle_id", how="left")
        .select("product_id", "p_reorder_ratio", "a_reorder_ratio")
    )


def prediction_point(
    history: pl.DataFrame, dow: int, hour: int, days_since_last: float
) -> pl.DataFrame:
    """Prediction point for each user's next, not yet placed, order."""
    return history.group_by("user_id").agg(
        t_order=pl.col("order_number").max() + 1,
        t_day=pl.col("day").max() + days_since_last,
        t_dow=pl.lit(dow),
        t_hour=pl.lit(hour),
        t_dsp=pl.lit(float(min(days_since_last, 30))),
        t_dsp_capped=pl.lit(int(days_since_last >= 30), pl.Int8),
    )


def extract_features(
    history: pl.DataFrame,
    at: pl.DataFrame,
    item_stats: pl.DataFrame | None = None,
    version: str = "v4",
    max_candidates: int = MAX_CANDIDATES,
) -> pl.DataFrame:
    """Candidates and features: KEY_COLUMNS + INFO_COLUMNS + FEATURE_SETS[version].

    Candidates are the products the user bought before t_order, at most
    `max_candidates` per prediction point, ranked by up_decay. They do not
    depend on `version`, so every round is scored on the same rows.
    """
    if version not in FEATURE_SETS:
        raise ValueError(f"unknown version {version!r}, expected one of {list(FEATURE_SETS)}")
    needs_items = "p_reorder_ratio" in FEATURE_SETS[version]
    if needs_items and item_stats is None:
        raise ValueError(f"version {version} needs item_stats")

    past = history.join(at, on="user_id").filter(
        pl.col("order_number") < pl.col("t_order")  # golden rule
    )

    up = past.group_by(KEY_COLUMNS).agg(
        up_cnt=pl.len(),
        up_last_order=pl.col("order_number").max(),
        up_last_day=pl.col("day").max(),
        aisle_id=pl.col("aisle_id").first(),
        # Average days between consecutive purchases; null if bought once.
        up_mean_gap=pl.col("day").sort().diff().mean(),
        up_decay=(DECAY ** (pl.col("t_order") - pl.col("order_number"))).sum(),
    )

    # One row per past order first, so order-level stats are not
    # weighted by basket size.
    past_orders = past.group_by("user_id", "t_order", "order_number").agg(
        dsp=pl.col("dsp").first(),
        dsp_capped=pl.col("dsp_capped").first(),
        basket=pl.len(),
        reordered=pl.col("reordered").sum(),
    )
    u = past_orders.group_by("user_id", "t_order").agg(
        u_n_orders=pl.len(),
        u_basket=pl.col("basket").mean(),
        u_reorder_rate=pl.col("reordered").sum() / pl.col("basket").sum(),
        # First order has no previous order, so exclude it from gap stats.
        u_mean_dsp=pl.col("dsp").filter(pl.col("order_number") > 1).mean(),
        u_pct_capped=pl.col("dsp_capped").filter(pl.col("order_number") > 1).mean(),
    )
    u_products = up.group_by("user_id", "t_order").agg(u_n_products=pl.len())
    # Past orders of the user that contain at least one product of the aisle.
    ua = (
        past.group_by("user_id", "t_order", "aisle_id")
        .agg(ua_orders=pl.col("order_number").n_unique())
    )

    df = (
        up.join(u, on=["user_id", "t_order"])
        .join(u_products, on=["user_id", "t_order"])
        .join(ua, on=["user_id", "t_order", "aisle_id"], how="left")
        .join(at, on=["user_id", "t_order"])
        .with_columns(
            up_rate=pl.col("up_cnt") / pl.col("u_n_orders"),
            up_orders_since=pl.col("t_order") - pl.col("up_last_order"),
            up_days_since=pl.col("t_day") - pl.col("up_last_day"),
            ua_rate=pl.col("ua_orders") / pl.col("u_n_orders"),
        )
        .with_columns(
            # ~1 means "due for a refill". Null when the gap is unknown or 0.
            streak_ratio=pl.when(pl.col("up_mean_gap") > 0)
            .then(pl.col("up_days_since") / pl.col("up_mean_gap"))
            .otherwise(None),
            in_last_1=(pl.col("up_orders_since") <= 1).cast(pl.Int8),
            in_last_2=(pl.col("up_orders_since") <= 2).cast(pl.Int8),
            in_last_3=(pl.col("up_orders_since") <= 3).cast(pl.Int8),
        )
    )
    if needs_items:
        df = df.join(item_stats, on="product_id", how="left")

    # Candidates: top-N products per prediction point, by recency-weighted
    # count. Sort first so ties are broken by product_id and runs are
    # reproducible.
    df = df.sort(KEY_COLUMNS).with_columns(
        rk=pl.col("up_decay")
        .rank("ordinal", descending=True)
        .over("user_id", "t_order")
    ).filter(pl.col("rk") <= max_candidates)

    return df.select(KEY_COLUMNS + INFO_COLUMNS + FEATURE_SETS[version])
