"""Gợi ý món cho storefront: /suggest/by-products (giỏ hàng, trang sản phẩm) và /suggest/discover (thử món mới).
Chỉ luật trên dữ liệu trong bộ nhớ, không DB, không mô hình ngôn ngữ nên không có lỗi 503 ngoài "chưa nạp"."""
from fastapi import APIRouter, Depends, Request

from src.api.deps import loaded
from src.api.security import require_internal_key
from src.schemas.suggest_dto import ByProductsRequest, DiscoverRequest, SuggestResponse

router = APIRouter(prefix="/suggest", tags=["suggest"], dependencies=[Depends(require_internal_key)])


@router.post("/by-products", response_model=SuggestResponse)
def by_products(body: ByProductsRequest, request: Request) -> SuggestResponse:
    service = loaded(request, "suggest")
    return SuggestResponse(suggestions=service.by_products(body.catalog_ids, body.mode, body.limit, body.have, body.exclude_ids))


@router.post("/discover", response_model=SuggestResponse)
def discover(body: DiscoverRequest, request: Request) -> SuggestResponse:
    service = loaded(request, "suggest")
    return SuggestResponse(suggestions=service.discover(body.bought_catalog_ids, body.have, body.seed, body.limit, body.exclude_ids))
