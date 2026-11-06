"""Gemini provider: gọi Gemini Developer API, ép trả JSON đúng schema AiAnswer."""
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from src.schemas.copilot_dto import AiAnswer
from src.services.llm_provider import ProviderError, ProviderInvalid, ProviderResult, ProviderTimeout


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.model = model
        self._client = genai.Client(api_key=api_key)

    def generate(self, system: str, user: str, timeout_s: float, output: type[BaseModel] = AiAnswer) -> ProviderResult:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=output,                                     # SDK lấy JSON schema từ model Pydantic
            http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),  # SDK tính timeout bằng mili giây
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=user, config=config)
        except errors.APIError as e:
            raise ProviderError(f"Gemini API {e.code}") from e
        except Exception as e:                                          # lỗi mạng / hết giờ của httpx
            if "timeout" in type(e).__name__.lower():
                raise ProviderTimeout("Gemini hết thời gian chờ") from e
            raise ProviderError(f"Gemini {type(e).__name__}") from e
        if not response.text:
            raise ProviderInvalid("Gemini trả về rỗng")
        try:
            answer = output.model_validate_json(response.text)          # tự kiểm tra, không tin response.parsed
        except ValidationError as e:
            raise ProviderInvalid(f"JSON không đúng schema: {e.error_count()} lỗi") from e
        usage = response.usage_metadata
        return ProviderResult(answer=answer, model=self.model,
                              tokens_in=getattr(usage, "prompt_token_count", None), tokens_out=getattr(usage, "candidates_token_count", None))
