"""FastAPI application entry point."""
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import api_router
from src.config.settings import get_settings
from src.ml.embedder import Embedder
from src.services.ask_service import AskService
from src.services.copilot_service import CopilotService
from src.services.providers import providers_from_settings
from src.services.recipe_service import RecipeService
from src.services.reorder_service import ReorderService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Nạp bge-m3, danh sách món và catalog một lần lúc khởi động (khoảng 10 giây), không nạp mỗi request.
    settings = get_settings()
    recipes = RecipeService(settings, Embedder(settings.embedding_model))
    app.state.recipes = recipes
    providers = providers_from_settings(settings)
    app.state.copilot = CopilotService(recipes, providers, settings)
    app.state.ask = AskService(recipes, providers, settings)
    # Thiếu model reorder không được làm sập cả service: /predict trả 503.
    try:
        app.state.reorder_service = ReorderService.from_weights(settings.weights_dir)
    except (FileNotFoundError, KeyError) as error:
        logging.getLogger(__name__).warning("reorder model not loaded: %r", error)
        app.state.reorder_service = None
    yield


app = FastAPI(title="grocery-store-ai", lifespan=lifespan)
app.include_router(api_router)
