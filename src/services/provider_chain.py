"""Thử lần lượt các nhà cung cấp mô hình theo ưu tiên, có kiểm tra câu trả lời, thử lại một lần khi sai và dự phòng.

Dùng chung cho lớp lời của /copilot và cho /ask. Hàm không ném lỗi: kết quả luôn là một ChainOutcome,
nơi gọi tự quyết định hiển thị gì khi `answer` là None.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from src.config.settings import Settings
from src.services.llm_provider import LlmProvider, ProviderError, ProviderInvalid, ProviderTimeout
from src.utils.logger import get_logger

log = get_logger("ai")

ATTEMPTS_ON_INVALID = 2         # lần đầu + một lần thử lại kèm lý do


@dataclass
class ProviderConfig:
    name: str
    enabled: bool
    priority: int


@dataclass
class CallRecord:
    """Một lần gọi nhà cung cấp, để ghi log / thống kê (GĐ 6 sẽ ghi vào ai_call_log)."""
    provider: str
    model: str
    status: str                 # ok | invalid | timeout | error
    latency_ms: int
    tokens_in: int | None
    tokens_out: int | None


def log_call(rec: CallRecord) -> None:
    log.info("provider=%s model=%s status=%s latency_ms=%d tokens_in=%s tokens_out=%s",
             rec.provider, rec.model, rec.status, rec.latency_ms, rec.tokens_in, rec.tokens_out)


@dataclass
class ChainOutcome:
    status: str                 # ok | fallback_disabled | fallback_invalid | fallback_timeout | fallback_error
    answer: BaseModel | None = None
    provider: str | None = None
    model: str | None = None


def run_chain(providers: dict[str, LlmProvider], configs: list[ProviderConfig], system: str, user: str, output: type[BaseModel],
              check: Callable[[BaseModel], BaseModel], settings: Settings, start: float, recorder: Callable[[CallRecord], None]) -> ChainOutcome:
    """`check` kiểm câu trả lời theo dữ liệu thật và ném ProviderInvalid nếu sai. `start` là lúc request bắt đầu (cho ngân sách thời gian)."""
    usable = sorted((c for c in configs if c.enabled and c.name in providers), key=lambda c: c.priority)
    if not usable:
        return ChainOutcome("fallback_disabled")

    def record(provider: LlmProvider, status: str, t0: float) -> None:
        recorder(CallRecord(provider.name, provider.model, status, int((time.perf_counter() - t0) * 1000), None, None))

    status = "fallback_error"
    for cfg in usable:
        provider = providers[cfg.name]
        prompt = user
        for _ in range(ATTEMPTS_ON_INVALID):
            if time.perf_counter() - start > settings.ai_total_budget_s:
                return ChainOutcome("fallback_timeout")
            t0 = time.perf_counter()
            try:
                result = provider.generate(system, prompt, settings.ai_timeout_s, output)
                answer = check(result.answer)
            except ProviderTimeout:
                record(provider, "timeout", t0)
                status = "fallback_timeout"
                break                                   # không thử lại cùng nhà cung cấp sau khi hết giờ
            except ProviderInvalid as e:
                record(provider, "invalid", t0)
                status = "fallback_invalid"
                prompt = user + f"\n\nLần trước câu trả lời bị từ chối vì: {e}. Hãy trả lời lại đúng schema và đúng quy tắc."
                continue
            except ProviderError:
                record(provider, "error", t0)
                status = "fallback_error"
                break
            recorder(CallRecord(provider.name, result.model, "ok", int((time.perf_counter() - t0) * 1000), result.tokens_in, result.tokens_out))
            return ChainOutcome("ok", answer, provider.name, result.model)
    return ChainOutcome(status)
