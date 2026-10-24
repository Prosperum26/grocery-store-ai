"""Claude provider (Haiku 5.5): dự phòng và dùng khi demo. Cùng schema AiAnswer với Gemini."""
import anthropic
from pydantic import ValidationError

from src.schemas.copilot_dto import AiAnswer
from src.services.llm_provider import ProviderError, ProviderInvalid, ProviderResult, ProviderTimeout

MAX_OUTPUT_TOKENS = 2000


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str, model: str):
        self.model = model
        # max_retries=0: SDK không tự thử lại, việc thử lại / chuyển nhà cung cấp do CopilotService quyết để kiểm soát thời gian.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0)

    def generate(self, system: str, user: str, timeout_s: float) -> ProviderResult:
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=AiAnswer,                  # SDK gửi JSON schema và kiểm tra kết quả theo model Pydantic
                output_config={"effort": "low"},         # việc đơn giản, trả lời nhanh và rẻ
                timeout=timeout_s,
            )
        except anthropic.APITimeoutError as e:
            raise ProviderTimeout("Claude hết thời gian chờ") from e
        except anthropic.APIError as e:
            raise ProviderError(f"Claude API {getattr(e, 'status_code', type(e).__name__)}") from e
        except ValidationError as e:
            raise ProviderInvalid(f"JSON không đúng schema: {e.error_count()} lỗi") from e
        if response.stop_reason == "refusal":
            raise ProviderError("Claude từ chối trả lời")
        if response.parsed_output is None:
            raise ProviderInvalid("Claude không trả về JSON đúng schema")
        return ProviderResult(answer=response.parsed_output, model=self.model,
                              tokens_in=response.usage.input_tokens, tokens_out=response.usage.output_tokens)
