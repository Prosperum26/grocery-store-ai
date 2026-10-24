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


_settings: Settings | None = None


def get_settings() -> Settings:
    """Đọc cấu hình một lần rồi dùng lại."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
