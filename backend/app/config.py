"""Application settings, loaded from environment variables and an optional .env file.

Responsibility: one validated place for configuration.
Inputs: environment variables / .env.   Outputs: a `Settings` object.
Dependencies: pydantic-settings only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Which API key each real provider needs.
_LLM_KEY_FIELD = {"gemini": "gemini_api_key", "groq": "groq_api_key"}
_SEARCH_KEY_FIELD = {"tavily": "tavily_api_key", "serper": "serper_api_key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False
    database_url: str = "sqlite:///./freshguard.db"

    # Defaults are the REAL providers on purpose: a missing key fails loudly at startup.
    llm_provider: Literal["gemini", "groq", "fake"] = "gemini"
    search_provider: Literal["tavily", "serper", "fake"] = "tavily"

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None

    # How real providers talk to vendors: LangChain integrations (default) or plain REST backup.
    provider_backend: Literal["langchain", "rest"] = "langchain"

    # Model ids are config, not code: vendors rename models often.
    gemini_model_standard: str = "gemini-3.8-flash"
    gemini_model_light: str = "gemini-3.5-flash-lite"
    groq_model_standard: str = "llama-3.3-70b-versatile"
    groq_model_light: str = "llama-3.3-70b-versatile"

    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    # Page fetcher (reads publish dates and quotes from pages).
    fetch_timeout_seconds: float = Field(default=15.0, gt=0, le=60)
    # Your email or site; goes into the fetcher's User-Agent (Wikipedia returns 403 without one).
    fetch_contact: str = ""
    search_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    # Short on purpose: long-cached search results would hide fresh changes. 0 disables the cache.
    search_cache_ttl_seconds: int = Field(default=6 * 3600, ge=0, le=7 * 24 * 3600)

    # API (M5). No key: auth off in development; the server refuses to start in production.
    freshguard_api_key: SecretStr | None = None
    max_concurrent_verifications: int = Field(default=2, ge=1, le=20)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=10_000)
    cors_origins: str = ""  # comma-separated origins for the dashboard; empty = no CORS

    max_claims_per_answer: int = Field(default=10, ge=1, le=50)
    max_search_results_per_query: int = Field(default=5, ge=1, le=20)
    max_query_retries: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def _validate_providers(self) -> Self:
        if self.environment == "production" and "fake" in (
            self.llm_provider,
            self.search_provider,
        ):
            raise ValueError("Fake providers are for tests only and are not allowed in production.")

        if self.environment == "production" and not _has_value(self.freshguard_api_key):
            raise ValueError("FRESHGUARD_API_KEY must be set in production.")

        missing: list[str] = []
        if self.llm_provider != "fake":
            field = _LLM_KEY_FIELD[self.llm_provider]
            if not _has_value(getattr(self, field)):
                missing.append(field.upper())
        if self.search_provider != "fake":
            field = _SEARCH_KEY_FIELD[self.search_provider]
            if not _has_value(getattr(self, field)):
                missing.append(field.upper())
        if missing:
            raise ValueError(
                "Missing API key(s) for the selected providers: "
                + ", ".join(missing)
                + ". Set them in .env, or use fake providers in tests."
            )
        return self


def _has_value(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    """Cached settings. Tests should build `Settings(...)` directly instead."""
    return Settings()