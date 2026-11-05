"""Predictive reorder route module."""

from fastapi import APIRouter, HTTPException, Request

from src.schemas.reorder_dto import PredictRequest, PredictResponse

router = APIRouter(tags=["reorder"])


# Plain def: the work is CPU-bound, so FastAPI runs it in its thread pool.
@router.post("/predict", response_model=PredictResponse)
def predict(body: PredictRequest, request: Request) -> PredictResponse:
    service = request.app.state.reorder_service
    if service is None:
        raise HTTPException(status_code=503, detail="reorder model is not loaded")
    return service.predict(body)
