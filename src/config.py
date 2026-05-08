"""
Application configuration via Pydantic Settings.

Values are loaded (in priority order) from:
1. real environment variables
2. ``.env`` file in the project root (gitignored)
3. defaults declared below

Never bake real secrets into defaults — only safe placeholders.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # ---- Database ----
    DATABASE_URL: str = "postgresql+psycopg://quant:quant@localhost:5432/quant_dev"

    # ---- LLM ----
    LLM_PROVIDER: Literal["mock", "openrouter", "openai", "anthropic"] = "mock"
    # Pin a dated model id (see INVARIANT #4 — no `latest` aliases).
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_API_KEY: str = ""
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_TOKENS: int = 4096

    # ---- Data sources ----
    YFINANCE_RATE_LIMIT: int = 2
    TUSHARE_TOKEN: str = ""

    # ---- JWT (V0.7+) ----
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRES_MINUTES: int = 1440

    # ---- Notifications (V0.4+) ----
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 587
    EMAIL_USERNAME: str = ""
    EMAIL_PASSWORD: str = ""

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a memoized Settings instance.

    Tests can clear the cache via ``get_settings.cache_clear()`` after
    monkey-patching environment variables.
    """
    return Settings()


# Convenience handle for app code; tests should prefer get_settings().
settings: Settings = get_settings()
