from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    """Không cần khóa nội bộ. `modules` cho biết tiến trình này chạy module nào và module đó nạp được không
    ("ok" | "failed"); không trả lý do lỗi hay khóa. `status` là "degraded" khi có module nạp lỗi."""
    state = request.app.state
    modules = dict(getattr(state, "modules", None) or {})
    copilot = getattr(state, "copilot", None)
    return {
        "status": "degraded" if "failed" in modules.values() else "ok",
        "modules": modules,
        "ai_providers": sorted(copilot.providers) if copilot else [],
        "reorder_model_loaded": getattr(state, "reorder_service", None) is not None,
    }
