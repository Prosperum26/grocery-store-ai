"""Kitchen copilot route: như /search nhưng có thêm lớp lời AI (tùy chọn). `data` luôn có, `ai` có thể là null."""
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.security import require_internal_key
from src.schemas.ask_dto import AskRequest, AskResponse
from src.schemas.copilot_dto import CopilotResponse
from src.schemas.recipe_dto import SearchRequest

router = APIRouter(tags=["copilot"], dependencies=[Depends(require_internal_key)])


# `def` thường: gọi mô hình có thể mất tới ai_total_budget_s giây, FastAPI chạy trong thread pool nên không chặn request khác.
@router.post("/copilot", response_model=CopilotResponse)
def copilot(body: SearchRequest, request: Request) -> CopilotResponse:
    try:
        return request.app.state.copilot.answer(body)
    except psycopg.Error as e:
        # Lỗi mô hình đã được CopilotService đổi thành ai=null + ai_status; chỉ lỗi DB mới tới đây.
        raise HTTPException(status_code=503, detail="ai_db không sẵn sàng") from e


# Khách bấm nút hỏi thêm về món đang xem. Mô hình lỗi thì `answer` = null + status, chỉ món không tồn tại mới là 404.
@router.post("/ask", response_model=AskResponse)
def ask(body: AskRequest, request: Request) -> AskResponse:
    try:
        return request.app.state.ask.answer(body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail="Không có món với recipe_id này") from e
