"""App gộp cả hai module trong một tiến trình, tiện khi dev: uvicorn src.main:app --port 8100

Mỗi module nạp độc lập (src/apps/loading.py): module nào nạp lỗi thì route của nó trả 503, module kia vẫn chạy.
Khi cần cách ly hẳn (một tiến trình chết không ảnh hưởng bên kia) thì chạy hai app riêng:
src.apps.chef:app (8100) và src.apps.reorder:app (8101).
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import api_router
from src.apps.loading import load_chef, load_reorder
from src.config.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    load_reorder(app, settings)
    load_chef(app, settings)
    yield


app = FastAPI(title="grocery-store-ai", lifespan=lifespan)
app.include_router(api_router)
