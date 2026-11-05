"""Health-check route module."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", "reorder_model_loaded": request.app.state.reorder_service is not None}
