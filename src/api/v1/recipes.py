"""Recipe search route: tên món hoặc nhu cầu -> các món gần nhất kèm giỏ nguyên liệu (không có lời AI)."""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.security import require_internal_key
from src.schemas.recipe_dto import SearchRequest, SearchResponse

router = APIRouter(tags=["recipes"], dependencies=[Depends(require_internal_key)])


# `def` thường (không async): tìm món dùng DB và GPU kiểu đồng bộ, FastAPI sẽ chạy nó trong thread pool.
@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, request: Request) -> SearchResponse:
    try:
        return request.app.state.recipes.search(body)
    except psycopg.Error as e:
        # DB của AI chưa chạy: 503 để backend dùng bản dự phòng (hợp đồng ai-service.md, mục 3)
        raise HTTPException(status_code=503, detail="ai_db không sẵn sàng") from e
