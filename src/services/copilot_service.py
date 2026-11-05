"""Copilot service (GĐ 4): tìm món bằng code, rồi nhờ mô hình viết lớp lời, có kiểm tra và dự phòng.

Nguyên tắc: phần `data` luôn do code dựng và luôn được trả về. Lớp lời `ai` là phần thêm; lỗi ở bất kỳ bước nào
(tắt, hết giờ, JSON sai, nội dung sai) chỉ làm `ai` thành None, không làm hỏng giỏ hàng.
"""
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.config.settings import Settings
from src.schemas.copilot_dto import AiAnswer, AiResult, CopilotResponse, ItemNote, PrepNote
from src.schemas.recipe_dto import SearchRequest, SearchResponse
from src.services.copilot_facts import SYSTEM_PROMPT, build_user_prompt, candidates_of
from src.services.llm_provider import LlmProvider, ProviderError, ProviderInvalid, ProviderTimeout
from src.services.recipe_service import RecipeService
from src.utils.logger import get_logger

log = get_logger("copilot")
MAX_EXPLANATION_CHARS = 800
MAX_PREP_STEPS = 8
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


def configs_from_settings(settings: Settings) -> list[ProviderConfig]:
    """Cấu hình bật/tắt tạm đọc từ .env; GĐ 5 thay bằng đọc bảng ai_provider_setting."""
    return [ProviderConfig("gemini", settings.ai_gemini_enabled, settings.ai_gemini_priority),
            ProviderConfig("claude", settings.ai_claude_enabled, settings.ai_claude_priority),
            ProviderConfig("openrouter", settings.ai_openrouter_enabled, settings.ai_openrouter_priority)]


def check_answer(answer: AiAnswer, data: SearchResponse, candidate_ids: list[str]) -> AiAnswer:
    """Kiểm tra lời của mô hình theo dữ liệu thật. recipe_id sai hoặc giải thích hỏng thì từ chối cả câu (ProviderInvalid);
    ghi chú nhắc tới nguyên liệu không có trong giỏ thì chỉ bỏ ghi chú đó."""
    if answer.recipe_id not in candidate_ids:
        raise ProviderInvalid(f"recipe_id '{answer.recipe_id}' không nằm trong các món ứng viên {candidate_ids}")
    explanation = answer.explanation.strip()
    if not explanation:
        raise ProviderInvalid("explanation rỗng")
    if len(explanation) > MAX_EXPLANATION_CHARS:
        raise ProviderInvalid(f"explanation dài quá {MAX_EXPLANATION_CHARS} ký tự")
    chosen = next(r for r in data.results if r.recipe.id == answer.recipe_id)
    in_basket = {i.ingredient for i in chosen.basket.buy + chosen.basket.maybe_have}
    derived = {i.ingredient for i in chosen.basket.buy + chosen.basket.maybe_have if i.derived}
    seen, notes = set(), []
    for n in answer.item_notes:
        if n.ingredient in in_basket and n.ingredient not in seen and n.note.strip():
            seen.add(n.ingredient)
            notes.append(ItemNote(ingredient=n.ingredient, note=n.note.strip()))
    preps = [PrepNote(ingredient=p.ingredient, steps=[s.strip() for s in p.steps if s.strip()][:MAX_PREP_STEPS])
             for p in answer.prep_notes if p.ingredient in derived and any(s.strip() for s in p.steps)]
    question = (answer.follow_up_question or "").strip() or None
    return AiAnswer(recipe_id=answer.recipe_id, explanation=explanation, item_notes=notes, prep_notes=preps, follow_up_question=question)


class CopilotService:
    def __init__(self, recipes: RecipeService, providers: dict[str, LlmProvider], settings: Settings,
                 config_source: Callable[[], list[ProviderConfig]] | None = None,
                 recorder: Callable[[CallRecord], None] | None = None):
        self.recipes = recipes
        self.providers = providers
        self.settings = settings
        self.config_source = config_source or (lambda: configs_from_settings(settings))
        self.recorder = recorder or self._log_record

    @staticmethod
    def _log_record(rec: CallRecord) -> None:
        log.info("provider=%s model=%s status=%s latency_ms=%d tokens_in=%s tokens_out=%s",
                 rec.provider, rec.model, rec.status, rec.latency_ms, rec.tokens_in, rec.tokens_out)

    def _steps_of(self, recipe_id: str) -> str:
        r = self.recipes.recipes[recipe_id]
        return " ".join([*(r.get("prep_steps") or []), *(r.get("cooking_steps") or [])])

    def answer(self, request: SearchRequest) -> CopilotResponse:
        start = time.perf_counter()
        data = self.recipes.search(request)

        def done(ai: AiResult | None, status: str) -> CopilotResponse:
            return CopilotResponse(data=data, ai=ai, ai_status=status, latency_ms=int((time.perf_counter() - start) * 1000))

        if not data.accepted or not data.results:
            return done(None, "skipped_no_match")          # không có món đủ gần: không nhờ mô hình nói về món không đúng ý
        configs = sorted((c for c in self.config_source() if c.enabled and c.name in self.providers), key=lambda c: c.priority)
        if not configs:
            return done(None, "fallback_disabled")

        candidates = candidates_of(data, self.settings.copilot_candidates)
        candidate_ids = [c.recipe.id for c in candidates]
        prompt = build_user_prompt(request.query, data, self._steps_of, self.settings.copilot_candidates, request.have)
        status = "fallback_error"
        for cfg in configs:
            provider = self.providers[cfg.name]
            user = prompt
            for _ in range(ATTEMPTS_ON_INVALID):
                if time.perf_counter() - start > self.settings.ai_total_budget_s:
                    return done(None, "fallback_timeout")
                t0 = time.perf_counter()
                try:
                    result = provider.generate(SYSTEM_PROMPT, user, self.settings.ai_timeout_s)
                    answer = check_answer(result.answer, data, candidate_ids)
                except ProviderTimeout:
                    self._record(provider, "timeout", t0)
                    status = "fallback_timeout"
                    break                                   # không thử lại cùng nhà cung cấp sau khi hết giờ
                except ProviderInvalid as e:
                    self._record(provider, "invalid", t0)
                    status = "fallback_invalid"
                    user = prompt + f"\n\nLần trước câu trả lời bị từ chối vì: {e}. Hãy trả lời lại đúng schema và đúng quy tắc."
                    continue
                except ProviderError:
                    self._record(provider, "error", t0)
                    status = "fallback_error"
                    break
                self.recorder(CallRecord(provider.name, result.model, "ok", int((time.perf_counter() - t0) * 1000), result.tokens_in, result.tokens_out))
                return done(AiResult(**answer.model_dump(), provider=provider.name, model=result.model), "ok")
        return done(None, status)

    def _record(self, provider: LlmProvider, status: str, t0: float) -> None:
        self.recorder(CallRecord(provider.name, provider.model, status, int((time.perf_counter() - t0) * 1000), None, None))
