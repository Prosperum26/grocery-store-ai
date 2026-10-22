"""Instacart preparation and leave-last-out split per user.
Mô tả z đầy đủ chưa =))

Steps
-----
1. Merge order_products__prior and order_products__train into one purchase
   history. Orders with eval_set == "test" are dropped: Kaggle hides their
   products, so they can be neither a label nor a feature source.
2. Sort by order_number and accumulate days_since_prior_order into `day`.
3. Keep users with at least MIN_ORDERS orders (counted after step 1, so
   every kept order has products).
4. Sample n users with a fixed seed (after the filter, so we get exactly n).
5. Split per user with n orders:
       order  n         -> test
       order  n-1       -> val
       orders 1 .. n-2  -> train
   Train label orders are the last `train_targets` train orders (default 1:
   order n-2). Earlier train orders only feed features.

Why leave-last-out
------------------
Instacart has no absolute dates, only the order sequence of each user, so
a global time cut is impossible. Taking the last orders of every user is
the closest to "predict the next basket": val/test always lie after all
data used for features, every user appears in each split, and val sits
between train and test so tuning on it mimics the final evaluation.

days_since_prior_order == 30
----------------------------
Instacart caps the gap at 30, so 30 means "30 days or more". We keep the
value 30 (a lower bound) and add a flag `dsp_capped`. Consequently `day`
and every day-based feature (up_days_since, up_mean_gap, streak_ratio) are
lower bounds for users with capped gaps; the model sees this through
`t_dsp_capped` and `u_pct_capped`. The first order has no previous order:
its gap is null, set to 0 and not flagged.

Run:
    python -m src.ml.data_prep --users 20000
    python -m src.ml.data_prep --users 0        # all users
Outputs data/processed/{train,val,test}.parquet and meta.json (git-ignored).
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from scripts.feature_extractor import MAX_CANDIDATES, build_examples, product_features

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")
MIN_ORDERS = 5
SEED = 42
DSP_CAP = 30
SPLITS = ("train", "val", "test")


def load_orders(raw_dir: Path = RAW_DIR) -> pl.DataFrame:
    """orders.csv without the eval_set == "test" orders."""
    return (
        pl.scan_csv(raw_dir / "orders.csv")
        .filter(pl.col("eval_set") != "test")
        .drop("eval_set")
        .collect()
    )


def load_order_products(raw_dir: Path, order_ids: pl.Series) -> pl.DataFrame:
    """prior + train baskets, read lazily and limited to `order_ids`."""
    keep = pl.DataFrame({"order_id": order_ids}).lazy()
    return (
        pl.concat(
            [
                pl.scan_csv(raw_dir / "order_products__prior.csv"),
                pl.scan_csv(raw_dir / "order_products__train.csv"),
            ]
        )
        .join(keep, on="order_id")
        .collect()
    )


def filter_users(orders: pl.DataFrame, min_orders: int = MIN_ORDERS) -> pl.DataFrame:
    return orders.filter(pl.len().over("user_id") >= min_orders)


def sample_users(orders: pl.DataFrame, n_users: int | None, seed: int = SEED) -> pl.DataFrame:
    """Random users with a fixed seed. Sorting first makes it reproducible."""
    if n_users is None:
        return orders
    users = orders.select("user_id").unique().sort("user_id")
    users = users.sample(min(n_users, users.height), seed=seed)
    return orders.join(users, on="user_id")


def add_timeline_and_roles(orders: pl.DataFrame, train_targets: int = 1) -> pl.DataFrame:
    """Add cumulative day, cap flag, order count, split role and label flag."""
    orders = (
        orders.sort("user_id", "order_number")
        .with_columns(
            dsp=pl.col("days_since_prior_order").fill_null(0),
            dsp_capped=(pl.col("days_since_prior_order") >= DSP_CAP)
            .fill_null(False)
            .cast(pl.Int8),
        )
        .with_columns(
            day=pl.col("dsp").cum_sum().over("user_id"),
            n_orders=pl.col("order_number").max().over("user_id"),
        )
    )
    gap = pl.col("n_orders") - pl.col("order_number")
    return orders.with_columns(
        role=pl.when(gap == 0)
        .then(pl.lit("test"))
        .when(gap == 1)
        .then(pl.lit("val"))
        .otherwise(pl.lit("train")),
        # Label orders; the rest of train only feeds features.
        is_target=(gap <= 1 + train_targets),
    )


def build_history(orders: pl.DataFrame, op: pl.DataFrame) -> pl.DataFrame:
    """Long table: one row per (order, product) with timeline columns."""
    return op.join(
        orders.select(
            "order_id", "user_id", "order_number", "day", "dsp", "dsp_capped",
            "role", "is_target",
        ),
        on="order_id",
    )


def targets_of(orders: pl.DataFrame, role: str) -> pl.DataFrame:
    return orders.filter((pl.col("role") == role) & pl.col("is_target")).select(
        "user_id",
        t_order=pl.col("order_number"),
        t_day=pl.col("day"),
        t_dow=pl.col("order_dow"),
        t_hour=pl.col("order_hour_of_day"),
        t_dsp=pl.col("dsp"),
        t_dsp_capped=pl.col("dsp_capped"),
    )


def make_split(
    orders: pl.DataFrame, hist: pl.DataFrame, prod: pl.DataFrame, role: str
) -> tuple[pl.DataFrame, int]:
    """Return (labelled examples, number of items in the true baskets)."""
    targets = targets_of(orders, role)
    examples = build_examples(hist, targets, prod)

    truth = hist.join(
        targets.select("user_id", "t_order"),
        left_on=["user_id", "order_number"],
        right_on=["user_id", "t_order"],
    ).select("user_id", pl.col("order_number").alias("t_order"), "product_id")

    labelled = examples.join(
        truth.with_columns(label=pl.lit(1, pl.Int8)),
        on=["user_id", "t_order", "product_id"],
        how="left",
    ).with_columns(pl.col("label").fill_null(0))
    return labelled, truth.height


def check_no_leakage(df: pl.DataFrame) -> None:
    """Every order used for features must come before the target order."""
    problems = {
        "uses orders at or after the target": df.filter(
            pl.col("up_last_order") >= pl.col("t_order")
        ).height,
        "user stats count more orders than exist before the target": df.filter(
            pl.col("u_n_orders") >= pl.col("t_order")
        ).height,
        "duplicated (user, target, product)": df.height
        - df.select("user_id", "t_order", "product_id").unique().height,
    }
    bad = {k: v for k, v in problems.items() if v}
    if bad:
        raise ValueError(f"Leakage check failed: {bad}")


def prepare(
    raw_dir: Path, out_dir: Path, n_users: int | None, train_targets: int = 1
) -> dict[str, dict]:
    orders = sample_users(filter_users(load_orders(raw_dir)), n_users)
    orders = add_timeline_and_roles(orders, train_targets)
    hist = build_history(orders, load_order_products(raw_dir, orders["order_id"]))
    # Global product stats only from orders that are never a label.
    prod = product_features(hist.filter(~pl.col("is_target")))

    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for role in SPLITS:
        df, n_truth = make_split(orders, hist, prod, role)
        check_no_leakage(df)
        df.write_parquet(out_dir / f"{role}.parquet")
        report[role] = {
            "users": df["user_id"].n_unique(),
            "rows": df.height,
            "pos_rate": round(df["label"].mean(), 4),
            "recall_ceiling": round(df["label"].sum() / n_truth, 4),
        }

    # Record how this run was made, next to the parquet files.
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "n_users": n_users,
        "min_orders": MIN_ORDERS,
        "train_targets": train_targets,
        "max_candidates": MAX_CANDIDATES,
        "dsp_cap": DSP_CAP,
        "splits": report,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--users", type=int, default=20_000, help="0 = all users")
    parser.add_argument(
        "--train-targets", type=int, default=1,
        help="number of last train orders used as labels",
    )
    args = parser.parse_args()

    report = prepare(args.raw_dir, args.out_dir, args.users or None, args.train_targets)
    for role, stats in report.items():
        print(role, stats)


if __name__ == "__main__":
    main()
