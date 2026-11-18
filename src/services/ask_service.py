"""Ask service: khách đang xem một món và hỏi thêm. Mô hình trả lời dựa trên công thức của món đó, có kiểm tra và dự phòng.

Không có bước tìm món hay giỏ hàng ở đây. Lỗi ở bất kỳ bước nào (tắt, hết giờ, JSON sai) chỉ làm `answer` thành None.
"""
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.config.settings import Settings
from src.schemas.ask_dto import AskAnswer, AskRequest, AskResponse
from src.schemas.recipe_dto import RecipeInfo, SearchRequest
from src.services.ask_facts import SYSTEM_PROMPT, build_ask_prompt
from src.services.basket import build_basket
from src.services.copilot_service import configs_from_settings
from src.services.llm_provider import LlmProvider, ProviderInvalid
from src.services.provider_chain import CallRecord, ProviderConfig, log_call, run_chain

if TYPE_CHECKING:                                   # chỉ để gõ kiểu: không nạp torch ở đây
    from src.services.recipe_service import RecipeService

MAX_ANSWER_CHARS = 1500
MAX_QUERY_CHARS = 100          # cụm từ tìm món / sản phẩm do mô hình điền
DISH_LIMIT = 3


def check_ask_answer(answer: AskAnswer) -> AskAnswer:
    text = answer.answer.strip()
    if not text:
        raise ProviderInvalid("answer rỗng")
    if len(text) > MAX_ANSWER_CHARS:
        raise ProviderInvalid(f"answer dài quá {MAX_ANSWER_CHARS} ký tự")
    # Cụm từ tìm kiếm chỉ cần ngắn; mô hình viết dài thì cắt, không coi là lỗi.
    return AskAnswer(answer=text, find_dishes=answer.find_dishes.strip()[:MAX_QUERY_CHARS],
                     find_products=answer.find_products.strip()[:MAX_QUERY_CHARS])


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
        prompt = build_ask_prompt(recipe, request.question, request.servings, request.history,
                                  scaled=self._scaled_amounts(recipe, request.servings))
        outcome = run_chain(self.providers, self.config_source(), SYSTEM_PROMPT, prompt, AskAnswer, check_ask_answer,
                            self.settings, start, self.recorder)
        found = outcome.answer
        return AskResponse(answer=found.answer if found else None, status=outcome.status, provider=outcome.provider,
                           model=outcome.model, latency_ms=int((time.perf_counter() - start) * 1000),
                           dishes=self._dishes(found.find_dishes, request.recipe_id) if found else [],
                           product_query=(found.find_products or None) if found else None)

    def _dishes(self, query: str, current_id: str) -> list[RecipeInfo]:
        """Món cho cụm từ mô hình điền, bằng đúng phần tìm món (từ khóa + bge-m3) của trang Trợ lý Bếp. Bỏ món đang xem.
        Không có cụm từ, tìm không ra món đủ gần (accepted = False) hoặc lỗi DB thì trả rỗng: câu trả lời vẫn hiện."""
        if not query:
            return []
        try:
            found = self.recipes.search(SearchRequest(query=query, top_k=DISH_LIMIT + 1, include_basket=False))
        except Exception:                           # noqa: BLE001  (gợi ý món là phần thêm, không được làm hỏng câu trả lời)
            return []
        if not found.accepted:
            return []
        return [r.recipe for r in found.results if r.recipe.id != current_id][:DISH_LIMIT]

    def _scaled_amounts(self, recipe: dict, servings: int | None) -> list[str] | None:
        """Lượng từng nguyên liệu cho `servings` người, cùng cách tính với giỏ trên màn hình (build_basket).
        None khi khách xem đúng khẩu phần gốc, công thức không ghi khẩu phần, hoặc không có catalog."""
        own = recipe.get("servings")
        catalog = getattr(self.recipes, "catalog", None)
        if not servings or not own or servings == own or catalog is None:
            return None
        basket = build_basket(recipe["ingredients"], catalog, own, servings)
        amounts = [f"{item.ingredient}: {item.need.quantity:g}" + (f" {item.need.unit}" if item.need.unit else "")
                   for item in basket.buy + basket.maybe_have if item.need]
        return amounts or None
