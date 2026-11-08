"""Dựng các nhà cung cấp mô hình ngôn ngữ từ .env: chỉ nhà cung cấp nào có khóa mới được nạp."""
from src.config.settings import Settings
from src.services.claude_service import ClaudeProvider
from src.services.gemini_service import GeminiProvider
from src.services.llm_provider import LlmProvider
from src.services.openrouter_service import OpenRouterProvider


def providers_from_settings(settings: Settings) -> dict[str, LlmProvider]:
    providers: dict[str, LlmProvider] = {}
    if settings.gemini_api_key.get_secret_value():
        providers["gemini"] = GeminiProvider(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
    if settings.anthropic_api_key.get_secret_value():
        providers["claude"] = ClaudeProvider(settings.anthropic_api_key.get_secret_value(), settings.claude_model)
    if settings.openrouter_api_key.get_secret_value():
        providers["openrouter"] = OpenRouterProvider(settings.openrouter_api_key.get_secret_value(), settings.openrouter_model)
    return providers
