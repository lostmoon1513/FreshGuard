"""Test-only sequential runner mirroring the M4 graph order. Not used in production."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.engine.nodes import (
    ClaimWork,
    Deps,
    assemble_result,
    check_quote_integrity,
    classify_volatility,
    compare_stance,
    decide,
    extract_claims,
    fail_result,
    generate_queries,
    needs_reformulation,
    retrieve_evidence,
    suggest_correction,
    validate_sources,
)
from app.engine.providers.errors import ProviderError
from app.engine.providers.fake import FAKE_NOW, FakeFetcher, FakeLLM, FakeLLMCall, FakeSearch
from app.engine.providers.models import SearchHit
from app.schemas.verification import VerificationResult

NOW = FAKE_NOW + timedelta(days=60)  # 2026-03-02


def make_deps(llm: FakeLLM, search: FakeSearch, fetcher: FakeFetcher | None = None) -> Deps:
    return Deps(llm=llm, search=search, fetcher=fetcher, clock=lambda: NOW)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


async def _search_round(c: ClaimWork, deps: Deps) -> ClaimWork:
    c = await retrieve_evidence(c, deps)
    return await validate_sources(c, deps)


async def run_pipeline(question: str, answer: str, deps: Deps) -> VerificationResult:
    created = deps.clock()
    try:
        claims = await extract_claims(question, answer, deps)
    except ProviderError:
        return fail_result("t", "extraction failed", created, deps.clock())
    claims = await classify_volatility(claims, deps)
    claims = await generate_queries(claims, deps)
    claims = [await _search_round(c, deps) for c in claims]
    if any(needs_reformulation(c) for c in claims):
        claims = await generate_queries(claims, deps, reformulate=True)
        claims = [await _search_round(c, deps) if needs_reformulation_ran(c) else c for c in claims]
    claims = [await compare_stance(c, deps) for c in claims]
    claims = [check_quote_integrity(c) for c in claims]
    claims = [decide(c, deps) for c in claims]
    claims = [await suggest_correction(c, deps) for c in claims]
    return assemble_result("t", claims, created, deps.clock())


def needs_reformulation_ran(c: ClaimWork) -> bool:
    return c.attempts == 2 and not c.sources


def hit(url: str, text: str, age: int | None = 5) -> SearchHit:
    return SearchHit(
        url=url,
        content=text,
        published_at=days_ago(age) if age is not None else None,
        retrieved_at=NOW,
        provider="fake",
    )


def scripted_llm(handlers: dict[str, object]) -> FakeLLM:
    """Dispatch by response model name -> dict | model | Exception | callable(call)."""

    def reply(call: FakeLLMCall):
        h = handlers[call.response_model.__name__]
        if isinstance(h, list):
            return h.pop(0)
        return h(call) if callable(h) else h

    return FakeLLM(reply)