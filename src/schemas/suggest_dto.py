"""Hợp đồng JSON của /v1/suggest/* (gợi ý món ở storefront: spec recipe-suggestions, mục 3)."""
from typing import Literal

from pydantic import BaseModel, Field

from src.schemas.recipe_dto import Basket, RecipeInfo


class ByProductsRequest(BaseModel):
    catalog_ids: list[str] = Field(min_length=1, max_length=30)
    mode: Literal["cart", "product"]                         # cart: B (giỏ hàng), product: C (một sản phẩm)
    limit: int = Field(default=9, ge=1, le=12)
    have: list[str] = Field(default_factory=list)            # SKU khách đã có, để giỏ chỉ còn phần thiếu
    exclude_ids: list[str] = Field(default_factory=list)


class DiscoverRequest(BaseModel):
    bought_catalog_ids: list[str] = Field(default_factory=list, max_length=500)    # SKU trong các đơn đã giao
    have: list[str] = Field(default_factory=list)
    seed: str = Field(min_length=1, max_length=100)          # khách + ngày: cùng khách cùng ngày thấy cùng món
    limit: int = Field(default=10, ge=1, le=12)
    exclude_ids: list[str] = Field(default_factory=list)


class Matched(BaseModel):
    catalog_id: str
    name: str                                                # tên nguyên liệu trong công thức ("cá lóc"), không phải tên có quy cách


class Suggestion(BaseModel):
    recipe: RecipeInfo
    matched: list[Matched]                                   # chỉ ở by-products
    new_count: int | None = None                             # chỉ ở discover
    familiar_count: int | None = None
    missing_count: int                                       # số dòng còn phải mua = len(basket.buy)
    basket: Basket


class SuggestResponse(BaseModel):
    suggestions: list[Suggestion]
