"""Recipe routes: /search (tên món hoặc nhu cầu -> các món gần nhất kèm giỏ) và /recipe (một món đầy đủ). Không có lời AI."""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.deps import loaded
from src.api.security import require_internal_key
from src.schemas.recipe_dto import RecipeDetailRequest, RecipeDetailResponse, SearchRequest, SearchResponse

router = APIRouter(tags=["recipes"], dependencies=[Depends(require_internal_key)])


# `def` thường (không async): tìm món dùng DB và GPU kiểu đồng bộ, FastAPI sẽ chạy nó trong thread pool.
@router.post("/search", response_model=SearchResponse)
def search(body: SearchRequest, request: Request) -> SearchResponse:
    try:
        return loaded(request, "recipes").search(body)
    except psycopg.Error as e:
        # DB của AI chưa chạy: 503 để backend dùng bản dự phòng (hợp đồng ai-service.md, mục 3)
        raise HTTPException(status_code=503, detail="ai_db không sẵn sàng") from e


@router.post("/recipe", response_model=RecipeDetailResponse)
def recipe_detail(body: RecipeDetailRequest, request: Request) -> RecipeDetailResponse:
    """Một món theo id: các bước nấu và giỏ nhân theo số người. Không embedding nên nhanh, dùng khi khách đổi số người."""
    detail = loaded(request, "recipes").detail(body)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Không có món {body.recipe_id}")
    return detail
