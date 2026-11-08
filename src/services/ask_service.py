"""Ask service: khách đang xem một món và hỏi thêm. Mô hình trả lời dựa trên công thức của món đó, có kiểm tra và dự phòng.

Không có bước tìm món hay giỏ hàng ở đây. Lỗi ở bất kỳ bước nào (tắt, hết giờ, JSON sai) chỉ làm `answer` thành None.
"""
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.config.settings import Settings
from src.schemas.ask_dto import AskAnswer, AskRequest, AskResponse
from src.services.ask_facts import SYSTEM_PROMPT, build_ask_prompt
from src.services.copilot_service import configs_from_settings
from src.services.llm_provider import LlmProvider, ProviderInvalid
from src.services.provider_chain import CallRecord, ProviderConfig, log_call, run_chain

if TYPE_CHECKING:                                   # chỉ để gõ kiểu: không nạp torch ở đây
    from src.services.recipe_service import RecipeService

MAX_ANSWER_CHARS = 1500


def check_ask_answer(answer: AskAnswer) -> AskAnswer:
    text = answer.answer.strip()
    if not text:
        raise ProviderInvalid("answer rỗng")
    if len(text) > MAX_ANSWER_CHARS:
        raise ProviderInvalid(f"answer dài quá {MAX_ANSWER_CHARS} ký tự")
    return AskAnswer(answer=text)


class AskService:
    def __init__(self, recipes: "RecipeService", providers: dict[str, LlmProvider], settings: Settings,
                 config_source: Callable[[], list[ProviderConfig]] | None = None,
                 recorder: Callable[[CallRecord], None] | None = None):
        self.recipes = recipes
        self.providers = providers
        self.settings = settings
        self.config_source = config_source or (lambda: configs_from_settings(settings))
        self.recorder = recorder or log_call

    def answer(self, request: AskRequest) -> AskResponse:
        """Ném LookupError khi không có món với id đó."""
        recipe = self.recipes.recipes.get(request.recipe_id)
        if recipe is None:
            raise LookupError(request.recipe_id)
        start = time.perf_counter()
        prompt = build_ask_prompt(recipe, request.question, request.servings)
        outcome = run_chain(self.providers, self.config_source(), SYSTEM_PROMPT, prompt, AskAnswer, check_ask_answer,
                            self.settings, start, self.recorder)
        return AskResponse(answer=outcome.answer.answer if outcome.answer else None, status=outcome.status, provider=outcome.provider,
                           model=outcome.model, latency_ms=int((time.perf_counter() - start) * 1000))
