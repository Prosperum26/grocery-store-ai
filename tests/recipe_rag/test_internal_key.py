"""Kiểm khóa nội bộ bằng một app nhỏ, không cần DB hay model."""
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.api.security import require_internal_key
from src.config.settings import Settings, get_settings


def client(key: str) -> TestClient:
    app = FastAPI()

    @app.get("/secret", dependencies=[Depends(require_internal_key)])
    def secret():
        return {"ok": True}

    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key=key)
    return TestClient(app)


def test_right_key_passes():
    assert client("k1").get("/secret", headers={"X-Internal-Key": "k1"}).json() == {"ok": True}


def test_missing_or_wrong_key_is_401():
    c = client("k1")
    assert c.get("/secret").status_code == 401
    assert c.get("/secret", headers={"X-Internal-Key": "nope"}).status_code == 401
    assert c.get("/secret", headers={"X-Internal-Key": b"kh\xf3a"}).status_code == 401      # byte ngoài ASCII không làm sập server


def test_unconfigured_key_rejects_everything_with_503():
    c = client("")
    assert c.get("/secret").status_code == 503
    assert c.get("/secret", headers={"X-Internal-Key": ""}).status_code == 503
