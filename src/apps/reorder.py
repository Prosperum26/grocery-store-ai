"""App riêng của Mua lại (cổng 8101): uvicorn src.apps.reorder:app --port 8101

Không import torch hay kết nối ai_db, nên khởi động trong vài giây và vẫn chạy khi Trợ lý Bếp gặp sự cố.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import reorder_router
from src.apps.loading import load_reorder
from src.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    load_reorder(app, get_settings())
    yield


app = FastAPI(title="grocery-store-ai: Mua lại", lifespan=lifespan)
app.include_router(reorder_router)
