"""Kiểm /ask không cần torch: prompt, kiểm câu trả lời, dự phòng, 404 và khóa nội bộ."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings, get_settings
from src.schemas.ask_dto import AskAnswer, AskRequest, AskResponse
from src.services.ask_facts import build_ask_prompt
from src.services.ask_service import AskService, check_ask_answer
from src.services.llm_provider import ProviderInvalid, ProviderResult, ProviderTimeout
from src.services.provider_chain import ProviderConfig

RECIPE = {"name": "Canh chua cá lóc", "family": "canh", "servings": 4, "description": "Món canh miền Tây.",
          "ingredients": [{"raw_text": "500g cá lóc"}, {"raw_text": "2 quả me"}],
          "prep_steps": ["Sơ chế cá."], "cooking_steps": ["Nấu nước me.", "Thả cá vào."]}


class StubRecipes:
    recipes = {"a": RECIPE}
    searched: list[str] = []

    def search(self, request):
        from src.schemas.recipe_dto import RecipeInfo, SearchResponse, SearchResult, Basket
        self.searched.append(request.query)
        info = lambda rid: RecipeInfo(id=rid, name=rid, family=None, servings=4, time_minutes=30, difficulty=None,
                                      description=None, image_url=None, source_url="u")
        results = [SearchResult(recipe=info(rid), score=0.8, matched_by="semantic", complete=True, basket=Basket(buy=[], maybe_have=[]))
                   for rid in ("a", "b", "c", "d", "e")]
        return SearchResponse(query=request.query, servings=4, accepted=request.query != "không ra", threshold=0.6, results=results)


class FakeProvider:
    def __init__(self, name, script):
        self.name, self.model, self.script, self.prompts = name, f"{name}-model", list(script), []

    def generate(self, system, user, timeout_s, output=AskAnswer):
        self.prompts.append(user)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ProviderResult(answer=step, model=self.model, tokens_in=1, tokens_out=1)


def service(providers, enabled=True):
    cfgs = [ProviderConfig(p.name, enabled, i) for i, p in enumerate(providers)]
    return AskService(StubRecipes(), {p.name: p for p in providers}, Settings(), config_source=lambda: cfgs, recorder=lambda r: None)


REQ = AskRequest(recipe_id="a", question="Món này khoảng bao nhiêu calo?", servings=2)


def test_prompt_contains_recipe_and_question():
    p = build_ask_prompt(RECIPE, "bớt mặn được không", 2)
    assert "Canh chua cá lóc" in p and "500g cá lóc" in p and "Thả cá vào." in p
    assert "cho 4 người" in p and "cho 2 người" in p and "<<<bớt mặn được không>>>" in p


def test_ok_answer():
    g = FakeProvider("gemini", [AskAnswer(answer="  Khoảng 300-400 kcal (ước tính).  ", find_dishes="", find_products="")])
    r = service([g]).answer(REQ)
    assert r.status == "ok" and r.answer == "Khoảng 300-400 kcal (ước tính)." and r.provider == "gemini"


def test_invalid_then_retry_with_reason():
    g = FakeProvider("gemini", [AskAnswer(answer="  ", find_dishes="", find_products=""), AskAnswer(answer="Ổn.", find_dishes="", find_products="")])
    r = service([g]).answer(REQ)
    assert r.status == "ok" and "bị từ chối" in g.prompts[1]


def test_timeout_falls_back_to_null_answer():
    r = service([FakeProvider("gemini", [ProviderTimeout("x")])]).answer(REQ)
    assert r.answer is None and r.status == "fallback_timeout"


def test_disabled_providers():
    r = service([FakeProvider("gemini", [])], enabled=False).answer(REQ)
    assert r.answer is None and r.status == "fallback_disabled"


def test_unknown_recipe_raises_lookup_error():
    with pytest.raises(LookupError):
        service([]).answer(AskRequest(recipe_id="zzz", question="hi"))


def test_check_rejects_too_long():
    with pytest.raises(ProviderInvalid):
        check_ask_answer(AskAnswer(answer="x" * 1501, find_dishes="", find_products=""))


class StubAsk:
    def __init__(self, error=None):
        self.error = error

    def answer(self, request):
        if self.error:
            raise self.error
        return AskResponse(answer="ok", status="ok", provider="p", model="m", latency_ms=1)


def client(stub) -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    app.state.ask = stub
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


def test_route_ok_404_and_validation():
    key = {"X-Internal-Key": "k1"}
    body = {"recipe_id": "a", "question": "calo?"}
    assert client(StubAsk()).post("/api/v1/ask", json=body, headers=key).json()["answer"] == "ok"
    assert client(StubAsk(LookupError("a"))).post("/api/v1/ask", json=body, headers=key).status_code == 404
    assert client(StubAsk()).post("/api/v1/ask", json=body).status_code == 401
    assert client(StubAsk()).post("/api/v1/ask", json={**body, "question": "   "}, headers=key).status_code == 422


def test_history_is_put_in_the_prompt_as_data_and_capped():
    from src.schemas.ask_dto import AskTurn
    turn = AskTurn(question="Bớt cay được không?", answer="Được, bỏ ớt ở bước 2.")
    g = FakeProvider("gemini", [AskAnswer(answer="Thay bằng tiêu.", find_dishes="", find_products="")])
    service([g]).answer(AskRequest(recipe_id="a", question="Vậy thay bằng gì?", history=[turn]))
    prompt = g.prompts[0]
    assert "<<<Bớt cay được không?>>>" in prompt and "<<<Được, bỏ ớt ở bước 2.>>>" in prompt
    assert prompt.index("Bớt cay được không?") < prompt.index("Vậy thay bằng gì?")      # lượt cũ đứng trước câu hỏi mới
    with pytest.raises(ValueError):
        AskRequest(recipe_id="a", question="q", history=[turn] * 7)


# --- Ngữ cảnh của prompt (spec R7, 2026-11-11): số bước giống màn hình, cách dùng, mẹo, lượng theo số người ---

FULL = {**RECIPE, "time_minutes": 35, "difficulty": "Dễ",
        "usage_notes": ["Dùng nóng với cơm."], "tips": ["Cho cá vào khi nước sôi để cá không tanh."]}


def test_steps_are_numbered_like_the_screen():
    # Màn hình gộp chuẩn bị rồi nấu, đánh số 1..N; prompt phải dùng đúng các số đó.
    p = build_ask_prompt(FULL, "bước 3 làm gì?", None)
    assert "Các bước (3 bước" in p
    assert "1. [chuẩn bị] Sơ chế cá." in p and "2. [nấu] Nấu nước me." in p and "3. [nấu] Thả cá vào." in p
    assert "Các bước chuẩn bị" not in p and "Các bước nấu" not in p          # không còn hai danh sách đánh số riêng


def test_notes_tips_time_and_difficulty_are_in_the_prompt():
    p = build_ask_prompt(FULL, "có mẹo gì không?", None)
    assert "thời gian khoảng 35 phút" in p and "độ khó: Dễ" in p
    assert "Cách dùng:\n- Dùng nóng với cơm." in p and "Mẹo:\n- Cho cá vào khi nước sôi" in p


def test_no_empty_sections_when_the_recipe_has_no_notes_or_steps():
    bare = {**RECIPE, "prep_steps": [], "cooking_steps": [], "usage_notes": [], "tips": [""]}
    p = build_ask_prompt(bare, "hỏi", None)
    assert "Các bước" not in p and "Cách dùng" not in p and "Mẹo" not in p and "Thông tin:" not in p


def test_long_notes_are_clipped_and_capped():
    many = {**FULL, "tips": ["x" * 1000] + [f"mẹo {i}" for i in range(10)]}
    p = build_ask_prompt(many, "hỏi", None)
    assert "x" * 300 + "..." in p and "x" * 301 not in p
    assert "mẹo 4" in p and "mẹo 5" not in p                                  # tối đa 6 dòng mẹo


class StubRecipesWithCatalog:
    catalog = {"CAT-1": {"catalog_id": "CAT-1", "name": "Cá lóc", "category": None, "pack_size": 500, "pack_unit": "g"},
               "CAT-2": {"catalog_id": "CAT-2", "name": "Me", "category": None, "pack_size": None, "pack_unit": None}}
    recipes = {"a": {**FULL, "ingredients": [
        {"ingredient": "cá lóc", "kind": "core", "raw_text": "500g cá lóc", "quantity": 500, "unit": "g", "status": "da_ghep",
         "match": {"catalog_id": "CAT-1", "alternatives": []}},
        {"ingredient": "me", "kind": "core", "raw_text": "2 quả me", "quantity": 2, "unit": "quả", "status": "da_ghep",
         "match": {"catalog_id": "CAT-2", "alternatives": []}}]}}


def ask_with_catalog(servings):
    g = FakeProvider("gemini", [AskAnswer(answer="ok", find_dishes="", find_products="")])
    AskService(StubRecipesWithCatalog(), {"gemini": g}, Settings(), config_source=lambda: [ProviderConfig("gemini", True, 0)],
               recorder=lambda r: None).answer(AskRequest(recipe_id="a", question="cần bao nhiêu cá?", servings=servings))
    return g.prompts[0]


def test_amounts_are_scaled_when_the_customer_views_other_servings():
    p = ask_with_catalog(8)
    assert "Lượng cho 8 người" in p and "- cá lóc: 1000 g" in p and "- me: 4 quả" in p


def test_no_scaled_amounts_for_the_recipe_servings():
    assert "Lượng cho" not in ask_with_catalog(4)
    assert "Lượng cho" not in ask_with_catalog(None)


def test_system_prompt_asks_for_plain_text():
    # Giao diện hiện câu trả lời nguyên văn: thẻ HTML hay ** sẽ lộ ra (gặp "<ul><li>" khi thử ngày 2026-11-13).
    from src.services.ask_facts import SYSTEM_PROMPT
    assert "không dùng thẻ HTML" in SYSTEM_PROMPT and "markdown" in SYSTEM_PROMPT


def test_dishes_are_searched_and_the_current_recipe_is_left_out():
    g = FakeProvider("gemini", [AskAnswer(answer="Gợi ý vài món bên dưới.", find_dishes="  canh rau nhẹ ", find_products="")])
    r = service([g]).answer(REQ)
    assert StubRecipes.searched[-1] == "canh rau nhẹ"
    assert [d.id for d in r.dishes] == ["b", "c", "d"] and r.product_query is None


def test_no_dishes_when_search_is_not_confident_or_not_asked():
    g = FakeProvider("gemini", [AskAnswer(answer="Ổn.", find_dishes="không ra", find_products=""),
                                AskAnswer(answer="Ổn.", find_dishes="", find_products="")])
    assert service([g]).answer(REQ).dishes == []
    assert service([g]).answer(REQ).dishes == []


def test_product_query_is_passed_to_the_storefront():
    g = FakeProvider("gemini", [AskAnswer(answer="Có kết quả bên dưới.", find_dishes="", find_products=" nước mắm ")])
    r = service([g]).answer(REQ)
    assert r.product_query == "nước mắm" and r.dishes == []


def test_prompt_rules_explain_the_two_search_fields():
    from src.services.ask_facts import SYSTEM_PROMPT
    assert "find_dishes" in SYSTEM_PROMPT and "find_products" in SYSTEM_PROMPT
