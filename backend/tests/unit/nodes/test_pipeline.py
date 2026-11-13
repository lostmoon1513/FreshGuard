"""End-to-end (sequential) scenarios with fakes; M4 will run the same nodes in LangGraph."""

from app.engine.providers.errors import ProviderUnavailable
from app.engine.providers.fake import FakeFetcher, FakeSearch
from app.schemas.labels import Label, VerificationStatus
from tests.unit.nodes._runner import hit, make_deps, run_pipeline, scripted_llm

ANSWER = "Jon Lee is the chief executive of Acme Corp."
QUOTE = "Priya Raman was appointed chief executive of Acme Corp"
PAGE = f"In February 2026, {QUOTE} after Jon Lee left the company."


def llm(stance_item, queries=None):
    return scripted_llm(
        {
            "ExtractedClaims": {
                "claims": [
                    {"text": "Jon Lee is the chief executive of Acme Corp", "answer_span": ANSWER}
                ]
            },
            "VolatilityBatch": {"items": [{"index": 0, "volatility": "slow"}]},
            "QueryBatch": queries or [{"items": [{"index": 0, "queries": ["Acme Corp CEO"]}]}],
            "StanceBatch": stance_item,
            "CorrectionOut": {
                "correction": "Priya Raman is the chief executive of Acme Corp.",
                "evidence": 1,
            },
        }
    )


async def test_stale_end_to_end():
    search = FakeSearch({"Acme Corp CEO": [hit("https://www.reuters.com/acme", PAGE, age=10)]})
    stance = {"items": [{"source": 1, "stance": "contradicts", "quote": QUOTE}]}
    res = await run_pipeline("Who runs Acme?", ANSWER, make_deps(llm(stance), search))
    assert res.status == VerificationStatus.COMPLETED and res.label == Label.STALE
    assert res.suggested_correction and res.claims[0].evidence[0].integrity_ok is True


async def test_fabricated_quote_is_not_stale():
    search = FakeSearch({"Acme Corp CEO": [hit("https://www.reuters.com/acme", PAGE, age=10)]})
    stance = {
        "items": [
            {
                "source": 1,
                "stance": "contradicts",
                "quote": "Jon Lee was fired from Acme Corp yesterday",
            }
        ]
    }
    res = await run_pipeline("q", ANSWER, make_deps(llm(stance), search))
    assert res.label == Label.UNVERIFIABLE and res.suggested_correction is None


async def test_no_evidence_reformulates_once_then_unverifiable():
    search = FakeSearch({})
    queries = [
        {"items": [{"index": 0, "queries": ["first q"]}]},
        {"items": [{"index": 0, "queries": ["second q"]}]},
    ]
    res = await run_pipeline("q", ANSWER, make_deps(llm({"items": []}, queries), search))
    assert res.label == Label.UNVERIFIABLE and res.status == VerificationStatus.COMPLETED
    assert [q for q, _ in search.calls] == ["first q", "second q"]


async def test_static_claim_never_searched():
    handlers = {
        "ExtractedClaims": {
            "claims": [
                {"text": "Python was created in 1991", "answer_span": "Python was created in 1991"}
            ]
        },
        "VolatilityBatch": {"items": [{"index": 0, "volatility": "static"}]},
    }
    search = FakeSearch({})
    res = await run_pipeline(
        "q", "Python was created in 1991", make_deps(scripted_llm(handlers), search)
    )
    assert res.label == Label.FRESH and search.calls == []


async def test_provider_outage_fails_run():
    class Boom(FakeSearch):
        async def search(self, query, *, max_results):
            raise ProviderUnavailable("fake", "down")

    res = await run_pipeline("q", ANSWER, make_deps(llm({"items": []}), Boom(), FakeFetcher()))
    assert res.status == VerificationStatus.FAILED and res.error