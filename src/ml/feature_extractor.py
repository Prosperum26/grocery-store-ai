"""Candidate generation and features for next-basket prediction."""

import polars as pl

MAX_CANDIDATES = 100
DECAY = 0.9  # weight of a purchase k orders ago = DECAY ** k

KEY_COLUMNS = ["user_id", "t_order", "product_id"]

FEATURE_COLUMNS = [
    # user x product
    "up_cnt",
    "up_rate",
    "up_orders_since",
    "up_days_since",
    "up_mean_gap",
    "streak_ratio",
    "up_decay",
    "up_avg_cart_pos",
    "up_first_order",
    "in_last_1",
    "in_last_2",
    "in_last_3",
    # user
    "u_n_orders",
    "u_basket",
    "u_reorder_rate",
    "u_n_products",
    "u_mean_dsp",
    "u_pct_capped",
    # product (global)
    "p_cnt",
    "p_reorder_ratio",
    "p_avg_cart_pos",
    "p_n_users",
    # context of the target order
    "t_dow",
    "t_hour",
    "t_dsp",
    "t_dsp_capped",
]


def product_features(history: pl.DataFrame) -> pl.DataFrame:
    """Global product stats.

    Pass only orders that are never a label (~is_target),
    otherwise other users' val/test baskets leak into these numbers.
    """
    return history.group_by("product_id").agg(
        p_cnt=pl.len(),
        p_reorder_ratio=pl.col("reordered").mean(),
        p_avg_cart_pos=pl.col("add_to_cart_order").mean(),
        p_n_users=pl.col("user_id").n_unique(),
    )


def build_examples(
    hist: pl.DataFrame,
    targets: pl.DataFrame,
    prod: pl.DataFrame,
    max_candidates: int = MAX_CANDIDATES,
) -> pl.DataFrame:
    """Build candidate rows with features for each target order.

    hist:    one row per (order, product) with user_id, order_number, day,
             dsp, add_to_cart_order, reordered, product_id.
    targets: one row per target order with user_id, t_order, t_day,
             t_dow, t_hour, t_dsp.
    prod:    output of product_features().
    """
    past = hist.join(targets, on="user_id").filter(
        pl.col("order_number") < pl.col("t_order")  # golden rule
    )

    up = past.group_by(KEY_COLUMNS).agg(
        up_cnt=pl.len(),
        up_last_order=pl.col("order_number").max(),
        up_first_order=pl.col("order_number").min(),
        up_last_day=pl.col("day").max(),
        # Average days between consecutive purchases; null if bought once.
        up_mean_gap=pl.col("day").sort().diff().mean(),
        up_avg_cart_pos=pl.col("add_to_cart_order").mean(),
        up_decay=(DECAY ** (pl.col("t_order") - pl.col("order_number"))).sum(),
    )

    # One row per past order first, so order-level stats are not
    # weighted by basket size.
    past_orders = past.group_by("user_id", "t_order", "order_number").agg(
        dsp=pl.col("dsp").first(),
        basket=pl.len(),
        reordered=pl.col("reordered").sum(),
    )
    u = past_orders.group_by("user_id", "t_order").agg(
        u_n_orders=pl.len(),
        u_basket=pl.col("basket").mean(),
        u_reorder_rate=pl.col("reordered").sum() / pl.col("basket").sum(),
        # First order has no previous order, so exclude it from gap stats.
        u_mean_dsp=pl.col("dsp").filter(pl.col("order_number") > 1).mean(),
        u_pct_capped=(pl.col("dsp").filter(pl.col("order_number") > 1) >= 30).mean(),
    )
    u_products = up.group_by("user_id", "t_order").agg(u_n_products=pl.len())

    df = (
        up.join(u, on=["user_id", "t_order"])
        .join(u_products, on=["user_id", "t_order"])
        .join(targets, on=["user_id", "t_order"])
        .join(prod, on="product_id", how="left")
        .with_columns(
            up_rate=pl.col("up_cnt") / pl.col("u_n_orders"),
            up_orders_since=pl.col("t_order") - pl.col("up_last_order"),
            up_days_since=pl.col("t_day") - pl.col("up_last_day"),
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

    # Candidates: top-N products per target order, by recency-weighted count.
    # Sort first so ties are broken by product_id and runs are reproducible.
    df = df.sort(KEY_COLUMNS).with_columns(
        rk=pl.col("up_decay")
        .rank("ordinal", descending=True)
        .over("user_id", "t_order")
    ).filter(pl.col("rk") <= max_candidates)

    return df.select(KEY_COLUMNS + ["up_last_order"] + FEATURE_COLUMNS)
