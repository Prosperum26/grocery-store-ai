"""Aggregate API router definitions."""
from fastapi import APIRouter

from src.api.v1 import copilot, health, recipes, reorder

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(recipes.router)
api_router.include_router(copilot.router)
api_router.include_router(reorder.router)
