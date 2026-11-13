"""LLM and search providers: interfaces, real clients, fallbacks, cache and test fakes.

The engine depends on `LLMProvider` and `SearchProvider` only. Build real ones with
`build_llm(settings)` / `build_search(settings)`.
"""

from app.engine.providers.cache import CachedSearch, InMemoryTTLCache, SearchCache
from app.engine.providers.errors import (
    AllProvidersFailed,
    FetchError,
    LLMOutputError,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderConfigError,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
    UnsafeURLError,
)
from app.engine.providers.factory import build_fetcher, build_llm, build_search
from app.engine.providers.fallback import FallbackLLM, FallbackSearch
from app.engine.providers.fetcher import HttpPageFetcher, PageFetcher
from app.engine.providers.langchain_llm import LangChainLLM
from app.engine.providers.langchain_search import LangChainSerperSearch, LangChainTavilySearch
from app.engine.providers.models import LLMProvider, ModelTier, SearchHit, SearchProvider

__all__ = [
    "AllProvidersFailed",
    "CachedSearch",
    "FallbackLLM",
    "FetchError",
    "FallbackSearch",
    "InMemoryTTLCache",
    "HttpPageFetcher",
    "LLMOutputError",
    "LangChainLLM",
    "LangChainSerperSearch",
    "LangChainTavilySearch",
    "LLMProvider",
    "ModelTier",
    "ProviderAuthError",
    "ProviderBadResponse",
    "PageFetcher",
    "ProviderConfigError",
    "ProviderError",
    "ProviderQuotaExceeded",
    "ProviderRateLimited",
    "ProviderUnavailable",
    "SearchCache",
    "UnsafeURLError",
    "SearchHit",
    "SearchProvider",
    "build_fetcher",
    "build_llm",
    "build_search",
]