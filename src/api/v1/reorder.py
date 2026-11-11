"""Predictive reorder route module."""

from fastapi import APIRouter, Depends, Request

from src.api.deps import loaded
from src.api.security import require_internal_key

from src.schemas.reorder_dto import PredictRequest, PredictResponse

router = APIRouter(tags=["reorder"], dependencies=[Depends(require_internal_key)])


# Plain def: the work is CPU-bound, so FastAPI runs it in its thread pool.
@router.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, request: Request) -> PredictResponse:
    return loaded(request, "reorder_service").predict(body)
