from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    admin_id: int
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+asyncpg://shorts:shorts@localhost:5432/shorts"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_api_style: str = "chat_completions"
    whisper_model: str = "small"
    media_root: Path = Path("media")
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    access_contact_url: str = "https://t.me/q1team"


@lru_cache
def get_settings() -> Settings:
    return Settings()
