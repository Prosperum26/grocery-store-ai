"""Ask data-transfer schemas: hỏi thêm về một món đang xem (POST /api/v1/ask)."""
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from src.schemas.recipe_dto import RecipeInfo


class AskTurn(BaseModel):
    """Một lượt hỏi đáp trước đó, do storefront gửi lại (service không lưu hội thoại)."""
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=1500)


class AskRequest(BaseModel):
    recipe_id: str = Field(min_length=1, max_length=100)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    servings: int | None = Field(default=None, ge=1, le=50)    # số người khách đang xem; bỏ trống thì lấy khẩu phần của công thức
    history: list[AskTurn] = Field(default_factory=list, max_length=6)   # các lượt trước, cũ trước mới sau, để hỏi nối tiếp ("vậy thay bằng gì?")


class AskAnswer(BaseModel):
    """Schema gửi cho mô hình. Hai trường tìm kiếm là chuỗi rỗng khi không cần: chế độ JSON nghiêm ngặt của OpenRouter
    bắt mọi trường phải có mặt, nên không dùng null hay giá trị mặc định."""
    answer: str
    find_dishes: str            # cụm từ tìm món khi khách muốn gợi ý món khác ("canh chua nhẹ"), không thì ""
    find_products: str          # tên sản phẩm khi khách muốn tìm hoặc mua ("nước mắm"), không thì ""


class AskResponse(BaseModel):
    answer: str | None                                         # None khi mô hình tắt / lỗi / quá giờ: giao diện báo "chưa trả lời được"
    status: str                                                # ok | fallback_disabled | fallback_invalid | fallback_timeout | fallback_error
    provider: str | None
    model: str | None
    latency_ms: int
    dishes: list[RecipeInfo] = Field(default_factory=list)    # món tìm được cho find_dishes (tìm món RAG có sẵn), tối đa 3
    product_query: str | None = None                          # find_products: storefront tự tìm sản phẩm bằng ô tìm kiếm
