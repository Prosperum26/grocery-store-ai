"""Thử /copilot ngoài HTTP: tìm món, gọi mô hình thật (nếu có khóa trong .env), in JSON kết quả.

Chạy từ thư mục grocery-store-ai (cần ai_db đang chạy và GEMINI_API_KEY / ANTHROPIC_API_KEY trong .env):
    .venv\Scripts\python scripts\recipe_rag\try_copilot.py "gà nướng mật ong cho 4 người"
    .venv\Scripts\python scripts\recipe_rag\try_copilot.py "canh chua" --providers claude        # chỉ dùng Claude
    .venv\Scripts\python scripts\recipe_rag\try_copilot.py "canh chua" --providers gemini,claude # thử cả hai theo thứ tự
    .venv\Scripts\python scripts\recipe_rag\try_copilot.py "canh chua" --prompt                  # chỉ in prompt, KHÔNG gọi mô hình

Mỗi lần chạy với nhà cung cấp thật tốn một ít tiền / hạn mức. Khóa không bao giờ được in ra.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config.settings import get_settings                     # noqa: E402
from src.ml.embedder import Embedder                              # noqa: E402
from src.schemas.recipe_dto import SearchRequest                  # noqa: E402
from src.services.claude_service import ClaudeProvider            # noqa: E402
from src.services.copilot_facts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from src.services.copilot_service import CopilotService, ProviderConfig  # noqa: E402
from src.services.gemini_service import GeminiProvider            # noqa: E402
from src.services.recipe_service import RecipeService             # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--providers", default="gemini", help="danh sách nhà cung cấp theo thứ tự ưu tiên, cách nhau bằng dấu phẩy")
    parser.add_argument("--prompt", action="store_true", help="chỉ in prompt gửi cho mô hình")
    args = parser.parse_args()

    settings = get_settings()
    recipes = RecipeService(settings, Embedder(settings.embedding_model))
    request = SearchRequest(query=args.query)
    if args.prompt:
        data = recipes.search(request)
        steps = lambda rid: " ".join([*(recipes.recipes[rid]["prep_steps"] or []), *(recipes.recipes[rid]["cooking_steps"] or [])])  # noqa: E731
        print(SYSTEM_PROMPT, "\n\n---\n")
        print(build_user_prompt(args.query, data, steps, settings.copilot_candidates))
        return

    wanted = [p.strip() for p in args.providers.split(",") if p.strip()]
    providers = {}
    if "gemini" in wanted:
        key = settings.gemini_api_key.get_secret_value()
        if not key:
            raise SystemExit("Thiếu GEMINI_API_KEY trong .env")
        providers["gemini"] = GeminiProvider(key, settings.gemini_model)
    if "claude" in wanted:
        key = settings.anthropic_api_key.get_secret_value()
        if not key:
            raise SystemExit("Thiếu ANTHROPIC_API_KEY trong .env")
        providers["claude"] = ClaudeProvider(key, settings.claude_model)
    configs = [ProviderConfig(name, True, i) for i, name in enumerate(wanted, 1) if name in providers]
    service = CopilotService(recipes, providers, settings, config_source=lambda: configs)
    print(service.answer(request).model_dump_json(indent=1))


if __name__ == "__main__":
    main()
