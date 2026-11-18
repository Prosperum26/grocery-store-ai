"""Lấy service đã nạp từ app.state; chưa nạp (module lỗi lúc khởi động) thì 503 thay vì lỗi 500 khó hiểu."""
from fastapi import HTTPException, Request


def loaded(request: Request, name: str):
    service = getattr(request.app.state, name, None)
    if service is None:
        raise HTTPException(status_code=503, detail=f"module '{name}' chưa sẵn sàng")
    return service
