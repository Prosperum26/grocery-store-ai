"""Predictive reorder service: history -> features -> scores -> rules -> list.

Tau was chosen for the top-15 list, and on val it lowers every metric at
top-5 (docs/report.md), so it is applied only when top_k equals the metadata's
top_k. Quantity is not predicted: the caller keeps its own logic for it.
"""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

from src.ml.feature_extractor import extract_features, prediction_point
from src.ml.onnx_inference import OnnxScorer, to_matrix
from src.ml.shelf_life_rules import RuleConfig, suppression_reason
from src.schemas.reorder_dto import (
    OrderLine,
    PastOrder,
    PredictedItem,
    PredictRequest,
    PredictResponse,
    SuppressedItem,
)

DSP_CAP = 30
SECONDS_PER_DAY = 86_400
# Val needs 3 past orders at least; fewer has never been evaluated.
MIN_EVALUATED_ORDERS = 3
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
USER = 1  # one customer per request; the extractor groups by user_id
CATEGORY_MAP = Path(__file__).resolve().parents[1] / "ml" / "category_map.json"

HISTORY_SCHEMA = {
    "user_id": pl.Int64,
    "order_number": pl.Int64,
    "day": pl.Float64,
    "dsp": pl.Float64,
    "dsp_capped": pl.Int8,
    "reordered": pl.Int64,
    "product_id": pl.String,
    "aisle_id": pl.String,
}


def days_between(earlier: datetime, later: datetime) -> int:
    return max(0, math.floor((later - earlier).total_seconds() / SECONDS_PER_DAY))


def build_history(orders: list[PastOrder]) -> pl.DataFrame:
    """Same timeline as data_prep: each gap capped at 30 days, then accumulated."""
    rows = []
    seen: set[str] = set()
    day = 0.0
    previous = None
    for number, order in enumerate(sorted(orders, key=lambda o: o.placed_at), start=1):
        gap = 0 if previous is None else days_between(previous, order.placed_at)
        dsp = min(gap, DSP_CAP)
        day += dsp
        # A product on two lines of one order is still one purchase.
        lines = {line.product_id: line.category for line in order.lines}
        for product_id, category in lines.items():
            rows.append(
                {
                    "user_id": USER,
                    "order_number": number,
                    "day": day,
                    "dsp": float(dsp),
                    "dsp_capped": int(previous is not None and gap >= DSP_CAP),
                    "reordered": int(product_id in seen),
                    "product_id": product_id,
                    "aisle_id": category,
                }
            )
        seen.update(lines)
        previous = order.placed_at
    return pl.DataFrame(rows, schema=HISTORY_SCHEMA)


class Scorer(Protocol):
    def predict(self, x: np.ndarray) -> np.ndarray: ...


class ReorderService:
    def __init__(
        self, scorer: Scorer, metadata: dict, category_stats: dict[str, float], rules: RuleConfig
    ) -> None:
        self.scorer = scorer
        self.metadata = metadata
        self.category_stats = category_stats
        self.rules = rules

    @classmethod
    def from_weights(cls, weights_dir: Path) -> "ReorderService":
        metadata = json.loads((weights_dir / "model_metadata.json").read_text(encoding="utf-8"))
        stats = json.loads((weights_dir / "category_stats.json").read_text(encoding="utf-8"))
        mapping = json.loads(CATEGORY_MAP.read_text(encoding="utf-8"))
        rules = RuleConfig(
            shelf_life_days={k: v["shelf_life_days"] for k, v in mapping["categories"].items()},
            min_lot_days=mapping["min_lot_days"],
            not_due_ratio=mapping["not_due_ratio"],
            not_due_enabled=mapping["not_due_enabled"],
        )
        return cls(OnnxScorer(weights_dir / metadata["onnx"]["file"]), metadata, stats, rules)

    def warm_up(self) -> None:
        """Chạy một lần dự đoán giả lúc khởi động. Lần gọi đầu của onnxruntime và polars chậm hơn hẳn các lần sau
        (cấp phát bộ nhớ, biên dịch biểu thức), nên để nó rơi vào lúc khởi động thay vì vào khách đầu tiên."""
        now = datetime.now(timezone.utc)
        orders = [
            PastOrder(placed_at=now - timedelta(days=days), lines=[OrderLine(product_id=p, category="rau-cu") for p in ("warm-a", "warm-b")])
            for days in (21, 14, 7)
        ]
        self.predict(PredictRequest(orders=orders, at=now))

    def features(self, orders: list[PastOrder], at: datetime) -> pl.DataFrame:
        """One row per candidate, built by the extractor shared with training."""
        history = build_history(orders)
        last_order = max(o.placed_at for o in orders)
        local = at.astimezone(LOCAL_TZ)
        point = prediction_point(
            history,
            dow=(local.weekday() + 1) % 7,  # Sunday = 0; Instacart does not document its coding
            hour=local.hour,
            days_since_last=days_between(last_order, at),
        )
        categories = history.group_by("product_id").agg(pl.col("aisle_id").first())
        stats = categories.with_columns(
            p_reorder_ratio=pl.col("aisle_id").replace_strict(
                self.category_stats, default=None, return_dtype=pl.Float64
            )
        ).with_columns(a_reorder_ratio=pl.col("p_reorder_ratio")).drop("aisle_id")
        return extract_features(history, point, stats, self.metadata["feature_version"]).join(
            categories, on="product_id"
        )

    def predict(self, request: PredictRequest) -> PredictResponse:
        at = request.at or datetime.now(timezone.utc)
        orders = [o for o in request.orders if o.placed_at <= at]  # nothing from the future
        model_file = self.metadata["onnx"]["file"]
        if not orders:
            return PredictResponse(
                status="empty", items=[], suppressed=[], tau_applied=None,
                low_history=True, model_file=model_file,
            )

        df = self.features(orders, at)
        scores = self.scorer.predict(to_matrix(df, self.metadata["feature_columns"]))

        tau = self.metadata["tau"] if request.top_k == self.metadata["top_k"] else None
        ranked = sorted(
            zip(df.iter_rows(named=True), scores.tolist()),
            key=lambda pair: (-pair[1], pair[0]["product_id"]),
        )
        items: list[PredictedItem] = []
        suppressed: list[SuppressedItem] = []
        for row, score in ranked:
            if len(items) == request.top_k or (tau is not None and score < tau):
                break
            expiry = request.lot_expiry.get(row["product_id"])
            rule = suppression_reason(
                row["aisle_id"],
                row["up_days_since"],
                row["up_mean_gap"],
                None if expiry is None else (expiry - at).total_seconds() / SECONDS_PER_DAY,
                self.rules,
            )
            if rule:
                suppressed.append(SuppressedItem(product_id=row["product_id"], rule=rule))
            else:
                items.append(
                    PredictedItem(product_id=row["product_id"], score=score, rank=len(items) + 1)
                )
        return PredictResponse(
            status="ready" if items else "empty",
            items=items,
            suppressed=suppressed,
            tau_applied=tau,
            low_history=len(orders) < MIN_EVALUATED_ORDERS,
            model_file=model_file,
        )
