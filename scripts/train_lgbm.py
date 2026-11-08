"""Train LightGBM on the candidate rows of data_prep and score the ranking.

- objective = binary, early stopping on val logloss, no scale_pos_weight.
- Features: FEATURE_SETS[version] from src/ml/feature_extractor.py.
- Each candidate gets a probability; the top 20 per target order are
  scored like the baselines (Recall@15, NDCG@15, F1@15, Precision@20)
  against the full true basket, new products included.
- Test is NOT scored unless --eval-test is given. Choose models on val.

Every run appends one JSON line to <data-dir>/lgbm_runs.jsonl.

Run:
    python -m scripts.train_lgbm --versions v0,v1,v2,v3,v4     # ablation
    python -m scripts.train_lgbm --versions v4 --num-leaves 127 --tag leaves127
    python -m scripts.train_lgbm --versions v4 --inspect 5     # importance + 5 users
"""

import argparse
import json
import os
import platform
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from scripts.baselines import METRICS, evaluate
from scripts.data_prep import OUT_DIR, RAW_DIR, SEED, load_order_products
from src.ml.feature_extractor import FEATURE_SETS

KEYS = ["user_id", "t_order"]
TOP_N = 20
WEIGHTS_DIR = Path("weights")


def load_split(data_dir: Path, role: str) -> tuple[pl.DataFrame, pl.DataFrame]:
    return (
        pl.read_parquet(data_dir / f"{role}.parquet"),
        pl.read_parquet(data_dir / f"{role}_truth.parquet"),
    )


def to_matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    """float32 matrix, nulls as NaN (LightGBM's missing value)."""
    return df.select(pl.col(cols).cast(pl.Float32)).to_numpy()


def rank_top(df: pl.DataFrame, score: np.ndarray, n: int = TOP_N) -> pl.DataFrame:
    """Top-n products per target order by score (ties -> smaller product_id)."""
    return (
        df.select(KEYS + ["product_id"])
        .with_columns(score=pl.Series(score))
        .sort(KEYS + ["score", "product_id"], descending=[False, False, True, False])
        .with_columns(rank=pl.col("product_id").cum_count().over(KEYS))
        .filter(pl.col("rank") <= n)
    )


def score_split(model: lgb.Booster, df: pl.DataFrame, truth: pl.DataFrame, cols: list[str]) -> dict:
    preds = rank_top(df, model.predict(to_matrix(df, cols)))
    targets = truth.select(KEYS).unique()
    return evaluate(preds, truth, targets)


def train(
    train_df: pl.DataFrame,
    val_df: pl.DataFrame,
    cols: list[str],
    params: dict,
    rounds: int,
    early_stop: int,
) -> lgb.Booster:
    dtrain = lgb.Dataset(to_matrix(train_df, cols), train_df["label"].to_numpy(), feature_name=cols)
    dval = lgb.Dataset(to_matrix(val_df, cols), val_df["label"].to_numpy(), reference=dtrain)
    return lgb.train(
        params,
        dtrain,
        num_boost_round=rounds,
        valid_sets=[dval],
        valid_names=["val"],
        callbacks=[lgb.early_stopping(early_stop, verbose=False), lgb.log_evaluation(100)],
    )


def machine_info() -> dict:
    """Where a run happened, so numbers can be traced back to a machine."""
    return {
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "n_cpu": os.cpu_count(),
        "python": platform.python_version(),
        "lightgbm": lgb.__version__,
    }


def importance(model: lgb.Booster) -> list[tuple[str, float]]:
    gain = model.feature_importance("gain")
    total = gain.sum() or 1.0
    pairs = sorted(zip(model.feature_name(), gain / total), key=lambda p: -p[1])
    return [(name, round(float(share), 4)) for name, share in pairs]


def inspect_users(
    model: lgb.Booster, val_df: pl.DataFrame, truth: pl.DataFrame, cols: list[str],
    n_users: int, raw_dir: Path,
) -> str:
    """Markdown: top-15 of a few val users next to their purchase history."""
    names = pl.read_csv(raw_dir / "products.csv").select("product_id", "product_name")
    users = val_df.select(KEYS).unique().sort(KEYS).sample(n_users, seed=SEED)
    df = val_df.join(users, on=KEYS)
    top = rank_top(df, model.predict(to_matrix(df, cols)), 15).join(
        df.select(KEYS + ["product_id", "label", "up_cnt", "up_orders_since", "u_n_orders"]),
        on=KEYS + ["product_id"],
    ).join(names, on="product_id", how="left")

    orders = pl.read_csv(raw_dir / "orders.csv").join(users.select("user_id"), on="user_id")
    hist = load_order_products(raw_dir, orders["order_id"]).join(
        orders.select("order_id", "user_id", "order_number"), on="order_id"
    ).join(names, on="product_id", how="left")

    out = []
    for user_id, t_order in users.iter_rows():
        past = hist.filter((pl.col("user_id") == user_id) & (pl.col("order_number") < t_order))
        bought = truth.filter((pl.col("user_id") == user_id) & (pl.col("t_order") == t_order)).join(
            names, on="product_id", how="left"
        )
        out.append(f"## user {user_id}, dự đoán đơn {t_order} ({t_order - 1} đơn trước)\n")
        out.append("**Top-15 của model** (✅ = có trong giỏ thật)\n")
        out.append("| # | Sản phẩm | Điểm | Đã mua (lần / đơn) | Số đơn từ lần cuối | |")
        out.append("| --- | --- | --- | --- | --- | --- |")
        for r in top.filter((pl.col("user_id") == user_id) & (pl.col("t_order") == t_order)).sort("rank").iter_rows(named=True):
            out.append(
                f"| {r['rank']} | {r['product_name']} | {r['score']:.3f} | {r['up_cnt']} / {r['u_n_orders']}"
                f" | {r['up_orders_since']} | {'✅' if r['label'] else ''} |"
            )
        freq = past.group_by("product_name").agg(n=pl.len(), last=pl.col("order_number").max()).sort(
            ["n", "last"], descending=True
        ).head(15)
        out.append("\n**Lịch sử: 15 món mua nhiều nhất**\n")
        out.append(", ".join(f"{r[0]} ({r[1]}×, đơn cuối {r[2]})" for r in freq.iter_rows()))
        last = past.filter(pl.col("order_number") == past["order_number"].max())["product_name"].to_list()
        out.append(f"\n**Đơn gần nhất**: {', '.join(last)}")
        out.append(f"\n**Giỏ thật của đơn {t_order}**: {', '.join(bought['product_name'].to_list())}\n")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--versions", default="v4", help="comma separated, e.g. v0,v1,v2")
    parser.add_argument("--tag", default="", help="free text saved with the run")
    parser.add_argument("--num-leaves", type=int, default=63)
    parser.add_argument("--min-data-in-leaf", type=int, default=100)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--feature-fraction", type=float, default=0.9)
    parser.add_argument("--rounds", type=int, default=2000)
    parser.add_argument("--early-stop", type=int, default=50)
    parser.add_argument("--inspect", type=int, default=0, help="number of val users to print")
    parser.add_argument("--save-model", action="store_true", help=f"save to {WEIGHTS_DIR}/")
    parser.add_argument("--eval-test", action="store_true", help="also score test (final model only)")
    args = parser.parse_args()

    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "learning_rate": args.learning_rate,
        "num_leaves": args.num_leaves,
        "min_data_in_leaf": args.min_data_in_leaf,
        "feature_fraction": args.feature_fraction,
        "bagging_fraction": 0.9,
        "bagging_freq": 1,
        "seed": SEED,
        "deterministic": True,
        "force_row_wise": True,
        "verbose": -1,
    }
    train_df, _ = load_split(args.data_dir, "train")
    val_df, val_truth = load_split(args.data_dir, "val")
    meta_path = args.data_dir / "meta.json"
    data_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    print(f"{'version':<8} {'iters':>6} {'val_logloss':>12}" + "".join(f"{m:>14}" for m in METRICS))
    for version in args.versions.split(","):
        cols = FEATURE_SETS[version]
        model = train(train_df, val_df, cols, params, args.rounds, args.early_stop)
        val_m = score_split(model, val_df, val_truth, cols)
        logloss = round(model.best_score["val"]["binary_logloss"], 5)
        print(f"{version:<8} {model.best_iteration:>6} {logloss:>12}"
              + "".join(f"{val_m[m]:>14.4f}" for m in METRICS), flush=True)

        run = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "tag": args.tag,
            "version": version,
            "data": {k: data_meta.get(k) for k in ("n_users", "train_targets", "seed")},
            "params": params,
            "machine": machine_info(),
            "best_iteration": model.best_iteration,
            "val_logloss": logloss,
            "val": val_m,
            "importance_gain": importance(model),
        }
        if args.eval_test:
            test_df, test_truth = load_split(args.data_dir, "test")
            run["test"] = score_split(model, test_df, test_truth, cols)
            print("test    " + "".join(f"{run['test'][m]:>14.4f}" for m in METRICS))
        with open(args.data_dir / "lgbm_runs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(run, ensure_ascii=False) + "\n")

        if args.save_model:
            WEIGHTS_DIR.mkdir(exist_ok=True)
            name = f"lgbm_{version}{'_' + args.tag if args.tag else ''}.txt"
            model.save_model(WEIGHTS_DIR / name, num_iteration=model.best_iteration)
        if args.inspect:
            print("\nfeature importance (gain share):")
            for name, share in run["importance_gain"]:
                print(f"  {name:<18} {share:.4f}")
            report = inspect_users(model, val_df, val_truth, cols, args.inspect, args.raw_dir)
            path = args.data_dir / f"inspect_{version}{'_' + args.tag if args.tag else ''}.md"
            path.write_text(report, encoding="utf-8")
            print(f"saved {path}")


if __name__ == "__main__":
    main()
