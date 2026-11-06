"""FastAPI application entry point."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import api_router
from src.config.settings import get_settings
from src.ml.embedder import Embedder
from src.services.copilot_service import CopilotService
from src.services.providers import providers_from_settings
from src.services.recipe_service import RecipeService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Nạp bge-m3, danh sách món và catalog một lần lúc khởi động (khoảng 10 giây), không nạp mỗi request.
    settings = get_settings()
    recipes = RecipeService(settings, Embedder(settings.embedding_model))
    app.state.recipes = recipes
    app.state.copilot = CopilotService(recipes, providers_from_settings(settings), settings)
    yield


app = FastAPI(title="grocery-store-ai", lifespan=lifespan)
app.include_router(api_router)
