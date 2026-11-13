"""Hai module AI nạp độc lập: một bên lỗi thì route của nó trả 503, bên kia và tiến trình vẫn chạy. Không cần torch hay DB."""
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import api_router, chef_router, reorder_router
from src.apps.loading import load_chef, load_reorder
from src.config.settings import Settings, get_settings

KEY = {"X-Internal-Key": "k1"}


def paths(router) -> set[str]:
    app = FastAPI()
    app.include_router(router)
    return set(app.openapi()["paths"])


def client(app: FastAPI) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(ai_internal_key="k1")
    return TestClient(app)


def test_each_app_serves_only_its_own_routes():
    assert paths(chef_router) == {"/api/v1/health", "/api/v1/search", "/api/v1/recipe", "/api/v1/copilot", "/api/v1/ask",
                                  "/api/v1/suggest/by-products", "/api/v1/suggest/discover"}
    assert paths(reorder_router) == {"/api/v1/health", "/api/v1/predict"}
    assert paths(api_router) == paths(chef_router) | paths(reorder_router)


def test_missing_reorder_weights_do_not_raise_and_predict_is_503(tmp_path):
    app = FastAPI()
    app.include_router(api_router)
    load_reorder(app, Settings(weights_dir=tmp_path))               # thư mục rỗng: không có model
    c = client(app)
    assert c.get("/api/v1/health").json() == {"status": "degraded", "modules": {"reorder": "failed"}, "ai_providers": [], "reorder_model_loaded": False}
    assert c.post("/api/v1/predict", json={"orders": []}, headers=KEY).status_code == 503


def test_missing_onnx_file_is_caught_too(tmp_path):
    """onnxruntime ném NoSuchFile (không phải FileNotFoundError) khi metadata có mà file .onnx thiếu."""
    (tmp_path / "model_metadata.json").write_text('{"onnx": {"file": "missing.onnx"}}', encoding="utf-8")
    (tmp_path / "category_stats.json").write_text("{}", encoding="utf-8")
    app = FastAPI()
    load_reorder(app, Settings(weights_dir=tmp_path))
    assert app.state.modules == {"reorder": "failed"} and app.state.reorder_service is None


def test_chef_failure_leaves_reorder_working(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "src.ml.embedder", None)       # giả lập torch không nạp được (import lỗi)
    app = FastAPI()
    app.include_router(api_router)
    app.state.reorder_service = object()                              # Mua lại đã nạp xong
    app.state.modules = {"reorder": "ok"}
    load_chef(app, Settings())
    c = client(app)
    body = c.get("/api/v1/health").json()
    assert body["modules"] == {"reorder": "ok", "chef": "failed"} and body["status"] == "degraded" and body["reorder_model_loaded"] is True
    for path, payload in [("/search", {"query": "canh chua"}), ("/copilot", {"query": "canh chua"}),
                          ("/recipe", {"recipe_id": "a"}), ("/ask", {"recipe_id": "a", "question": "calo?"})]:
        assert c.post("/api/v1" + path, json=payload, headers=KEY).status_code == 503, path


def test_reorder_app_does_not_import_torch():
    """App Mua lại phải khởi động được khi torch bị chặn: import nó trong tiến trình sạch và kiểm sys.modules."""
    code = "import sys; import src.apps.reorder; sys.exit(1 if 'torch' in sys.modules or 'sentence_transformers' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code], timeout=120).returncode == 0
