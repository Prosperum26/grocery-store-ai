"""Non-ML baselines on the leave-last-out splits of data_prep.

popularity    : the products bought most often overall, same for everyone.
                Counted only on orders that are never a label (~is_target),
                like product_features, so no val/test basket leaks in.
personal_freq : the products the user bought most often before the target
                order (ties -> bought more recently -> product_id).
tifuknn       : TIFU-KNN, see scripts/tifuknn.py.

Every baseline returns a ranked list (rank 1 = best) of up to TOP_N
products per target order. It is scored against the full true basket,
including products the user never bought before, so the numbers are
comparable with any later model.

Metrics (mean over target orders, an order without predictions scores 0):
    Recall@15, NDCG@15, F1@15, Precision@20
Precision@K divides by K, even when fewer than K products were predicted.

Run:
    python -m scripts.baselines --users 20000
Prints a table and writes data/processed/baselines.json.
"""

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from scripts import tifuknn as tk
from scripts.data_prep import (
    OUT_DIR,
    RAW_DIR,
    SEED,
    add_timeline_and_roles,
    build_history,
    filter_users,
    load_order_products,
    load_orders,
    sample_users,
    targets_of,
)

KEYS = ["user_id", "t_order"]
TOP_N = 20
EVAL_SPLITS = ("val", "test")
METRICS = ("recall@15", "ndcg@15", "f1@15", "precision@20")


def true_baskets(hist: pl.DataFrame, targets: pl.DataFrame) -> pl.DataFrame:
    """One row per (target order, product actually bought in it)."""
    return hist.join(
        targets.select(KEYS),
        left_on=["user_id", "order_number"],
        right_on=KEYS,
    ).select("user_id", pl.col("order_number").alias("t_order"), "product_id")


def popularity(hist: pl.DataFrame, targets: pl.DataFrame, n: int) -> pl.DataFrame:
    top = (
        hist.filter(~pl.col("is_target"))
        .group_by("product_id")
        .agg(cnt=pl.len())
        .sort(["cnt", "product_id"], descending=[True, False])
        .head(n)
        .with_row_index("rank", offset=1)
        .select("product_id", "rank")
    )
    return targets.select(KEYS).join(top, how="cross")


def personal_freq(hist: pl.DataFrame, targets: pl.DataFrame, n: int) -> pl.DataFrame:
    past = hist.join(targets.select(KEYS), on="user_id").filter(
        pl.col("order_number") < pl.col("t_order")
    )
    return (
        past.group_by(KEYS + ["product_id"])
        .agg(cnt=pl.len(), last=pl.col("order_number").max())
        .sort(
            KEYS + ["cnt", "last", "product_id"],
            descending=[False, False, True, True, False],
        )
        .with_columns(rank=pl.col("product_id").cum_count().over(KEYS))
        .filter(pl.col("rank") <= n)
        .select(KEYS + ["product_id", "rank"])
    )


def tifuknn(hist: pl.DataFrame, targets: pl.DataFrame, n: int, **params) -> pl.DataFrame:
    return tk.tifuknn(hist, targets, n, **params)


def evaluate(
    preds: pl.DataFrame, truth: pl.DataFrame, targets: pl.DataFrame
) -> dict[str, float]:
    """Recall@15, NDCG@15, F1@15 and Precision@20 from ranked predictions."""
    hits = preds.join(truth, on=KEYS + ["product_id"]).with_columns(
        gain=1 / (pl.col("rank") + 1).log(2)
    )
    per_order = targets.select(KEYS).join(
        truth.group_by(KEYS).agg(n_true=pl.len()), on=KEYS, how="left"
    )
    for k in (15, 20):
        per_order = per_order.join(
            hits.filter(pl.col("rank") <= k)
            .group_by(KEYS)
            .agg(pl.len().alias(f"hit{k}"), pl.col("gain").sum().alias(f"dcg{k}")),
            on=KEYS,
            how="left",
        )
    # Ideal DCG: all true products at the top ranks.
    idcg = [0.0]
    for i in range(1, 16):
        idcg.append(idcg[-1] + 1 / math.log2(i + 1))

    per_order = (
        per_order.fill_null(0)
        .with_columns(
            p15=pl.col("hit15") / 15,
            r15=pl.when(pl.col("n_true") > 0)
            .then(pl.col("hit15") / pl.col("n_true"))
            .otherwise(0.0),
            p20=pl.col("hit20") / 20,
            idcg15=pl.col("n_true")
            .clip(upper_bound=15)
            .replace_strict(list(range(16)), idcg, return_dtype=pl.Float64),
        )
        .with_columns(
            f15=pl.when(pl.col("p15") + pl.col("r15") > 0)
            .then(2 * pl.col("p15") * pl.col("r15") / (pl.col("p15") + pl.col("r15")))
            .otherwise(0.0),
            ndcg15=pl.when(pl.col("idcg15") > 0)
            .then(pl.col("dcg15") / pl.col("idcg15"))
            .otherwise(0.0),
        )
    )
    return {
        "recall@15": round(per_order["r15"].mean(), 4),
        "ndcg@15": round(per_order["ndcg15"].mean(), 4),
        "f1@15": round(per_order["f15"].mean(), 4),
        "precision@20": round(per_order["p20"].mean(), 4),
    }


BASELINES = {
    "popularity": popularity,
    "personal_freq": personal_freq,
    "tifuknn": tifuknn,
}


def run(
    raw_dir: Path,
    n_users: int | None,
    train_targets: int = 1,
    splits: tuple[str, ...] = EVAL_SPLITS,
    tifu_params: dict | None = None,
) -> dict:
    # Same users, roles and label orders as data_prep.prepare.
    orders = sample_users(filter_users(load_orders(raw_dir)), n_users, SEED)
    orders = add_timeline_and_roles(orders, train_targets)
    hist = build_history(orders, load_order_products(raw_dir, orders["order_id"]))

    results = {}
    for role in splits:
        targets = targets_of(orders, role)
        truth = true_baskets(hist, targets)
        results[role] = {}
        for name, fn in BASELINES.items():
            extra = {**(tifu_params or {}), "verbose": True} if name == "tifuknn" else {}
            print(f"{role}: {name}...", flush=True)
            results[role][name] = evaluate(fn(hist, targets, TOP_N, **extra), truth, targets)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--users", type=int, default=20_000, help="0 = all users")
    parser.add_argument("--train-targets", type=int, default=1)
    parser.add_argument("--group-size", type=int, default=tk.GROUP_SIZE)
    parser.add_argument("--r-b", type=float, default=tk.R_B)
    parser.add_argument("--r-g", type=float, default=tk.R_G)
    parser.add_argument("--k-neighbors", type=int, default=tk.K_NEIGHBORS)
    parser.add_argument("--alpha", type=float, default=tk.ALPHA)
    args = parser.parse_args()

    n_users = args.users or None
    tifu_params = {
        "group_size": args.group_size,
        "r_b": args.r_b,
        "r_g": args.r_g,
        "k_neighbors": args.k_neighbors,
        "alpha": args.alpha,
    }
    results = run(args.raw_dir, n_users, args.train_targets, tifu_params=tifu_params)

    print(f"{'split':<6} {'baseline':<14}" + "".join(f"{m:>14}" for m in METRICS))
    for role, by_name in results.items():
        for name, m in by_name.items():
            print(f"{role:<6} {name:<14}" + "".join(f"{m[k]:>14.4f}" for k in METRICS))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": SEED,
        "n_users": n_users,
        "train_targets": args.train_targets,
        "tifuknn": tifu_params,
        "results": results,
    }
    path = args.out_dir / "baselines.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"saved {path}")


if __name__ == "__main__":
    main()
