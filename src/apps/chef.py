"""App riêng của Trợ lý Bếp (cổng 8100): uvicorn src.apps.chef:app --port 8100

Chạy tách khỏi app Mua lại để một bên sập, treo hay hết RAM không kéo bên kia theo.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import chef_router
from src.apps.loading import load_chef
from src.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_chef(app, get_settings())
    yield


app = FastAPI(title="grocery-store-ai: Trợ lý Bếp", lifespan=lifespan)
app.include_router(chef_router)
