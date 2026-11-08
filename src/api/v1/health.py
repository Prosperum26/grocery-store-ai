from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    """Không cần khóa nội bộ. Chỉ báo nhà cung cấp AI nào đã nạp (tên, không bao giờ trả khóa) và model reorder đã nạp chưa."""
    copilot = getattr(request.app.state, "copilot", None)
    return {
        "status": "ok",
        "ai_providers": sorted(copilot.providers) if copilot else [],
        "reorder_model_loaded": getattr(request.app.state, "reorder_service", None) is not None,
    }
