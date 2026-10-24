"""Recipe data-transfer schemas: hợp đồng JSON của /v1/search (xem docs/recipe_rag/plan-ai-copilot.md, mục 3)."""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    servings: int | None = Field(default=None, ge=1, le=50)    # bỏ trống thì lấy từ câu hỏi ("cho 4 người")
    top_k: int = Field(default=5, ge=1, le=10)
    have: list[str] = Field(default_factory=list)              # tên nguyên liệu hoặc catalog_id khách đã có


class Need(BaseModel):
    quantity: float
    unit: str | None
    scaled_for: int                                            # số người đã nhân


class Product(BaseModel):
    catalog_id: str
    name: str
    category: str | None
    pack_size: float | None
    pack_unit: str | None


class Alternative(BaseModel):
    catalog_id: str
    name: str


class Item(BaseModel):
    ingredient: str
    kind: str                                                  # core | addon
    raw_text: str
    need: Need | None                                          # None khi công thức không ghi lượng
    product: Product
    default_qty: int                                           # 1 ở phần buy, 0 ở phần maybe_have
    pack_hint: int | None                                      # số gói gợi ý, chỉ khi lượng cần và quy cách cùng loại đơn vị
    alternatives: list[Alternative]


class Basket(BaseModel):
    buy: list[Item]
    maybe_have: list[Item]


class RecipeInfo(BaseModel):
    id: str
    name: str
    family: str | None
    servings: int
    time_minutes: int | None
    difficulty: str | None
    description: str | None
    image_url: str | None
    source_url: str


class SearchResult(BaseModel):
    recipe: RecipeInfo
    score: float                                               # cosine bge-m3 của thẻ món (0 nếu chỉ khớp từ khóa)
    matched_by: str                                            # keyword | semantic | both
    complete: bool
    basket: Basket


class SearchResponse(BaseModel):
    query: str
    servings: int
    accepted: bool                                             # False: không có món đủ gần, results là món gần nhất
    threshold: float
    results: list[SearchResult]
