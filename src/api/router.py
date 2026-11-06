"""Aggregate API router definitions."""
from fastapi import APIRouter

from src.api.v1 import health, recipes

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(recipes.router)
