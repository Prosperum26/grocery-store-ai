"""Xác thực nội bộ: chỉ backend Medusa được gọi AI service, bằng header X-Internal-Key."""
import secrets

from fastapi import Depends, Header, HTTPException

from src.config.settings import Settings, get_settings


def require_internal_key(x_internal_key: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> None:
    expected = settings.ai_internal_key.get_secret_value()
    if not expected:
        # Chưa đặt khóa thì từ chối hết, không mở cửa: quên cấu hình không được thành lỗ hổng.
        raise HTTPException(status_code=503, detail="AI_INTERNAL_KEY chưa được cấu hình")
    # compare_digest so sánh trong thời gian không phụ thuộc vị trí khác nhau; encode vì nó không nhận chuỗi có dấu.
    if x_internal_key is None or not secrets.compare_digest(x_internal_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Sai hoặc thiếu X-Internal-Key")
