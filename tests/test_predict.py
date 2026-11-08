from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings, get_settings
from src.ml.feature_extractor import FEATURE_SETS
from src.ml.shelf_life_rules import RuleConfig, suppression_reason
from src.schemas.reorder_dto import PredictRequest
from src.services.reorder_service import ReorderService, build_history

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
RULES = RuleConfig(
    shelf_life_days={"gao": 180, "thit": 3}, min_lot_days=2, not_due_ratio=0.5, not_due_enabled=True
)
COLS = FEATURE_SETS["v4"]
META = {
    "feature_columns": COLS,
    "feature_version": "v4",
    "tau": 0.5,
    "top_k": 15,
    "onnx": {"file": "stub.onnx"},
}


class StubScorer:
    """Score = up_cnt / 100, so products bought more often rank first."""

    def predict(self, x: np.ndarray) -> np.ndarray:
        return x[:, COLS.index("up_cnt")] / 100


def service(scorer=None) -> ReorderService:
    return ReorderService(scorer or StubScorer(), META, {"gao": 0.6}, RULES)


def order(day: int, *products: tuple[str, str]) -> dict:
    return {
        "placed_at": (START + timedelta(days=day)).isoformat(),
        "lines": [{"product_id": p, "category": c} for p, c in products],
    }


def request(orders, at_day, **kw) -> PredictRequest:
    return PredictRequest(orders=orders, at=START + timedelta(days=at_day), **kw)


def test_history_caps_gaps_counts_duplicates_once_and_marks_reorders():
    h = build_history(
        request([order(0, ("a", "gao"), ("a", "gao")), order(100, ("a", "gao"))], 101).orders
    ).sort("order_number")
    assert h.height == 2  # two lines of "a" in one order are one purchase
    assert h["day"].to_list() == [0.0, 30.0]
    assert h["dsp_capped"].to_list() == [0, 1]
    assert h["reordered"].to_list() == [0, 1]


def test_days_after_the_cap_do_not_grow_up_days_since():
    orders = request([order(0, ("a", "gao"))], 1000).orders
    f = service().features(orders, START + timedelta(days=1000))
    assert f["t_dsp"][0] == 30.0
    assert f["up_days_since"][0] == 30.0  # as in training, where gaps are capped


def test_orders_after_prediction_time_are_ignored():
    r = service().predict(request([order(0, ("a", "gao")), order(50, ("b", "gao"))], 10))
    assert [i.product_id for i in r.items] == ["a"]


def test_empty_history():
    r = service().predict(request([], 1))
    assert r.status == "empty" and r.items == [] and r.low_history


def test_top_k_ranking_and_low_history_flag():
    orders = [order(0, ("a", "gao"), ("b", "gao")), order(40, ("a", "gao"))]
    r = service().predict(request(orders, 80, top_k=1))
    assert [(i.product_id, i.rank) for i in r.items] == [("a", 1)]
    assert r.low_history


def test_tau_only_applies_at_the_top_k_it_was_chosen_for():
    orders = [order(0, ("a", "gao"))]
    assert service().predict(request(orders, 90, top_k=5)).items
    r = service().predict(request(orders, 90, top_k=15))
    assert r.tau_applied == 0.5 and r.items == []


def test_not_due_is_replaced_by_the_next_product():
    # "a" is bought every 20 days, last 2 days ago, so it is not due. "c" takes the slot.
    orders = [order(0, ("a", "gao")), order(20, ("a", "gao")), order(25, ("c", None))]
    r = service().predict(request(orders, 22, top_k=1))
    assert [i.product_id for i in r.suppressed] == ["a"]
    assert r.suppressed[0].rule == "not_due"


def test_lot_expiring_removes_a_product():
    orders = [order(0, ("a", "gao")), order(1, ("b", "gao"))]
    at = START + timedelta(days=60)
    r = service().predict(
        PredictRequest(orders=orders, at=at, lot_expiry={"a": at + timedelta(days=1)})
    )
    assert {s.product_id: s.rule for s in r.suppressed} == {"a": "lot_expiring"}
    assert [i.product_id for i in r.items] == ["b"]


@pytest.mark.parametrize(
    "category, since, gap, lot, expected",
    [
        ("gao", 5, 30, None, "not_due"),
        ("gao", 20, 30, None, None),      # past half of the gap
        ("thit", 5, 30, None, None),      # meat bought 5 days ago is past its shelf life
        ("gao", 5, None, None, None),     # bought once, no gap
        (None, 5, 30, None, None),        # unknown category
        ("gao", 20, 30, 1.0, "lot_expiring"),
        ("gao", 20, 30, 2.0, None),
    ],
)
def test_rules(category, since, gap, lot, expected):
    assert suppression_reason(category, since, gap, lot, RULES) == expected


def test_not_due_is_off_unless_enabled():
    off = RuleConfig(shelf_life_days={"gao": 180}, min_lot_days=2, not_due_ratio=0.5)
    assert suppression_reason("gao", 5, 30, None, off) is None


KEY = {"X-Internal-Key": "k1"}


def client(reorder_service) -> TestClient:
    """App riêng chỉ có router, không chạy lifespan thật (không nạp bge-m3 hay ai_db)."""
    app = FastAPI()
    app.include_router(api_router)
    app.state.reorder_service = reorder_service
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


def test_route_returns_503_without_a_model_and_422_on_naive_dates():
    c = client(None)
    assert c.get("/api/v1/health").json()["reorder_model_loaded"] is False
    assert c.post("/api/v1/predict", json={"orders": []}, headers=KEY).status_code == 503
    bad = {"orders": [{"placed_at": "2026-01-01T00:00:00", "lines": [{"product_id": "a"}]}]}
    assert c.post("/api/v1/predict", json=bad, headers=KEY).status_code == 422


def test_route_requires_internal_key():
    assert client(service()).post("/api/v1/predict", json={"orders": []}).status_code == 401


def test_route_predicts():
    body = {"orders": [order(0, ("a", "gao"))], "at": (START + timedelta(days=9)).isoformat()}
    r = client(service()).post("/api/v1/predict", json=body, headers=KEY)
    assert r.status_code == 200
    assert r.json()["items"][0]["product_id"] == "a"
