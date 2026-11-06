"""Kiểm OpenRouterProvider không cần mạng: thay httpx.stream bằng hàm giả."""
from contextlib import contextmanager

import httpx
from pydantic import BaseModel
import pytest

from src.schemas.copilot_dto import AiAnswer
from src.services import openrouter_service
from src.services.llm_provider import ProviderError, ProviderInvalid, ProviderTimeout
from src.services.openrouter_service import OpenRouterProvider

GOOD = AiAnswer(recipe_id="a", explanation="ok", item_notes=[], prep_notes=[], follow_up_question=None)


def fake_post(monkeypatch, status=200, payload=None, raises=None):
    sent = {}

    @contextmanager
    def stream(method, url, json, headers, timeout):
        sent.update(url=url, body=json, headers=headers, timeout=timeout)
        if raises:
            raise raises
        yield httpx.Response(status, json=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(openrouter_service.httpx, "stream", stream)
    return sent


def reply(content, usage=None):
    return {"choices": [{"message": {"content": content}}], "usage": usage or {"prompt_tokens": 120, "completion_tokens": 30}}


def test_ok_parses_answer_and_tokens_and_asks_for_json_schema(monkeypatch):
    sent = fake_post(monkeypatch, payload=reply(GOOD.model_dump_json()))
    result = OpenRouterProvider("k", "m/x").generate("sys", "user", 5)
    assert result.answer == GOOD and (result.tokens_in, result.tokens_out) == (120, 30)
    assert sent["body"]["response_format"]["type"] == "json_schema" and sent["body"]["provider"]["require_parameters"] is True
    assert sent["headers"]["Authorization"] == "Bearer k" and sent["timeout"] == 5


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_error_is_provider_error_without_leaking_key(monkeypatch, status):
    fake_post(monkeypatch, status=status, payload={"error": {"message": "no access"}})
    with pytest.raises(ProviderError) as e:
        OpenRouterProvider("secret-key", "m/x").generate("s", "u", 5)
    assert str(status) in str(e.value) and "secret-key" not in str(e.value) and not isinstance(e.value, (ProviderInvalid, ProviderTimeout))


def test_timeout_is_provider_timeout(monkeypatch):
    fake_post(monkeypatch, raises=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderTimeout):
        OpenRouterProvider("k", "m/x").generate("s", "u", 5)


@pytest.mark.parametrize("content", ["", None, "không phải json", '{"recipe_id": "a"}'])
def test_bad_content_is_invalid(monkeypatch, content):
    fake_post(monkeypatch, payload=reply(content))
    with pytest.raises(ProviderInvalid):
        OpenRouterProvider("k", "m/x").generate("s", "u", 5)


def test_unexpected_body_is_invalid(monkeypatch):
    fake_post(monkeypatch, payload={"oops": 1})
    with pytest.raises(ProviderInvalid):
        OpenRouterProvider("k", "m/x").generate("s", "u", 5)


class Plain(BaseModel):
    answer: str


def test_custom_output_schema_is_sent_and_parsed(monkeypatch):
    sent = fake_post(monkeypatch, payload=reply('{"answer": "Ít cay hơn thì bỏ ớt."}'))
    result = OpenRouterProvider("k", "m/x").generate("s", "u", 5, output=Plain)
    assert result.answer == Plain(answer="Ít cay hơn thì bỏ ớt.")
    assert sent["body"]["response_format"]["json_schema"]["name"] == "Plain"
    assert sent["body"]["response_format"]["json_schema"]["schema"]["properties"].keys() == {"answer"}


def test_answer_for_another_schema_is_invalid(monkeypatch):
    fake_post(monkeypatch, payload=reply(GOOD.model_dump_json()))            # JSON của AiAnswer, nhưng yêu cầu Plain
    with pytest.raises(ProviderInvalid):
        OpenRouterProvider("k", "m/x").generate("s", "u", 5, output=Plain)


def test_total_deadline_is_enforced_even_when_each_phase_is_fast(monkeypatch):
    """Từng đoạn đến kịp nhưng tổng quá hạn thì vẫn là ProviderTimeout (httpx chỉ canh từng pha)."""
    fake_post(monkeypatch, payload=reply(GOOD.model_dump_json()))
    clock = iter([0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(openrouter_service.time, "monotonic", lambda: next(clock))
    with pytest.raises(ProviderTimeout):
        OpenRouterProvider("k", "m/x").generate("s", "u", 5)
