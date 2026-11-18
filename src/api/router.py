"""Aggregate API router definitions.

Ba bộ route, cùng tiền tố /api/v1: của Trợ lý Bếp, của Mua lại, và bộ gộp cả hai (src/main.py).
/health có ở cả ba để backend và người vận hành kiểm tra từng tiến trình.
"""
from fastapi import APIRouter

from src.api.v1 import copilot, health, recipes, reorder, suggest

PREFIX = "/api/v1"

chef_router = APIRouter(prefix=PREFIX)
chef_router.include_router(health.router)
chef_router.include_router(recipes.router)
chef_router.include_router(copilot.router)
chef_router.include_router(suggest.router)

reorder_router = APIRouter(prefix=PREFIX)
reorder_router.include_router(health.router)
reorder_router.include_router(reorder.router)

api_router = APIRouter(prefix=PREFIX)
api_router.include_router(health.router)
api_router.include_router(recipes.router)
api_router.include_router(copilot.router)
api_router.include_router(suggest.router)
api_router.include_router(reorder.router)
