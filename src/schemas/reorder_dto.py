"""Predictive reorder data-transfer schemas."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class OrderLine(BaseModel):
    product_id: str = Field(min_length=1)
    category: str | None = None  # handle of the catalog category, e.g. "rau-cu"


class PastOrder(BaseModel):
    placed_at: AwareDatetime
    lines: list[OrderLine] = Field(min_length=1)


class PredictRequest(BaseModel):
    orders: list[PastOrder] = Field(max_length=500)
    at: AwareDatetime | None = None  # prediction time, default now
    top_k: int = Field(default=5, ge=1, le=15)
    lot_expiry: dict[str, AwareDatetime] = Field(default_factory=dict)  # product_id -> expiry


class PredictedItem(BaseModel):
    product_id: str
    score: float
    rank: int


class SuppressedItem(BaseModel):
    product_id: str
    rule: Literal["lot_expiring", "not_due"]


class PredictResponse(BaseModel):
    status: Literal["ready", "empty"]
    items: list[PredictedItem]
    suppressed: list[SuppressedItem]
    tau_applied: float | None
    low_history: bool  # fewer past orders than any customer in the evaluation
    model_file: str
