import asyncio

import pytest

from app.engine.providers.errors import (
    AllProvidersFailed,
    LLMOutputError,
    ProviderAuthError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.engine.providers.fake import FakeLLM, FakeSearch, make_hit
from app.engine.providers.fallback import FallbackLLM, FallbackSearch
from tests.unit.providers._helpers import Verdict

GOOD = {"answer": "ok", "score": 1}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def gen(llm):
    return asyncio.run(llm.generate_structured(system="s", prompt="p", response_model=Verdict))


def llm_pair(primary_script, fallback_script, clock=None, cooldown=60.0):
    primary, fallback = FakeLLM(primary_script), FakeLLM(fallback_script)
    return (
        primary,
        fallback,
        FallbackLLM(primary, fallback, cooldown_seconds=cooldown, clock=clock or Clock()),
    )


def test_primary_success_never_touches_fallback():
    primary, fallback, llm = llm_pair([GOOD], [])
    assert gen(llm).answer == "ok"
    assert len(primary.calls) == 1 and fallback.calls == []


def test_name_combines_both():
    assert llm_pair([], [])[2].name == "fake+fake"


@pytest.mark.parametrize(
    "error",
    [
        ProviderRateLimited("p", "429"),
        ProviderUnavailable("p", "down"),
        ProviderAuthError("p", "bad key"),
        LLMOutputError("p", "bad json"),
    ],
)
def test_any_primary_error_falls_back(error):
    _, fallback, llm = llm_pair([error], [GOOD])
    assert gen(llm).answer == "ok" and len(fallback.calls) == 1


def test_rate_limit_starts_cooldown_so_primary_is_skipped_until_it_ends():
    clock = Clock()
    primary, fallback, llm = llm_pair(
        [ProviderRateLimited("p", "429"), GOOD], [GOOD, GOOD, GOOD], clock=clock
    )
    gen(llm)  # primary fails -> fallback
    gen(llm)  # cooldown: primary NOT called
    assert len(primary.calls) == 1 and len(fallback.calls) == 2
    clock.now += 61
    gen(llm)  # cooldown over: primary tried again (and succeeds)
    assert len(primary.calls) == 2 and len(fallback.calls) == 2


def test_a_single_bad_output_does_not_start_a_cooldown():
    primary, fallback, llm = llm_pair([LLMOutputError("p", "bad"), GOOD], [GOOD])
    gen(llm)
    gen(llm)
    assert len(primary.calls) == 2


def test_both_failing_raises_all_providers_failed_with_both_errors():
    _, _, llm = llm_pair([ProviderRateLimited("a", "429")], [ProviderUnavailable("b", "down")])
    with pytest.raises(AllProvidersFailed) as info:
        gen(llm)
    assert [type(e) for e in info.value.errors] == [ProviderRateLimited, ProviderUnavailable]
    assert "429" in str(info.value) and "down" in str(info.value)


def test_fallback_failing_while_primary_in_cooldown_reports_one_error():
    clock = Clock()
    _, _, llm = llm_pair(
        [ProviderRateLimited("a", "429")],
        [GOOD, ProviderUnavailable("b", "down")],
        clock=clock,
    )
    gen(llm)
    with pytest.raises(AllProvidersFailed) as info:
        gen(llm)
    assert len(info.value.errors) == 1


def test_non_provider_exceptions_are_not_swallowed():
    _, fallback, llm = llm_pair([RuntimeError("bug")], [GOOD])
    with pytest.raises(RuntimeError):
        gen(llm)
    assert fallback.calls == []


def test_tier_and_arguments_are_forwarded_to_fallback():
    from app.engine.providers.models import ModelTier

    _, fallback, llm = llm_pair([ProviderUnavailable("p", "x")], [GOOD])
    asyncio.run(
        llm.generate_structured(
            system="S", prompt="P", response_model=Verdict, tier=ModelTier.LIGHT
        )
    )
    call = fallback.calls[0]
    assert (call.system, call.prompt, call.tier) == ("S", "P", ModelTier.LIGHT)


# ---- search ---------------------------------------------------------------------------------
HIT = make_hit("https://example.com/a", "text")


def failing(error):
    def raise_it(query, n):
        raise error

    return raise_it


def search(provider, q="q"):
    return asyncio.run(provider.search(q, max_results=5))


def test_search_falls_back_and_cools_down():
    clock = Clock()
    primary = FakeSearch(failing(ProviderRateLimited("tavily", "429")))
    fallback = FakeSearch({"q": [HIT]})
    wrapper = FallbackSearch(primary, fallback, cooldown_seconds=30, clock=clock)
    assert search(wrapper) == [HIT]
    assert search(wrapper) == [HIT]
    assert len(primary.calls) == 1 and len(fallback.calls) == 2
    clock.now += 31
    search(wrapper)
    assert len(primary.calls) == 2


def test_search_primary_success_skips_fallback_and_empty_results_are_not_failures():
    primary, fallback = FakeSearch({}), FakeSearch({"q": [HIT]})
    assert search(FallbackSearch(primary, fallback)) == []  # empty is a valid answer
    assert fallback.calls == []


def test_search_both_fail():
    wrapper = FallbackSearch(
        FakeSearch(failing(ProviderAuthError("a", "key"))),
        FakeSearch(failing(ProviderUnavailable("b", "down"))),
    )
    with pytest.raises(AllProvidersFailed):
        search(wrapper)