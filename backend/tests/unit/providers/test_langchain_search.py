import asyncio
from datetime import UTC, datetime

import pytest

from app.engine.providers.errors import ProviderAuthError, ProviderBadResponse
from app.engine.providers.langchain_search import LangChainSerperSearch, LangChainTavilySearch

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class FakeTavilyTool:
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        if self.error:
            raise self.error
        return self.data


class FakeSerperWrapper:
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    async def aresults(self, query):
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.data


def tavily(tool, **kw):
    return LangChainTavilySearch(tool, clock=lambda: NOW, **kw)


def serper(wrapper):
    return LangChainSerperSearch(wrapper, clock=lambda: NOW)


def run(provider, query="who is the ceo", n=5):
    return asyncio.run(provider.search(query, max_results=n))


def t_item(i, **over):
    return {
        "title": f"T{i}",
        "url": f"https://example.com/{i}",
        "content": f"snippet {i}",
        "score": 0.5,
        **over,
    }


def test_tavily_parses_content_and_passes_a_clean_query():
    tool = FakeTavilyTool({"results": [t_item(1, raw_content="full page text")]})
    hits = run(tavily(tool), "  hello  ")
    assert tool.calls == [{"query": "hello"}]
    assert hits[0].content == "full page text" and hits[0].snippet == "snippet 1"
    assert hits[0].provider == "tavily" and hits[0].published_at is None  # never guessed


def test_tavily_keeps_published_date_when_the_wrapper_provides_it():
    tool = FakeTavilyTool({"results": [t_item(1, raw_content="x", published_date="2026-11-01")]})
    assert run(tavily(tool))[0].published_at == datetime(2026, 11, 1, tzinfo=UTC)


def test_tavily_slices_to_max_results_and_skips_junk():
    items = [t_item(i, raw_content="x") for i in range(10)] + ["junk", {"title": "no url"}]
    assert len(run(tavily(FakeTavilyTool({"results": items})), n=3)) == 3


@pytest.mark.parametrize("data", ["Error: invalid api key", None, [], {"results": "nope"}, {}])
def test_tavily_unusable_responses_are_bad_response_errors(data):
    with pytest.raises(ProviderBadResponse):
        run(tavily(FakeTavilyTool(data)))


def test_tavily_without_raw_content_uses_snippets_only():
    hits = run(tavily(FakeTavilyTool({"results": [t_item(1, raw_content="big")]}), with_raw=False))
    assert hits[0].content is None


def test_tavily_exceptions_are_mapped():
    class InvalidAPIKeyError(Exception):
        pass

    with pytest.raises(ProviderAuthError):
        run(tavily(FakeTavilyTool(error=InvalidAPIKeyError("tvly-secret"))))


def test_empty_query_is_rejected_before_any_call():
    tool = FakeTavilyTool({"results": []})
    with pytest.raises(ValueError):
        run(tavily(tool), "   ")
    assert tool.calls == []


def test_serper_parses_organic_results_and_dates():
    wrapper = FakeSerperWrapper(
        {
            "organic": [
                {"title": "A", "link": "https://a.com/x", "snippet": "s", "date": "Nov 5, 2026"},
                {"title": "B", "link": "https://b.com/y", "snippet": "s2", "date": "recently"},
            ]
        }
    )
    hits = run(serper(wrapper), " q ")
    assert wrapper.calls == ["q"]
    assert [h.provider for h in hits] == ["serper", "serper"]
    assert hits[0].published_at == datetime(2026, 11, 5, tzinfo=UTC)
    assert hits[1].published_at is None and hits[0].content is None


def test_serper_no_organic_means_no_results_not_an_error():
    assert run(serper(FakeSerperWrapper({"searchParameters": {}}))) == []


@pytest.mark.parametrize("data", ["oops", None, ["x"], {"organic": "bad"}])
def test_serper_unusable_responses(data):
    with pytest.raises(ProviderBadResponse):
        run(serper(FakeSerperWrapper(data)))


def test_serper_exceptions_are_mapped():
    class ClientResponseError(Exception):
        status_code = 403

    with pytest.raises(ProviderAuthError):
        run(serper(FakeSerperWrapper(error=ClientResponseError("key"))))