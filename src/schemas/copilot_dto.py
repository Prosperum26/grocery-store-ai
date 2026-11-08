"""Kitchen copilot data-transfer schemas: lớp lời AI của /v1/copilot (docs/recipe_rag/plan-ai-copilot.md, mục 3)."""
from pydantic import BaseModel

from src.schemas.recipe_dto import SearchResponse


class ItemNote(BaseModel):
    ingredient: str          # phải là nguyên liệu có trong giỏ
    note: str                # gợi ý ngắn về lượng mua, dựa trên số liệu code đã tính


class PrepNote(BaseModel):
    ingredient: str          # phải là nguyên liệu tự làm (Item.derived = True)
    steps: list[str]         # hướng dẫn thêm, bám các bước của công thức


class AiAnswer(BaseModel):
    """Schema mô hình PHẢI trả về. Cố ý nhỏ và không có giá trị mặc định (mô hình điền đủ mọi trường, rỗng thì để [] hoặc null)."""
    recipe_id: str           # một trong các món ứng viên
    explanation: str         # vì sao hợp với câu hỏi, 2-3 câu
    item_notes: list[ItemNote]
    prep_notes: list[PrepNote]
    follow_up_question: str | None


class AiResult(AiAnswer):
    """Lớp lời đã kiểm tra, kèm nhà cung cấp tạo ra nó."""
    provider: str
    model: str


class CopilotResponse(BaseModel):
    data: SearchResponse                     # luôn có, do code dựng
    ai: AiResult | None                      # None khi lớp lời lỗi / tắt / không cần
    ai_status: str                           # ok | skipped_no_match | fallback_disabled | fallback_invalid | fallback_timeout | fallback_error
    latency_ms: int
