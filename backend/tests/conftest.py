"""Shared test fixtures."""

import pytest

_ENV_VARS = [
    "ENVIRONMENT",
    "LOG_LEVEL",
    "LOG_JSON",
    "DATABASE_URL",
    "LLM_PROVIDER",
    "SEARCH_PROVIDER",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "TAVILY_API_KEY",
    "SERPER_API_KEY",
    "PROVIDER_BACKEND",
    "GEMINI_MODEL_STANDARD",
    "GEMINI_MODEL_LIGHT",
    "GROQ_MODEL_STANDARD",
    "GROQ_MODEL_LIGHT",
    "LLM_TIMEOUT_SECONDS",
    "SEARCH_TIMEOUT_SECONDS",
    "PROVIDER_MAX_ATTEMPTS",
    "SEARCH_CACHE_TTL_SECONDS",
    "FETCH_TIMEOUT_SECONDS",
    "FETCH_CONTACT",
    "FRESHGUARD_API_KEY",
    "MAX_CONCURRENT_VERIFICATIONS",
    "RATE_LIMIT_PER_MINUTE",
    "CORS_ORIGINS",
    "MAX_CLAIMS_PER_ANSWER",
    "MAX_SEARCH_RESULTS_PER_QUERY",
    "MAX_QUERY_RETRIES",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make tests independent of the developer's real environment and .env file."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)