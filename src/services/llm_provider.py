"""Giao diện chung của nhà cung cấp mô hình ngôn ngữ (Gemini, Claude). Mỗi nhà cung cấp là một lớp nhỏ có hàm generate()."""
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from src.schemas.copilot_dto import AiAnswer


class ProviderError(Exception):
    """Gọi nhà cung cấp thất bại (mạng, khóa sai, hết hạn mức, bị từ chối...). Chuyển sang nhà cung cấp kế tiếp."""


class ProviderTimeout(ProviderError):
    """Quá thời gian chờ. Không thử lại cùng nhà cung cấp (thử lại chỉ tốn thêm thời gian)."""


class ProviderInvalid(ProviderError):
    """Mô hình trả về nhưng không đúng schema hoặc sai nội dung. Được thử lại một lần kèm lý do."""


@dataclass
class ProviderResult:
    answer: BaseModel          # đúng kiểu `output` đã yêu cầu (mặc định AiAnswer)
    model: str
    tokens_in: int | None
    tokens_out: int | None


class LlmProvider(Protocol):
    name: str
    model: str

    def generate(self, system: str, user: str, timeout_s: float, output: type[BaseModel] = AiAnswer) -> ProviderResult: ...
