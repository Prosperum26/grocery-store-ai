"""Map Bach Hoa Xanh categories to Instacart aisles and estimate the cost.

The catalog has no sales history, so p_reorder_ratio and a_reorder_ratio are
replaced by one rate per category: the reorder rate of its mapped aisles, on
the same never-a-label orders as training. Writes weights/category_stats.json.

Then, on Instacart val only, it measures two simulations for the report:
- proxy: item features replaced by the category rate (aisles not mapped: null).
- rules: the `not_due` shelf-life rule applied to the ranking.
Neither says how the model behaves on real Bach Hoa Xanh data.

Run:
    python -m scripts.build_category_stats
"""

import json

import polars as pl

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
)
from scripts.eval_topk import per_order_metrics
from scripts.train_lgbm import KEYS, WEIGHTS_DIR, load_split
from src.ml.onnx_inference import OnnxScorer, to_matrix
from src.services.reorder_service import CATEGORY_MAP

N_AISLES = 134


def load_mapping() -> dict:
    mapping = json.loads(CATEGORY_MAP.read_text(encoding="utf-8"))
    aisles = [a for c in mapping["categories"].values() for a in c["aisles"]]
    if len(aisles) != len(set(aisles)):
        raise ValueError("an aisle is mapped to two categories")
    if not all(1 <= a <= N_AISLES for a in aisles):
        raise ValueError("unknown aisle id")
    return mapping


def aisle_table(mapping: dict) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"aisle_id": a, "category": handle}
            for handle, c in mapping["categories"].items()
            for a in c["aisles"]
        ],
        schema={"aisle_id": pl.Int64, "category": pl.String},
    )


def score_top(val: pl.DataFrame, p, keep: pl.Expr | None = None) -> pl.DataFrame:
    df = val.with_columns(score=pl.Series(p))
    if keep is not None:
        df = df.filter(keep)
    return (
        df.select(KEYS + ["product_id", "score"])
        .sort(KEYS + ["score", "product_id"], descending=[False, False, True, False])
        .with_columns(rank=pl.col("product_id").cum_count().over(KEYS))
        .filter(pl.col("rank") <= 15)
    )


def main() -> None:
    mapping = load_mapping()
    table = aisle_table(mapping)
    meta = json.loads((WEIGHTS_DIR / "model_metadata.json").read_text(encoding="utf-8"))

    orders = sample_users(filter_users(load_orders(RAW_DIR)), meta["data"]["n_users"], SEED)
    orders = add_timeline_and_roles(orders, meta["data"]["train_targets"])
    hist = build_history(orders, load_order_products(RAW_DIR, orders["order_id"])).with_columns(
        pl.col("aisle_id").cast(pl.Int64)
    )
    known = hist.filter(~pl.col("is_target"))

    rates = known.join(table, on="aisle_id").group_by("category").agg(rate=pl.col("reordered").mean())
    stats = {r["category"]: round(r["rate"], 4) for r in rates.iter_rows(named=True)}
    covered = known.join(table, on="aisle_id").height / known.height
    path = WEIGHTS_DIR / "category_stats.json"
    path.write_text(json.dumps(dict(sorted(stats.items())), indent=2), encoding="utf-8")
    print(f"purchases in mapped aisles: {covered:.1%}")

    # Simulations on val.
    val, truth = load_split(OUT_DIR, "val")
    aisles = hist.select("product_id", "aisle_id").unique("product_id")
    shelf = pl.DataFrame(
        [{"category": k, "shelf": v["shelf_life_days"]} for k, v in mapping["categories"].items()]
    )
    val = (
        val.join(aisles, on="product_id", how="left")
        .join(table, on="aisle_id", how="left")
        .join(shelf, on="category", how="left")
    )
    targets = truth.select(KEYS).unique()
    scorer = OnnxScorer(WEIGHTS_DIR / meta["onnx"]["file"])
    cols = meta["feature_columns"]
    proxy_val = val.with_columns(
        p_reorder_ratio=pl.col("category").replace_strict(stats, default=None, return_dtype=pl.Float64)
    ).with_columns(a_reorder_ratio=pl.col("p_reorder_ratio"))
    base = scorer.predict(to_matrix(val, cols))
    proxy = scorer.predict(to_matrix(proxy_val, cols))
    not_due = (
        pl.col("up_mean_gap").is_not_null()
        & (pl.col("up_days_since") < pl.col("shelf"))
        & (pl.col("up_days_since") < mapping["not_due_ratio"] * pl.col("up_mean_gap"))
    ).fill_null(False)

    runs = {
        "model": score_top(val, base),
        "proxy": score_top(val, proxy),
        "rules": score_top(val, base, ~not_due),
    }
    results: dict = {"covered_purchases": round(covered, 4), "category_rates": stats}
    for name, preds in runs.items():
        results[name] = {}
        for k in (5, 15):
            m = per_order_metrics(preds, truth, targets, k)
            results[name][f"@{k}"] = {c: round(float(m[c].mean()), 4) for c in ("recall", "ndcg")}
    removed = val.filter(not_due)
    results["rules_removed"] = {
        "share_of_candidates": round(removed.height / val.height, 4),
        "bought_rate_of_removed": round(float(removed["label"].mean()), 4),
        "bought_rate_of_all": round(float(val["label"].mean()), 4),
    }
    print(json.dumps(results, indent=1, ensure_ascii=False))
    (OUT_DIR / "category_sim_val.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
