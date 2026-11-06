"""Environment-backed application settings (đọc từ .env, xem .env.example)."""
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    # ai_db (Postgres + pgvector, docker compose)
    ai_db_host: str = "127.0.0.1"
    ai_db_port: int = 5434
    ai_db_name: str = "ai_db"
    ai_db_user: str = "ai_user"
    ai_db_password: SecretStr = SecretStr("")

    # Tìm món
    embedding_model: str = "BAAI/bge-m3"
    search_threshold: float = 0.64      # sim top-1 >= ngưỡng (hoặc có món khớp từ khóa) thì nhận kết quả; đo ở docs/recipe_rag
    search_top_k: int = 5
    search_default_servings: int = 4    # khi công thức không ghi khẩu phần và khách cũng không nói

    # Backend Medusa gọi service này kèm header X-Internal-Key (hợp đồng: grocery-store-backend/docs/contracts/ai-service.md)
    ai_internal_key: SecretStr = SecretStr("")

    # Lớp lời AI (khóa chỉ nằm ở .env, không ghi vào DB hay log)
    gemini_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-flash-latest"
    claude_model: str = "claude-haiku-5-5"
    openrouter_model: str = "google/gemini-2.5-flash"
    ai_timeout_s: float = 20.0          # giới hạn thời gian cho MỖI lần gọi nhà cung cấp
    ai_total_budget_s: float = 30.0     # tổng thời gian tối đa cho cả lớp lời; quá thì trả bản dự phòng
    ai_gemini_enabled: bool = True      # sau này đọc từ ai_db (trang admin), tạm đọc từ .env
    ai_gemini_priority: int = 1
    ai_claude_enabled: bool = False
    ai_claude_priority: int = 2
    ai_openrouter_enabled: bool = False
    ai_openrouter_priority: int = 3
    copilot_candidates: int = 3         # số món ứng viên đưa cho mô hình chọn


_settings: Settings | None = None


def get_settings() -> Settings:
    """Đọc cấu hình một lần rồi dùng lại."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
