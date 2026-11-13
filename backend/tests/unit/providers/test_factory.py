import asyncio
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.engine.providers import (
    CachedSearch,
    FallbackLLM,
    FallbackSearch,
    ProviderConfigError,
    build_llm,
    build_search,
)
from app.engine.providers.fake import FakeLLM, FakeSearch
from app.engine.providers.gemini import GeminiProvider
from app.engine.providers.groq import GroqProvider
from app.engine.providers.serper import SerperSearch
from app.engine.providers.tavily import TavilySearch
from tests.unit.providers._helpers import FakeHttp, Verdict, gemini_reply, groq_reply, ok


def settings(**over):
    base = dict(
        environment="development",
        llm_provider="gemini",
        search_provider="tavily",
        gemini_api_key=SecretStr("g"),
        groq_api_key=None,
        tavily_api_key=SecretStr("t"),
        serper_api_key=None,
        gemini_model_standard="std-model",
        gemini_model_light="lite-model",
        groq_model_standard="groq-std",
        groq_model_light="groq-lite",
        llm_timeout_seconds=11.0,
        search_timeout_seconds=7.0,
        provider_max_attempts=2,
        search_cache_ttl_seconds=0,
    )
    base.update(over)
    return SimpleNamespace(**base)


HTTP = FakeHttp()


@pytest.mark.parametrize("which", ["llm_provider", "search_provider"])
def test_fakes_are_refused_in_production(which):
    s = settings(environment="production", **{which: "fake"})
    with pytest.raises(ProviderConfigError, match="not allowed in production"):
        build_llm(s, http=HTTP)
    with pytest.raises(ProviderConfigError, match="not allowed in production"):
        build_search(s, http=HTTP)


def test_fakes_are_built_outside_production():
    s = settings(environment="test", llm_provider="fake", search_provider="fake")
    assert isinstance(build_llm(s), FakeLLM) and isinstance(build_search(s), FakeSearch)


def test_gemini_only():
    llm = build_llm(settings(), http=HTTP)
    assert isinstance(llm, GeminiProvider)


@pytest.mark.parametrize(
    ("primary", "gemini", "groq", "name"),
    [
        ("gemini", "g", "q", "gemini+groq"),
        ("groq", "g", "q", "groq+gemini"),
    ],
)
def test_other_providers_key_wires_a_fallback(primary, gemini, groq, name):
    s = settings(
        llm_provider=primary, gemini_api_key=SecretStr(gemini), groq_api_key=SecretStr(groq)
    )
    llm = build_llm(s, http=HTTP)
    assert isinstance(llm, FallbackLLM) and llm.name == name


def test_blank_other_key_means_no_fallback():
    llm = build_llm(settings(groq_api_key=SecretStr("   ")), http=HTTP)
    assert isinstance(llm, GeminiProvider)


def test_groq_primary_alone():
    s = settings(llm_provider="groq", gemini_api_key=None, groq_api_key=SecretStr("q"))
    assert isinstance(build_llm(s, http=HTTP), GroqProvider)


def test_model_names_and_timeouts_come_from_settings():
    http = FakeHttp(gemini_reply('{"answer": "a", "score": 1}'))
    llm = build_llm(settings(), http=http)
    asyncio.run(llm.generate_structured(system="s", prompt="p", response_model=Verdict))
    assert "/models/std-model:generateContent" in http.calls[0]["url"]
    assert http.calls[0]["timeout"] == 11.0


def test_fallback_llm_actually_uses_groq_when_gemini_fails():
    http = FakeHttp(
        *[ok({"error": "x"})] * 0,  # placeholder to keep the script explicit below
    )
    from tests.unit.providers._helpers import status

    http = FakeHttp(status(401), groq_reply('{"answer": "from groq", "score": 2}'))
    s = settings(groq_api_key=SecretStr("q"))
    llm = build_llm(s, http=http)
    result = asyncio.run(llm.generate_structured(system="s", prompt="p", response_model=Verdict))
    assert result.answer == "from groq"
    assert "groq.com" in http.calls[1]["url"] and http.calls[1]["body"]["model"] == "groq-std"


def test_search_variants():
    assert isinstance(build_search(settings(), http=HTTP), TavilySearch)
    both = build_search(settings(serper_api_key=SecretStr("s")), http=HTTP)
    assert isinstance(both, FallbackSearch) and both.name == "tavily+serper"
    serper_first = build_search(
        settings(search_provider="serper", serper_api_key=SecretStr("s"), tavily_api_key=None),
        http=HTTP,
    )
    assert isinstance(serper_first, SerperSearch)


def test_cache_wraps_search_only_when_ttl_positive():
    assert not isinstance(
        build_search(settings(search_cache_ttl_seconds=0), http=HTTP), CachedSearch
    )
    cached = build_search(settings(search_cache_ttl_seconds=60), http=HTTP)
    assert isinstance(cached, CachedSearch) and cached.name == "tavily"


def test_cache_actually_prevents_a_second_api_call():
    http = FakeHttp(ok({"results": [{"url": "https://example.com/a", "content": "text"}]}))
    search = build_search(settings(search_cache_ttl_seconds=60), http=http)
    for _ in range(3):
        asyncio.run(search.search("Same Query", max_results=5))
    assert len(http.calls) == 1


def test_provider_max_attempts_is_applied():
    from tests.unit.providers._helpers import status

    http = FakeHttp(status(500), status(500), status(500))
    search = build_search(settings(provider_max_attempts=2), http=http)
    with pytest.raises(Exception):  # noqa: B017
        asyncio.run(search.search("q", max_results=5))
    assert len(http.calls) == 2


# ---- LangChain backend ----------------------------------------------------------------------
class _ChatModel:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, messages):
        from types import SimpleNamespace

        return SimpleNamespace(content=self.text)


def test_langchain_backend_builds_langchain_providers_without_touching_httpx():
    from app.engine.providers import LangChainLLM, LangChainTavilySearch

    built = []

    def chat_factory(provider, tier):
        built.append((provider, tier))
        return _ChatModel("{}")

    s = settings(provider_backend="langchain")
    llm = build_llm(s, chat_model_factory=chat_factory)  # note: no http client given
    assert isinstance(llm, LangChainLLM) and llm.name == "gemini"
    assert sorted(t.value for p, t in built) == ["light", "standard"]
    assert {p for p, _ in built} == {"gemini"}

    search = build_search(s, search_tool_factory=lambda name: object())
    assert isinstance(search, LangChainTavilySearch)


def test_langchain_backend_wires_the_fallback_when_both_keys_exist():
    s = settings(
        provider_backend="langchain",
        groq_api_key=SecretStr("q"),
        serper_api_key=SecretStr("s"),
    )
    llm = build_llm(s, chat_model_factory=lambda p, t: _ChatModel("{}"))
    assert isinstance(llm, FallbackLLM) and llm.name == "gemini+groq"
    search = build_search(s, search_tool_factory=lambda name: object())
    assert isinstance(search, FallbackSearch) and search.name == "tavily+serper"


def test_langchain_search_goes_through_the_cache_too():
    s = settings(provider_backend="langchain", search_cache_ttl_seconds=60)
    assert isinstance(build_search(s, search_tool_factory=lambda n: object()), CachedSearch)


def test_rest_backend_is_still_available_and_unknown_backends_are_refused():
    assert isinstance(build_llm(settings(provider_backend="rest"), http=HTTP), GeminiProvider)
    with pytest.raises(ProviderConfigError, match="PROVIDER_BACKEND"):
        build_llm(settings(provider_backend="magic"), http=HTTP)
    with pytest.raises(ProviderConfigError, match="PROVIDER_BACKEND"):
        build_search(settings(provider_backend="magic"), http=HTTP)


def test_fakes_ignore_the_backend_and_are_still_refused_in_production():
    s = settings(
        environment="test",
        llm_provider="fake",
        search_provider="fake",
        provider_backend="langchain",
    )
    assert isinstance(build_llm(s), FakeLLM) and isinstance(build_search(s), FakeSearch)
    with pytest.raises(ProviderConfigError):
        build_llm(
            settings(environment="production", llm_provider="fake", provider_backend="langchain")
        )