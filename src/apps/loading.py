"""Nạp từng module AI lúc khởi động, độc lập với nhau.

Mỗi hàm nạp tự bắt MỌI lỗi (thiếu file model, ai_db tắt, DLL của torch bị chặn...): module lỗi được ghi là "failed",
route của nó trả 503, còn tiến trình và module kia vẫn chạy. Lý do lỗi chỉ ghi vào log, không trả ra /health.
"""
import logging

from fastapi import FastAPI

from src.config.settings import Settings

log = logging.getLogger("ai.startup")

CHEF = "chef"           # Trợ lý Bếp: tìm món, giỏ nguyên liệu, lời AI
REORDER = "reorder"     # Mua lại: dự đoán giỏ mua lại


def _mark(app: FastAPI, module: str, status: str) -> None:
    modules = getattr(app.state, "modules", None) or {}
    modules[module] = status
    app.state.modules = modules


def load_chef(app: FastAPI, settings: Settings) -> None:
    """bge-m3 + danh sách món + catalog (khoảng 10 giây). Import nằm trong hàm để app Mua lại không phải nạp torch."""
    app.state.recipes = app.state.copilot = app.state.ask = app.state.suggest = None
    try:
        from src.ml.embedder import Embedder
        from src.services.ask_service import AskService
        from src.services.copilot_service import CopilotService
        from src.services.providers import providers_from_settings
        from src.services.recipe_service import RecipeService
        from src.services.suggest_service import SuggestService

        recipes = RecipeService(settings, Embedder(settings.embedding_model))
        recipes.warm_up()
        providers = providers_from_settings(settings)
        app.state.recipes = recipes
        app.state.copilot = CopilotService(recipes, providers, settings)
        app.state.ask = AskService(recipes, providers, settings)
        app.state.suggest = SuggestService(recipes.recipes, recipes.catalog, settings.search_default_servings)
        _mark(app, CHEF, "ok")
    except Exception:                                   # noqa: BLE001  (cố ý bắt hết: xem docstring của file)
        log.exception("Trợ lý Bếp không nạp được; các route của nó sẽ trả 503")
        _mark(app, CHEF, "failed")


def load_reorder(app: FastAPI, settings: Settings) -> None:
    """Model ONNX + metadata trong weights/. Không cần torch hay ai_db."""
    app.state.reorder_service = None
    try:
        from src.services.reorder_service import ReorderService

        app.state.reorder_service = ReorderService.from_weights(settings.weights_dir)
        _mark(app, REORDER, "ok")
    except Exception:                                   # noqa: BLE001  (onnxruntime ném NoSuchFile, không phải FileNotFoundError)
        log.exception("Model Mua lại không nạp được; /predict sẽ trả 503")
        _mark(app, REORDER, "failed")
