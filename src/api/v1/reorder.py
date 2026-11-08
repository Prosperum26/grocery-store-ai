"""Predictive reorder route module."""

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.security import require_internal_key

from src.schemas.reorder_dto import PredictRequest, PredictResponse

router = APIRouter(tags=["reorder"], dependencies=[Depends(require_internal_key)])


# Plain def: the work is CPU-bound, so FastAPI runs it in its thread pool.
@router.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, request: Request) -> PredictResponse:
    service = request.app.state.reorder_service
    if service is None:
        raise HTTPException(status_code=503, detail="reorder model is not loaded")
    return service.predict(body)
