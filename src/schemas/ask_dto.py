"""Ask data-transfer schemas: hỏi thêm về một món đang xem (POST /api/v1/ask)."""
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class AskRequest(BaseModel):
    recipe_id: str = Field(min_length=1, max_length=100)
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    servings: int | None = Field(default=None, ge=1, le=50)    # số người khách đang xem; bỏ trống thì lấy khẩu phần của công thức


class AskAnswer(BaseModel):
    """Schema gửi cho mô hình: chỉ một đoạn văn trả lời."""
    answer: str


class AskResponse(BaseModel):
    answer: str | None                                         # None khi mô hình tắt / lỗi / quá giờ: giao diện báo "chưa trả lời được"
    status: str                                                # ok | fallback_disabled | fallback_invalid | fallback_timeout | fallback_error
    provider: str | None
    model: str | None
    latency_ms: int
