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
    g = FakeProvider("gemini", [AskAnswer(answer="  Khoảng 300-400 kcal (ước tính).  ")])
    r = service([g]).answer(REQ)
    assert r.status == "ok" and r.answer == "Khoảng 300-400 kcal (ước tính)." and r.provider == "gemini"


def test_invalid_then_retry_with_reason():
    g = FakeProvider("gemini", [AskAnswer(answer="  "), AskAnswer(answer="Ổn.")])
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
        check_ask_answer(AskAnswer(answer="x" * 1501))


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
