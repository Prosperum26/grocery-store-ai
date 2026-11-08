"""Compare LightGBM with the baselines at short list sizes, on val only.

The backend shows 5 products, while the model and tau were chosen at 15.
For each K this reports Recall, Precision (hits / K), NDCG and hit rate
(at least one correct product), then the paired bootstrap 95% CI of
"LightGBM - baseline" per target order. `lightgbm` is the plain top-K;
`lightgbm_tau` also drops products with probability < tau, as serving would.

Test is deliberately not an option here.

Run:
    python -m scripts.eval_topk
Writes <data-dir>/topk_val.json.
"""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from scripts import baselines
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
from scripts.train_lgbm import KEYS, WEIGHTS_DIR, load_split, rank_top, to_matrix

KS = (5, 10, 15)
N_BOOT = 2000
METRICS = ("recall", "precision", "ndcg", "hit_rate")


def per_order_metrics(
    preds: pl.DataFrame, truth: pl.DataFrame, targets: pl.DataFrame, k: int
) -> pl.DataFrame:
    """One row per target order, sorted by KEYS. No prediction scores 0.

    preds needs KEYS, product_id, rank. Precision divides by k.
    """
    hits = (
        preds.filter(pl.col("rank") <= k)
        .join(truth, on=KEYS + ["product_id"])
        .with_columns(gain=1 / (pl.col("rank") + 1).log(2))
        .group_by(KEYS)
        .agg(hit=pl.len(), dcg=pl.col("gain").sum())
    )
    idcg = [0.0]
    for i in range(1, k + 1):
        idcg.append(idcg[-1] + 1 / math.log2(i + 1))
    return (
        targets.select(KEYS)
        .join(truth.group_by(KEYS).agg(n_true=pl.len()), on=KEYS, how="left")
        .join(hits, on=KEYS, how="left")
        .with_columns(pl.col("hit", "dcg", "n_true").fill_null(0))
        .with_columns(
            idcg=pl.col("n_true")
            .clip(upper_bound=k)
            .replace_strict(list(range(k + 1)), idcg, return_dtype=pl.Float64),
        )
        .with_columns(
            recall=pl.when(pl.col("n_true") > 0)
            .then(pl.col("hit") / pl.col("n_true"))
            .otherwise(0.0),
            precision=pl.col("hit") / k,
            ndcg=pl.when(pl.col("idcg") > 0).then(pl.col("dcg") / pl.col("idcg")).otherwise(0.0),
            hit_rate=(pl.col("hit") > 0).cast(pl.Float64),
        )
        .select(KEYS + list(METRICS))
        .sort(KEYS)
    )


def paired_bootstrap(
    a: np.ndarray, b: np.ndarray, n_boot: int = N_BOOT, seed: int = SEED
) -> dict[str, float]:
    """Mean of a - b and its percentile 95% CI, resampling target orders."""
    if len(a) != len(b):
        raise ValueError("paired bootstrap needs the same target orders on both sides")
    diff = a - b
    rng = np.random.default_rng(seed)
    means = np.array(
        [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(n_boot)]
    )
    low, high = np.percentile(means, [2.5, 97.5])
    return {
        "diff": round(float(diff.mean()), 4),
        "ci_low": round(float(low), 4),
        "ci_high": round(float(high), 4),
    }


def compare(
    runs: dict[str, pl.DataFrame], truth: pl.DataFrame, targets: pl.DataFrame, k: int
) -> dict:
    """Means per method, and each LightGBM variant minus each baseline."""
    per = {name: per_order_metrics(p, truth, targets, k) for name, p in runs.items()}
    means = {
        name: {m: round(float(df[m].mean()), 4) for m in METRICS} for name, df in per.items()
    }
    models = [n for n in runs if n.startswith("lightgbm")]
    others = [n for n in runs if not n.startswith("lightgbm")]
    diffs = {
        f"{model} - {other}": {
            m: paired_bootstrap(per[model][m].to_numpy(), per[other][m].to_numpy())
            for m in METRICS
        }
        for model in models
        for other in others
    }
    return {"means": means, "diffs": diffs}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args()

    meta = json.loads((WEIGHTS_DIR / "model_metadata.json").read_text(encoding="utf-8"))
    model = lgb.Booster(model_file=str(WEIGHTS_DIR / meta["model_file"]))
    val, truth = load_split(args.data_dir, "val")
    scored = rank_top(val, model.predict(to_matrix(val, meta["feature_columns"])), max(KS))

    orders = sample_users(filter_users(load_orders(args.raw_dir)), meta["data"]["n_users"], SEED)
    orders = add_timeline_and_roles(orders, meta["data"]["train_targets"])
    hist = build_history(orders, load_order_products(args.raw_dir, orders["order_id"]))
    targets = targets_of(orders, "val")

    runs = {
        "lightgbm": scored,
        "lightgbm_tau": scored.filter(pl.col("score") >= meta["tau"]),
        "personal_freq": baselines.personal_freq(hist, targets, max(KS)),
        "tifuknn": baselines.tifuknn(hist, targets, max(KS), verbose=True),
    }
    results = {f"@{k}": compare(runs, truth, targets, k) for k in KS}

    for label, res in results.items():
        print(f"\n{label}")
        for name, means in res["means"].items():
            print(f"  {name:<14}" + "".join(f" {m}={means[m]:.4f}" for m in METRICS))
        for name, by_metric in res["diffs"].items():
            d = by_metric["recall"]
            print(f"  {name:<30} recall {d['diff']:+.4f} [{d['ci_low']:+.4f}, {d['ci_high']:+.4f}]")

    out = args.data_dir / "topk_val.json"
    out.write_text(
        json.dumps(
            {
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "split": "val",
                "model_file": meta["model_file"],
                "tau": meta["tau"],
                "n_boot": N_BOOT,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved {out}")


if __name__ == "__main__":
    main()
