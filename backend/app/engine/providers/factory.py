"""Build providers from Settings. Defense in depth: fakes are refused in production here too.

`settings` is duck-typed (only attributes are read), so tests can pass a simple object.
Primary comes from LLM_PROVIDER / SEARCH_PROVIDER. If the *other* real provider's key is also
set, it is wired in as the fallback (Gemini->Groq, Tavily->Serper).

PROVIDER_BACKEND picks how real providers talk to the vendors:
  "langchain" (default): LangChain chat models and search tools behind our interfaces.
  "rest": plain REST calls through httpx. Kept as a tested backup.
Both implement the same `LLMProvider` / `SearchProvider`, so nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.engine.providers import langchain_backend
from app.engine.providers.cache import CachedSearch, InMemoryTTLCache, SearchCache
from app.engine.providers.errors import ProviderConfigError
from app.engine.providers.fake import FakeFetcher, FakeLLM, FakeSearch
from app.engine.providers.fallback import FallbackLLM, FallbackSearch
from app.engine.providers.fetcher import USER_AGENT, HttpPageFetcher, PageFetcher
from app.engine.providers.gemini import GeminiProvider
from app.engine.providers.groq import GroqProvider
from app.engine.providers.http import HttpClient, RetryPolicy
from app.engine.providers.langchain_llm import LangChainLLM
from app.engine.providers.langchain_search import LangChainSerperSearch, LangChainTavilySearch
from app.engine.providers.models import LLMProvider, ModelTier, SearchProvider
from app.engine.providers.serper import SerperSearch
from app.engine.providers.tavily import TavilySearch

if TYPE_CHECKING:  # avoid importing pydantic-settings at runtime
    from app.config import Settings

# (provider name, tier) -> LangChain chat model. Tests inject fakes here.
ChatModelFactory = Callable[[str, ModelTier], Any]
# provider name ("tavily" | "serper") -> LangChain search tool / wrapper.
SearchToolFactory = Callable[[str], Any]


def _has(secret: Any) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def _backend(settings: Settings) -> str:
    backend = getattr(settings, "provider_backend", "rest")
    if backend not in ("langchain", "rest"):
        raise ProviderConfigError(f"Unknown PROVIDER_BACKEND: {backend!r}")
    return backend


def _refuse_fakes_in_production(settings: Settings) -> None:
    if settings.environment == "production" and "fake" in (
        settings.llm_provider,
        settings.search_provider,
    ):
        raise ProviderConfigError(
            "Fake providers are for tests only and are not allowed in production."
        )


def _http(http: HttpClient | None) -> HttpClient:
    if http is not None:
        return http
    from app.engine.providers.httpx_client import HttpxClient  # lazy: needs httpx

    return HttpxClient()


def build_llm(
    settings: Settings,
    *,
    http: HttpClient | None = None,
    chat_model_factory: ChatModelFactory | None = None,
) -> LLMProvider:
    _refuse_fakes_in_production(settings)
    if settings.llm_provider == "fake":
        return FakeLLM()
    use_langchain = _backend(settings) == "langchain"
    client = None if use_langchain else _http(http)
    retry = RetryPolicy(max_attempts=settings.provider_max_attempts)
    timeout = settings.llm_timeout_seconds
    make_model = chat_model_factory or (
        lambda provider, tier: langchain_backend.make_chat_model(settings, provider, tier)
    )

    def make(name: str) -> LLMProvider:
        if use_langchain:
            return LangChainLLM(name, {tier: make_model(name, tier) for tier in ModelTier})
        assert client is not None
        if name == "gemini":
            return GeminiProvider(
                settings.gemini_api_key,  # type: ignore[arg-type]
                client,
                models={
                    ModelTier.STANDARD: settings.gemini_model_standard,
                    ModelTier.LIGHT: settings.gemini_model_light,
                },
                retry=retry,
                timeout=timeout,
            )
        return GroqProvider(
            settings.groq_api_key,  # type: ignore[arg-type]
            client,
            models={
                ModelTier.STANDARD: settings.groq_model_standard,
                ModelTier.LIGHT: settings.groq_model_light,
            },
            retry=retry,
            timeout=timeout,
        )

    primary = settings.llm_provider
    other = "groq" if primary == "gemini" else "gemini"
    other_key = settings.groq_api_key if other == "groq" else settings.gemini_api_key
    if _has(other_key):
        return FallbackLLM(make(primary), make(other))
    return make(primary)


def build_search(
    settings: Settings,
    *,
    http: HttpClient | None = None,
    cache: SearchCache | None = None,
    search_tool_factory: SearchToolFactory | None = None,
) -> SearchProvider:
    _refuse_fakes_in_production(settings)
    if settings.search_provider == "fake":
        return FakeSearch()
    use_langchain = _backend(settings) == "langchain"
    client = None if use_langchain else _http(http)
    retry = RetryPolicy(max_attempts=settings.provider_max_attempts)
    timeout = settings.search_timeout_seconds
    make_tool = search_tool_factory or (
        lambda provider: langchain_backend.make_search_tool(settings, provider)
    )

    def make(name: str) -> SearchProvider:
        if use_langchain:
            tool = make_tool(name)
            return LangChainTavilySearch(tool) if name == "tavily" else LangChainSerperSearch(tool)
        assert client is not None
        if name == "tavily":
            return TavilySearch(settings.tavily_api_key, client, retry=retry, timeout=timeout)  # type: ignore[arg-type]
        return SerperSearch(settings.serper_api_key, client, retry=retry, timeout=timeout)  # type: ignore[arg-type]

    primary = settings.search_provider
    other = "serper" if primary == "tavily" else "tavily"
    other_key = settings.serper_api_key if other == "serper" else settings.tavily_api_key
    provider: SearchProvider = (
        FallbackSearch(make(primary), make(other)) if _has(other_key) else make(primary)
    )
    if settings.search_cache_ttl_seconds > 0:
        provider = CachedSearch(
            provider,
            cache if cache is not None else InMemoryTTLCache(),
            ttl_seconds=settings.search_cache_ttl_seconds,
        )
    return provider


def user_agent_for(contact: str) -> str:
    """Some sites (Wikipedia) reject anonymous bots with 403; a contact in the UA fixes that."""
    contact = " ".join(contact.split())[:120]
    return f"FreshGuardBot/0.1 (+{contact})" if contact else USER_AGENT


def build_fetcher(settings: Settings, *, http: Any = None) -> PageFetcher:
    """The page fetcher. `http` must provide `get(...)` (the real `HttpxClient` does)."""
    _refuse_fakes_in_production(settings)
    if settings.search_provider == "fake":
        return FakeFetcher()
    client = http if http is not None else _http(None)
    return HttpPageFetcher(
        client,
        timeout=float(getattr(settings, "fetch_timeout_seconds", 10.0)),
        max_bytes=int(getattr(settings, "fetch_max_bytes", 1_500_000)),
        user_agent=user_agent_for(str(getattr(settings, "fetch_contact", "") or "")),
    )