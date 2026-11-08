"""Kiểm POST /api/v1/search bằng RecipeService giả: khóa, hình dạng JSON, kiểm đầu vào, lỗi DB."""
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings, get_settings
from src.schemas.recipe_dto import (Alternative, Basket, Item, Need, Product, RecipeInfo, SearchRequest, SearchResponse,
                                    SearchResult)

KEY = {"X-Internal-Key": "k1"}

# Dữ liệu dựng thẳng từ schema (không import test khác) để file này không kéo torch / sentence-transformers vào.
ITEM = Item(ingredient="cá lóc", kind="core", raw_text="cá lóc", derived=False, need=Need(quantity=500, unit="g", scaled_for=4),
            product=Product(catalog_id="CAT-1", name="SP cá lóc", category=None, pack_size=300, pack_unit="g"),
            default_qty=1, pack_hint=2, alternatives=[Alternative(catalog_id="CAT-2", name="x")])
DATA = SearchResponse(query="canh chua", servings=4, accepted=True, threshold=0.64, results=[SearchResult(
    recipe=RecipeInfo(id="a", name="Canh chua cá lóc", family="canh chua", servings=4, time_minutes=30, difficulty="dễ",
                      description="mô tả", image_url=None, source_url="u"),
    score=0.7, matched_by="both", complete=True, basket=Basket(buy=[ITEM], maybe_have=[]))])


class StubRecipes:
    def __init__(self, error=None):
        self.error, self.seen = error, []

    def search(self, request: SearchRequest):
        self.seen.append(request)
        if self.error:
            raise self.error
        return DATA


def client(stub) -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    app.state.recipes = stub
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


def test_search_returns_data_shape_of_the_contract():
    stub = StubRecipes()
    resp = client(stub).post("/api/v1/search", json={"query": "canh chua", "servings": 4, "have": ["muối"]}, headers=KEY)
    body = resp.json()
    assert resp.status_code == 200 and body["accepted"] is True and body["servings"] == 4
    first = body["results"][0]
    assert first["recipe"]["id"] == "a" and first["matched_by"] == "both"
    assert {"buy", "maybe_have"} <= set(first["basket"])
    assert first["basket"]["buy"][0]["product"]["catalog_id"] == "CAT-1" and first["basket"]["buy"][0]["default_qty"] == 1
    assert stub.seen[0].have == ["muối"] and stub.seen[0].top_k == 5          # top_k mặc định 5 theo hợp đồng


def test_search_requires_the_internal_key():
    c = client(StubRecipes())
    assert c.post("/api/v1/search", json={"query": "canh chua"}).status_code == 401


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "x" * 301}, {"query": "a", "top_k": 11}, {"query": "a", "servings": 0}, {}])
def test_search_rejects_bad_input_with_422(body):
    assert client(StubRecipes()).post("/api/v1/search", json=body, headers=KEY).status_code == 422


def test_database_down_is_503_not_500():
    resp = client(StubRecipes(error=psycopg.OperationalError("connection refused"))).post("/api/v1/search", json={"query": "canh chua"}, headers=KEY)
    assert resp.status_code == 503
