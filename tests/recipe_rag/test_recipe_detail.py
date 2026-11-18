"""Chi tiết một món: hàm dựng (thuần) và route /recipe với RecipeService giả. Không import torch."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings, get_settings
from src.services.recipe_detail import build_recipe_detail

CATALOG = {
    "CAT-1": {"catalog_id": "CAT-1", "name": "Cá lóc vỉ 300g", "category": "Cá", "unit": None, "pack_size": 300, "pack_unit": "g"},
    "CAT-2": {"catalog_id": "CAT-2", "name": "Muối 500g", "category": "Gia vị", "unit": None, "pack_size": 500, "pack_unit": "g"},
}


def line(ingredient, raw, kind="core", status="da_ghep", catalog_id="CAT-1", quantity=500.0, unit="g"):
    match = {"catalog_id": catalog_id, "product_name": "x", "category": None, "unit": None, "packs": 1, "match_via": "bang_ghep", "alternatives": []}
    return {"ingredient": ingredient, "kind": kind, "raw_text": raw, "quantity": quantity, "unit": unit, "status": status,
            "match": match if status == "da_ghep" else None}


RECIPE = {"id": "canh-chua", "name": "Canh chua", "family": "canh chua", "servings": 4, "time_minutes": 30, "difficulty": "dễ", "description": "mô tả",
          "image_url": None, "source_url": "u", "complete": False, "prep_steps": ["Sơ chế cá"], "cooking_steps": ["Nấu canh", "Nêm vừa ăn"],
          "ingredients": [line("cá lóc", "Cá lóc: 500g"), line("muối", "Muối: 1 thìa", kind="addon", catalog_id="CAT-2", quantity=None, unit=None),
                          line("rau ăn kèm", "Rau ăn kèm", kind="side"), line("me", "Me: 40g", status="chua_ghep_duoc")]}


def test_detail_scales_the_basket_and_keeps_the_written_steps():
    detail = build_recipe_detail(RECIPE, CATALOG, 8, [], 4)
    assert detail.servings == 8 and detail.recipe.servings == 4        # recipe.servings là khẩu phần gốc của công thức
    assert detail.basket.buy[0].need.quantity == 1000 and detail.basket.buy[0].pack_hint == 4
    assert [i.ingredient for i in detail.basket.maybe_have] == ["muối"]
    assert detail.prep_steps == ["Sơ chế cá"] and detail.cooking_steps == ["Nấu canh", "Nêm vừa ăn"]
    assert detail.complete is False


def test_lines_outside_the_basket_are_listed_as_written():
    assert build_recipe_detail(RECIPE, CATALOG, None, [], 4).not_in_basket == ["Rau ăn kèm", "Me: 40g"]


def test_split_recipe_line_is_listed_once_and_missing_parts_by_name():
    """'Đường, muối, rau thơm' tách ba nguyên liệu: danh sách công thức ghi một lần; phần không vào giỏ ghi tên nguyên liệu."""
    raw = "Đường, muối, rau thơm"
    recipe = dict(RECIPE, ingredients=[line("cá lóc", "Cá lóc: 500g"), line("đường", raw, kind="addon", catalog_id="CAT-2"),
                                       line("muối", raw, kind="addon", catalog_id="CAT-2"), line("rau thơm", raw, kind="side")])
    detail = build_recipe_detail(recipe, CATALOG, None, [], 4)
    assert detail.ingredient_lines == ["Cá lóc: 500g", raw]
    assert detail.not_in_basket == ["rau thơm"]
    assert [i.ingredient for i in detail.basket.maybe_have] == ["đường, muối"]


def test_default_servings_when_not_given_and_have_moves_items_out_of_buy():
    detail = build_recipe_detail(RECIPE, CATALOG, None, ["cá lóc"], 4)
    assert detail.servings == 4 and detail.basket.buy == []
    assert detail.basket.maybe_have[0].default_qty == 0
    no_servings = dict(RECIPE, servings=None)
    assert build_recipe_detail(no_servings, CATALOG, None, [], 6).servings == 6   # công thức không ghi khẩu phần thì lấy mặc định


def test_missing_steps_become_empty_lists():
    detail = build_recipe_detail(dict(RECIPE, prep_steps=None, cooking_steps=None), CATALOG, None, [], 4)
    assert detail.prep_steps == [] and detail.cooking_steps == []


class StubRecipes:
    def __init__(self):
        self.seen = []

    def detail(self, request):
        self.seen.append(request)
        return build_recipe_detail(RECIPE, CATALOG, request.servings, request.have, 4) if request.recipe_id == "canh-chua" else None


def client(stub) -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    app.state.recipes = stub
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


KEY = {"X-Internal-Key": "k1"}


def test_route_returns_detail_and_404_for_unknown_recipe():
    stub = StubRecipes()
    c = client(stub)
    body = c.post("/api/v1/recipe", json={"recipe_id": "canh-chua", "servings": 2, "have": ["muối"]}, headers=KEY).json()
    assert body["servings"] == 2 and body["cooking_steps"] == ["Nấu canh", "Nêm vừa ăn"] and body["basket"]["buy"][0]["product"]["catalog_id"] == "CAT-1"
    assert stub.seen[0].have == ["muối"]
    assert c.post("/api/v1/recipe", json={"recipe_id": "khong-co"}, headers=KEY).status_code == 404


def test_route_needs_key_and_valid_body():
    c = client(StubRecipes())
    assert c.post("/api/v1/recipe", json={"recipe_id": "canh-chua"}).status_code == 401
    for bad in ({}, {"recipe_id": ""}, {"recipe_id": "a", "servings": 51}, {"recipe_id": "a", "have": ["x"] * 51}):
        assert c.post("/api/v1/recipe", json=bad, headers=KEY).status_code == 422
