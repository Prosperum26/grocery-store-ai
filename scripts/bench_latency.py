"""CPU latency of POST /api/v1/predict, and a train/serve feature check.

Uses real val customers: their history before the val order becomes a
request. Runs in-process with one ONNX thread, so network time is excluded.

The check rebuilds features through the service and compares them with the
training parquet. p_reorder_ratio, a_reorder_ratio are skipped on purpose
(category rates at serving). Aisle ids stand in for categories, so ua_rate
must match too.

Run:
    python -m scripts.bench_latency
Writes the numbers into weights/model_metadata.json.
"""

import json
import platform
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl
from fastapi.testclient import TestClient

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
from scripts.train_lgbm import WEIGHTS_DIR, load_split, machine_info
from src.main import app
from src.schemas.reorder_dto import PredictRequest

N_REQUESTS = 500
SKIPPED = {"p_reorder_ratio", "a_reorder_ratio", "t_dow", "t_hour"}
START = datetime(2026, 1, 1, tzinfo=timezone.utc)
FEATURE_TOLERANCE = 1e-3


def requests_for(hist: pl.DataFrame, targets: pl.DataFrame) -> list[tuple[int, int, dict]]:
    """One request per target order, timestamps rebuilt from the capped timeline."""
    out = []
    by_user = hist.partition_by("user_id", as_dict=True)
    for user_id, t_order, t_day in targets.iter_rows():
        past = by_user[(user_id,)].filter(pl.col("order_number") < t_order)
        orders = []
        for group in past.sort("order_number").partition_by("order_number", maintain_order=True):
            # Minutes keep same-day orders in sequence without changing the day gaps.
            number = int(group["order_number"][0])
            placed = START + timedelta(days=int(group["day"][0]), minutes=number)
            orders.append(
                {
                    "placed_at": placed.isoformat(),
                    "lines": [
                        {"product_id": str(p), "category": str(a)}
                        for p, a in zip(group["product_id"], group["aisle_id"])
                    ],
                }
            )
        at = START + timedelta(days=int(t_day), minutes=t_order)
        out.append((user_id, t_order, {"orders": orders, "at": at.isoformat(), "top_k": 5}))
    return out


def main() -> None:
    meta_path = WEIGHTS_DIR / "model_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    orders = sample_users(filter_users(load_orders(RAW_DIR)), meta["data"]["n_users"], SEED)
    orders = add_timeline_and_roles(orders, meta["data"]["train_targets"])
    val_orders = orders.filter(pl.col("role") == "val").sort("user_id").sample(N_REQUESTS, seed=SEED)
    picked = orders.join(val_orders.select("user_id"), on="user_id")
    hist = build_history(picked, load_order_products(RAW_DIR, picked["order_id"]))
    targets = val_orders.select("user_id", pl.col("order_number").alias("t_order"), "day")
    reqs = requests_for(hist, targets)

    val, _ = load_split(OUT_DIR, "val")
    cols = [c for c in meta["feature_columns"] if c not in SKIPPED]
    worst = {c: 0.0 for c in cols}
    with TestClient(app) as client:
        service = app.state.reorder_service
        for user_id, t_order, body in reqs:
            parsed = PredictRequest.model_validate(body)
            served = service.features(parsed.orders, parsed.at).with_columns(
                pl.col("product_id").cast(pl.Int64)
            )
            truth = val.filter((pl.col("user_id") == user_id) & (pl.col("t_order") == t_order))
            both = truth.join(served, on="product_id", suffix="_s")
            for c in cols:
                d = (both[c].cast(pl.Float64) - both[f"{c}_s"].cast(pl.Float64)).abs().max()
                nulls = (both[c].is_null() != both[f"{c}_s"].is_null()).sum()
                worst[c] = max(worst[c], d or 0.0, float(nulls))
        bad = {c: v for c, v in worst.items() if v > FEATURE_TOLERANCE}
        print("train/serve feature differences above tolerance:", bad or "none")

        client.post("/api/v1/predict", json=reqs[0][2])  # warm-up, not counted
        times, sizes = [], []
        for _, _, body in reqs:
            start = time.perf_counter()
            response = client.post("/api/v1/predict", json=body)
            times.append((time.perf_counter() - start) * 1000)
            response.raise_for_status()
            sizes.append(sum(len(o["lines"]) for o in body["orders"]))

    ms = np.array(times)
    latency = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "machine": machine_info() | {"platform": platform.platform()},
        "requests": N_REQUESTS,
        "scope": "in-process POST /api/v1/predict, no network, one ONNX thread",
        "p50_ms": round(float(np.percentile(ms, 50)), 1),
        "p95_ms": round(float(np.percentile(ms, 95)), 1),
        "p99_ms": round(float(np.percentile(ms, 99)), 1),
        "max_ms": round(float(ms.max()), 1),
        "median_purchase_lines": int(np.median(sizes)),
        "max_purchase_lines": int(max(sizes)),
    }
    print(latency)
    meta["latency_cpu"] = latency
    meta["train_serve_check"] = {"requests": N_REQUESTS, "skipped": sorted(SKIPPED), "above_tolerance": bad}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
