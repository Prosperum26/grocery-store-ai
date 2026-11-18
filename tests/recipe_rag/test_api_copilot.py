"""Kiểm POST /api/v1/copilot bằng CopilotService giả (không import torch): khóa, hai dạng trả lời, lỗi DB."""
import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings, get_settings
from src.schemas.copilot_dto import AiResult, CopilotResponse, ItemNote
from src.schemas.recipe_dto import SearchRequest
from tests.recipe_rag.test_api_search import DATA

KEY = {"X-Internal-Key": "k1"}
AI = AiResult(recipe_id="a", explanation="Hợp vì đúng món canh chua.", item_notes=[ItemNote(ingredient="cá lóc", note="Nên mua 2 gói.")],
              prep_notes=[], follow_up_question=None, provider="openrouter", model="m/x")


class StubCopilot:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.seen = response, error, []

    def answer(self, request: SearchRequest):
        self.seen.append(request)
        if self.error:
            raise self.error
        return self.response


def client(stub) -> TestClient:
    app = FastAPI()
    app.include_router(api_router)
    app.state.copilot = stub
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


def test_copilot_returns_data_and_ai():
    stub = StubCopilot(CopilotResponse(data=DATA, ai=AI, ai_status="ok", latency_ms=1234))
    body = client(stub).post("/api/v1/copilot", json={"query": "canh chua", "have": ["muối"]}, headers=KEY).json()
    assert body["ai_status"] == "ok" and body["ai"]["provider"] == "openrouter" and body["ai"]["item_notes"][0]["ingredient"] == "cá lóc"
    assert body["data"]["results"][0]["recipe"]["id"] == "a" and body["latency_ms"] == 1234
    assert stub.seen[0].have == ["muối"]


def test_copilot_without_ai_still_returns_data():
    stub = StubCopilot(CopilotResponse(data=DATA, ai=None, ai_status="fallback_timeout", latency_ms=30000))
    body = client(stub).post("/api/v1/copilot", json={"query": "canh chua"}, headers=KEY).json()
    assert body["ai"] is None and body["ai_status"] == "fallback_timeout" and body["data"]["results"]


def test_copilot_requires_key_and_valid_body():
    c = client(StubCopilot(CopilotResponse(data=DATA, ai=None, ai_status="ok", latency_ms=1)))
    assert c.post("/api/v1/copilot", json={"query": "canh chua"}).status_code == 401
    assert c.post("/api/v1/copilot", json={"query": ""}, headers=KEY).status_code == 422


def test_database_down_is_503():
    stub = StubCopilot(error=psycopg.OperationalError("connection refused"))
    assert client(stub).post("/api/v1/copilot", json={"query": "canh chua"}, headers=KEY).status_code == 503
