"""OpenRouter provider: một khóa gọi được nhiều mô hình, giao diện kiểu OpenAI. Cùng schema AiAnswer với Gemini / Claude."""
import httpx
from pydantic import ValidationError

from src.schemas.copilot_dto import AiAnswer
from src.services.llm_provider import ProviderError, ProviderInvalid, ProviderResult, ProviderTimeout

URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_OUTPUT_TOKENS = 2000


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str, model: str):
        self.model = model
        self._api_key = api_key

    def generate(self, system: str, user: str, timeout_s: float) -> ProviderResult:
        body = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "AiAnswer", "strict": True, "schema": AiAnswer.model_json_schema()}},
            "provider": {"require_parameters": True},       # chỉ chọn nơi chạy thật sự hỗ trợ json_schema, không âm thầm bỏ qua
        }
        try:
            response = httpx.post(URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}, timeout=timeout_s)
        except httpx.TimeoutException as e:
            raise ProviderTimeout("OpenRouter hết thời gian chờ") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenRouter {type(e).__name__}") from e
        if response.status_code != 200:
            raise ProviderError(f"OpenRouter API {response.status_code}: {_error_message(response)}")
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderInvalid("OpenRouter trả về sai khuôn dạng") from e
        if not text:
            raise ProviderInvalid("OpenRouter trả về rỗng")
        try:
            answer = AiAnswer.model_validate_json(text)
        except ValidationError as e:
            raise ProviderInvalid(f"JSON không đúng schema: {e.error_count()} lỗi") from e
        usage = data.get("usage") or {}
        return ProviderResult(answer=answer, model=self.model, tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))


def _error_message(response: httpx.Response) -> str:
    """Lấy câu lỗi ngắn từ thân phản hồi (không chứa khóa) để dễ chẩn đoán."""
    try:
        return str(response.json().get("error", {}).get("message", ""))[:200]
    except ValueError:
        return response.text[:200]
