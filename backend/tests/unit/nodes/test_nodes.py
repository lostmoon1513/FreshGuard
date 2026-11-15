from datetime import timedelta

import pytest

from app.engine.nodes import (
    ClaimWork,
    Deps,
    assemble_result,
    check_quote_integrity,
    classify_volatility,
    compare_stance,
    decide,
    extract_claims,
    generate_queries,
    needs_reformulation,
    retrieve_evidence,
    suggest_correction,
    validate_sources,
)
from app.engine.nodes.state import Source
from app.engine.nodes.volatility import guard
from app.engine.providers.errors import FetchError, ProviderUnavailable
from app.engine.providers.fake import FakeFetcher, FakeLLM, FakeSearch
from app.engine.rules.source_tiers import classify_source
from app.schemas.evidence import Document, Evidence
from app.schemas.labels import Label, Stance, VerificationStatus, Volatility
from tests.unit.nodes._runner import NOW, days_ago, hit, make_deps, scripted_llm

ANSWER = "Satya Nadella is the CEO of Microsoft. Python was created in 1991."


def deps_for(llm=None, search=None, fetcher=None) -> Deps:
    return make_deps(llm or FakeLLM([]), search or FakeSearch({}), fetcher)


# ---- extract -------------------------------------------------------------------------------
async def test_extract_keeps_only_grounded_unique_claims():
    llm = FakeLLM(
        [
            {
                "claims": [
                    {
                        "text": "Satya Nadella is the CEO of Microsoft",
                        "answer_span": "Satya Nadella is the CEO of Microsoft.",
                    },
                    {
                        "text": "satya nadella is the ceo of microsoft",
                        "answer_span": "Satya Nadella is the CEO",
                    },
                    {"text": "Invented fact", "answer_span": "Not in the answer at all"},
                    {"text": "No span", "answer_span": ""},
                ]
            }
        ]
    )
    claims = await extract_claims("q", ANSWER, deps_for(llm))
    assert [c.text for c in claims] == ["Satya Nadella is the CEO of Microsoft"]


async def test_extract_caps_claims_and_fences_answer():
    many = {"claims": [{"text": f"claim {i}", "answer_span": ANSWER[:10]} for i in range(30)]}
    llm = FakeLLM([many])
    claims = await extract_claims("q", ANSWER, deps_for(llm))
    assert len(claims) == 8  # capped at Limits.max_claims
    assert "<answer>" in llm.calls[0].prompt


async def test_extract_propagates_provider_error():
    with pytest.raises(ProviderUnavailable):
        await extract_claims("q", ANSWER, deps_for(FakeLLM([ProviderUnavailable("fake", "down")])))


# ---- volatility ----------------------------------------------------------------------------
def test_guard_only_increases_sensitivity():
    assert (
        guard("Alice is the current CEO of X", Volatility.STATIC, None, NOW)[0] == Volatility.SLOW
    )
    assert guard("Python was created in 1991", Volatility.STATIC, None, NOW)[0] == Volatility.STATIC
    assert guard("Revenue grew in 2026", Volatility.STATIC, None, NOW)[0] == Volatility.SLOW
    assert guard("The stock price is 10", Volatility.SLOW, None, NOW)[0] == Volatility.FAST
    assert guard("x", Volatility.FAST, 99999, NOW) == (Volatility.FAST, 3650)
    assert guard("x", Volatility.STATIC, 30, NOW) == (Volatility.STATIC, None)


async def test_volatility_defaults_to_slow_on_failure_and_missing_items():
    claims = [ClaimWork(text="A fact"), ClaimWork(text="Another fact")]
    out = await classify_volatility(claims, deps_for(FakeLLM([ProviderUnavailable("fake", "x")])))
    assert all(c.volatility == Volatility.SLOW and c.notes for c in out)
    llm = FakeLLM([{"items": [{"index": 0, "volatility": "static"}]}])
    out = await classify_volatility(claims, deps_for(llm))
    assert out[0].volatility == Volatility.STATIC and out[1].volatility == Volatility.SLOW


# ---- queries -------------------------------------------------------------------------------
async def test_queries_cleaned_capped_and_static_skipped():
    claims = [ClaimWork(text="Fact one"), ClaimWork(text="Old fact", volatility=Volatility.STATIC)]
    llm = FakeLLM([{"items": [{"index": 0, "queries": ["a  b", "A B", "c", "d", "e"]}]}])
    out = await generate_queries(claims, deps_for(llm))
    assert out[0].queries == ("a b", "c", "d") and out[0].attempts == 1
    assert out[1].queries == () and out[1].attempts == 0


async def test_queries_fallback_to_claim_text_on_failure():
    out = await generate_queries(
        [ClaimWork(text="Fact one")], deps_for(FakeLLM([ProviderUnavailable("fake", "x")]))
    )
    assert out[0].queries == ("Fact one",)


async def test_reformulation_excludes_previous_queries():
    c = ClaimWork(text="Fact", queries=("old q",), attempts=1)
    llm = FakeLLM([{"items": [{"index": 0, "queries": ["old q", "new q"]}]}])
    out = await generate_queries([c], deps_for(llm), reformulate=True)
    assert out[0].queries == ("new q",) and out[0].attempts == 2
    assert "old q" in llm.calls[0].prompt


# ---- retrieve ------------------------------------------------------------------------------
async def test_retrieve_dedupes_and_flags_total_outage():
    h = hit("https://a.com/x/", "text one")
    search = FakeSearch(lambda q, n: [h, hit("https://a.com/x?utm_source=z", "longer text here")])
    c = await retrieve_evidence(ClaimWork(text="f", queries=("q1", "q2")), deps_for(search=search))
    assert len(c.hits) == 1 and not c.provider_failed

    class Boom(FakeSearch):
        async def search(self, query, *, max_results):
            raise ProviderUnavailable("fake", "down")

    c = await retrieve_evidence(ClaimWork(text="f", queries=("q",)), deps_for(search=Boom()))
    assert c.provider_failed and not c.hits


# ---- sources -------------------------------------------------------------------------------
async def test_sources_fetch_credible_snippet_only_and_drop_uncrawlable():
    snippet = hit("https://www.reuters.com/a", "")  # no content
    snippet = snippet.model_copy(update={"content": None, "snippet": "short snippet"})
    blog_snip = hit("https://random.blog/b", "").model_copy(
        update={"content": None, "snippet": "s"}
    )
    full = hit("https://random.blog/c", "full page text about the claim", age=3)
    fetcher = FakeFetcher(
        {
            "https://www.reuters.com/a": Document(
                url="https://www.reuters.com/a",
                text="reuters page text",
                published_at=days_ago(2),
                fetched_at=NOW,
            )
        }
    )
    c = ClaimWork(text="f", hits=(snippet, blog_snip, full))
    out = await validate_sources(c, deps_for(fetcher=fetcher))
    urls = [str(s.document.url) for s in out.sources]
    assert urls == ["https://www.reuters.com/a", "https://random.blog/c"]
    assert out.sources[0].from_fetch and out.sources[0].tier == classify_source(urls[0])
    assert "https://random.blog/b" not in fetcher.calls  # tier 3 never fetched


async def test_sources_fetch_failure_drops_snippet_keeps_content_hit():
    nocontent = hit("https://www.reuters.com/a", "").model_copy(update={"content": None})
    undated = hit("https://www.bbc.com/z", "bbc content text", age=None)
    fetcher = FakeFetcher(
        {"https://www.reuters.com/a": FetchError("x"), "https://www.bbc.com/z": FetchError("x")}
    )
    out = await validate_sources(
        ClaimWork(text="f", hits=(nocontent, undated)), deps_for(fetcher=fetcher)
    )
    assert [str(s.document.url) for s in out.sources] == ["https://www.bbc.com/z"]


async def test_sources_page_date_beats_hit_date_and_static_not_processed():
    undated_hit = hit("https://www.bbc.com/z", "stub text", age=None)
    fetcher = FakeFetcher(
        {
            "https://www.bbc.com/z": Document(
                url="https://www.bbc.com/z", text="page", published_at=days_ago(1), fetched_at=NOW
            )
        }
    )
    out = await validate_sources(
        ClaimWork(text="f", hits=(undated_hit,)), deps_for(fetcher=fetcher)
    )
    assert out.sources[0].document.published_at == days_ago(1)
    st = ClaimWork(text="f", volatility=Volatility.STATIC, hits=(undated_hit,))
    assert (await validate_sources(st, deps_for(fetcher=fetcher))).sources == ()


# ---- stance + integrity --------------------------------------------------------------------
PAGE = (
    "As of February 2026, Priya Raman was appointed chief executive of Acme Corp "
    "after Jon Lee left."
)


def claim_with_source(
    text="Jon Lee is the chief executive of Acme Corp", tier_url="https://www.reuters.com/acme"
):
    doc = Document(url=tier_url, text=PAGE, published_at=days_ago(10), fetched_at=NOW)
    return ClaimWork(text=text, sources=(Source(document=doc, tier=classify_source(tier_url)),))


async def test_stance_downgrades_quoteless_and_offtopic():
    c = claim_with_source()
    llm = FakeLLM([{"items": [{"source": 1, "stance": "contradicts", "quote": None}]}])
    out = await compare_stance(c, deps_for(llm))
    assert out.evidence[0].stance == Stance.NEUTRAL
    off = claim_with_source(text="Zzz qqq")
    llm = FakeLLM(
        [
            {
                "items": [
                    {"source": 1, "stance": "supports", "quote": "Priya Raman was appointed chief"}
                ]
            }
        ]
    )
    assert (await compare_stance(off, deps_for(llm))).evidence[0].stance == Stance.NEUTRAL


async def test_stance_ignores_bad_source_numbers_and_flags_outage():
    c = claim_with_source()
    llm = FakeLLM([{"items": [{"source": 9, "stance": "supports", "quote": "x" * 30}]}])
    assert (await compare_stance(c, deps_for(llm))).evidence[0].stance == Stance.NEUTRAL
    out = await compare_stance(c, deps_for(FakeLLM([ProviderUnavailable("fake", "x")])))
    assert out.provider_failed and not out.evidence


async def test_integrity_keeps_only_verbatim_quotes():
    c = claim_with_source()
    url = c.sources[0].document.url

    def ev(quote):
        return Evidence(
            url=url,
            tier=c.sources[0].tier,
            published_at=days_ago(10),
            fetched_at=NOW,
            stance=Stance.CONTRADICTS,
            quoted_span=quote,
        )

    good = ev("Priya Raman was appointed chief executive of Acme Corp")
    cases = [
        good,
        ev("Priya Raman became chief executive of Acme Corp"),
        ev("short quote"),
        ev("Priya Raman was ... chief executive of Acme Corp"),
    ]
    out = check_quote_integrity(c.model_copy(update={"evidence": tuple(cases)}))
    assert len(out.evidence) == 1 and out.evidence[0].integrity_ok is True
    assert out.evidence[0].quoted_span == good.quoted_span


# ---- decide + correction + assemble --------------------------------------------------------
async def verified_stale_claim():
    c = claim_with_source()
    llm = FakeLLM(
        [
            {
                "items": [
                    {
                        "source": 1,
                        "stance": "contradicts",
                        "quote": "Priya Raman was appointed chief executive of Acme Corp",
                    }
                ]
            }
        ]
    )
    c = await compare_stance(c, deps_for(llm))
    return decide(check_quote_integrity(c), deps_for())


async def test_decide_stale_then_correction_grounded():
    c = await verified_stale_claim()
    assert c.verdict and c.verdict.label == Label.STALE
    ok = FakeLLM(
        [{"correction": "Priya Raman is the chief executive of Acme Corp.", "evidence": 1}]
    )
    assert (await suggest_correction(c, deps_for(ok))).correction.startswith("Priya Raman")
    for bad in (
        {"correction": "Priya Raman has led Acme Corp since 2019.", "evidence": 1},
        {"correction": "Maria Gomez is chief executive of Acme Corp.", "evidence": 1},
        {"correction": "Fine sentence.", "evidence": 5},
        {"correction": None, "evidence": None},
    ):
        assert (await suggest_correction(c, deps_for(FakeLLM([bad])))).correction is None


async def test_correction_skipped_unless_stale():
    c = claim_with_source()
    c = decide(c, deps_for())
    llm = FakeLLM([])
    assert (await suggest_correction(c, deps_for(llm))).correction is None and not llm.calls


async def test_assemble_labels_and_failure():
    stale = await verified_stale_claim()
    stale = stale.model_copy(
        update={"correction": "Priya Raman is the chief executive of Acme Corp."}
    )
    static = decide(
        ClaimWork(text="Python was created in 1991", volatility=Volatility.STATIC), deps_for()
    )
    res = assemble_result("r", [static, stale], NOW, NOW + timedelta(seconds=1))
    assert res.status == VerificationStatus.COMPLETED and res.label == Label.STALE
    assert res.suggested_correction and 0 < res.confidence <= 1
    empty = assemble_result("r", [], NOW, NOW)
    assert empty.label == Label.UNVERIFIABLE and empty.confidence == 0.0
    broken = decide(
        ClaimWork(text="f", provider_failed=True, queries=("q",), attempts=1), deps_for()
    )
    assert assemble_result("r", [broken], NOW, NOW).status == VerificationStatus.FAILED


def test_needs_reformulation_rules():
    assert needs_reformulation(ClaimWork(text="f", attempts=1))
    assert not needs_reformulation(ClaimWork(text="f", attempts=2))
    assert not needs_reformulation(ClaimWork(text="f", attempts=1, provider_failed=True))
    assert not needs_reformulation(ClaimWork(text="f", attempts=1, volatility=Volatility.STATIC))


_ = scripted_llm


def test_url_date_fallback_is_strict():
    from app.engine.nodes.sources import url_date

    assert url_date("https://www.npr.org/2021/11/30/1060035782/x").year == 2021
    assert url_date("https://example.com/news/2021/13/30/x") is None  # bad month
    assert url_date("https://example.com/item/20211130/1060035782") is None  # not segments
    assert url_date("https://www.bbc.com/news/world-asia-india-59472676") is None


async def test_sources_use_url_date_only_when_no_other_date():
    dated_by_url = hit("https://www.npr.org/2021/11/30/1/x", "npr text", age=None)
    with_hit_date = hit("https://www.npr.org/2021/11/30/2/y", "npr text 2", age=3)
    out = await validate_sources(
        ClaimWork(text="f", hits=(dated_by_url, with_hit_date)), deps_for()
    )
    by_url = {str(s.document.url): s.document.published_at for s in out.sources}
    assert by_url["https://www.npr.org/2021/11/30/1/x"].year == 2021
    assert by_url["https://www.npr.org/2021/11/30/2/y"] == days_ago(3)


def test_guard_never_leaves_office_holder_claims_static():
    """Benchmark c022: 'Queen Elizabeth II is the reigning British monarch' was classed static
    and passed as fresh without any search."""
    for text in (
        "Queen Elizabeth II is the reigning British monarch.",
        "Jerome Powell is the Chair of the Federal Reserve.",
        "Olaf Scholz is the Chancellor of Germany.",
        "Argentina is the reigning FIFA World Cup champion.",
        "Antony Blinken is the US Secretary of State.",
    ):
        assert guard(text, Volatility.STATIC, None, NOW)[0] == Volatility.SLOW, text


def test_guard_keeps_timeless_facts_static():
    for text in (
        "World War II ended in 1945.",
        "Water boils at 100 degrees Celsius at sea level.",
        "Python was created by Guido van Rossum.",
        "The chemical formula of water is H2O.",
    ):
        assert guard(text, Volatility.STATIC, None, NOW)[0] == Volatility.STATIC, text