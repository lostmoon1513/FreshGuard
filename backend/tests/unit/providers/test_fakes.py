import asyncio

import pytest

from app.engine.providers.errors import ProviderUnavailable
from app.engine.providers.fake import FakeLLM, FakeSearch, make_hit
from app.engine.providers.models import LLMProvider, ModelTier, SearchProvider
from tests.unit.providers._helpers import Verdict


def gen(llm, **kw):
    return asyncio.run(
        llm.generate_structured(system="s", prompt="p", response_model=Verdict, **kw)
    )


def test_fakes_satisfy_the_provider_protocols():
    assert isinstance(FakeLLM(), LLMProvider) and isinstance(FakeSearch(), SearchProvider)


def test_llm_replays_script_in_order_and_records_calls():
    llm = FakeLLM([{"answer": "a", "score": 1}, Verdict(answer="b", score=2)])
    assert gen(llm).answer == "a"
    assert gen(llm, tier=ModelTier.LIGHT).answer == "b"
    assert [c.tier for c in llm.calls] == [ModelTier.STANDARD, ModelTier.LIGHT]
    assert llm.calls[0].prompt == "p" and llm.calls[0].response_model is Verdict


def test_llm_exhausted_script_fails_loudly_instead_of_inventing_output():
    with pytest.raises(AssertionError, match="exhausted"):
        gen(FakeLLM())


def test_llm_scripted_exception_is_raised():
    with pytest.raises(ProviderUnavailable):
        gen(FakeLLM([ProviderUnavailable("fake", "down")]))


def test_llm_scripted_invalid_dict_fails_validation():
    with pytest.raises(ValueError):
        gen(FakeLLM([{"answer": "a"}]))


def test_llm_callable_script():
    llm = FakeLLM(lambda call: {"answer": call.prompt.upper(), "score": 0})
    assert gen(llm).answer == "P"


def test_search_returns_scripted_hits_case_and_space_insensitively():
    hit = make_hit("https://example.com/a", "text")
    search = FakeSearch({"Acme  CEO": [hit]})
    assert asyncio.run(search.search("acme ceo", max_results=5)) == [hit]
    assert asyncio.run(search.search("something else", max_results=5)) == []
    assert search.calls == [("acme ceo", 5), ("something else", 5)]


def test_search_truncates_to_max_results_and_supports_callables():
    hits = [make_hit(f"https://example.com/{i}", "t") for i in range(5)]
    assert len(asyncio.run(FakeSearch({"q": hits}).search("q", max_results=2))) == 2
    assert len(asyncio.run(FakeSearch(lambda q, n: hits).search("x", max_results=3))) == 3


def test_make_hit_defaults():
    hit = make_hit("https://example.com/a", "body", title="T")
    assert hit.provider == "fake" and hit.content == "body" and hit.text == "body"