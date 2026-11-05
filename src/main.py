"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import api_router
from src.config.settings import settings
from src.services.reorder_service import ReorderService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A missing model must not take the whole service down: /predict answers 503.
    try:
        app.state.reorder_service = ReorderService.from_weights(settings.weights_dir)
    except (FileNotFoundError, KeyError) as error:
        logging.getLogger(__name__).warning("reorder model not loaded: %r", error)
        app.state.reorder_service = None
    yield


app = FastAPI(title="grocery-store-ai", lifespan=lifespan)
app.include_router(api_router)
