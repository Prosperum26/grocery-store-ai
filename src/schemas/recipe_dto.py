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
    derived: bool = False                                      # True: nguyên liệu tự làm từ sản phẩm này (nước me từ me), không bán sẵn
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


class RecipeDetailRequest(BaseModel):
    recipe_id: str = Field(min_length=1, max_length=100)
    servings: int | None = Field(default=None, ge=1, le=50)    # bỏ trống thì lấy khẩu phần của công thức
    have: list[str] = Field(default_factory=list, max_length=50)


class RecipeDetailResponse(BaseModel):
    """Một món đầy đủ: các bước nấu (do code lấy từ công thức) và giỏ nguyên liệu nhân theo số người."""
    recipe: RecipeInfo
    servings: int
    complete: bool                                             # False: còn nguyên liệu chưa ghép được với catalog
    prep_steps: list[str]
    cooking_steps: list[str]
    basket: Basket
    not_in_basket: list[str]                                   # dòng công thức không vào giỏ (đồ ăn kèm, chưa ghép được), đúng chữ công thức
