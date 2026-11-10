"""Kiểm khung API không cần DB / model: /health không cần khóa và chỉ lộ tên nhà cung cấp."""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router
from src.config.settings import Settings
from src.services.providers import providers_from_settings


def app_with(copilot=None) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router)
    if copilot is not None:
        app.state.copilot = copilot
    return app


def test_health_needs_no_key_and_lists_only_provider_names():
    app = app_with(SimpleNamespace(providers={"openrouter": object(), "gemini": object()}))
    body = TestClient(app).get("/api/v1/health").json()
    assert body["status"] == "ok" and body["ai_providers"] == ["gemini", "openrouter"]


def test_health_works_before_services_are_loaded():
    assert TestClient(app_with()).get("/api/v1/health").json() == {"status": "ok", "modules": {}, "ai_providers": [], "reorder_model_loaded": False}


def test_providers_are_built_only_for_keys_that_exist():
    assert providers_from_settings(Settings(gemini_api_key="", anthropic_api_key="", openrouter_api_key="")) == {}
    built = providers_from_settings(Settings(gemini_api_key="", anthropic_api_key="", openrouter_api_key="k", openrouter_model="m/x"))
    assert list(built) == ["openrouter"] and built["openrouter"].model == "m/x"
