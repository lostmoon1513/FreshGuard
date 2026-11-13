import importlib.util
import sys
import types

import pytest

from app.engine.graph import build_graph, verify
from app.engine.providers.errors import ProviderUnavailable
from app.engine.providers.fake import FakeFetcher, FakeSearch
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest
from tests.unit.graph import _stub_langgraph as stub
from tests.unit.nodes._runner import hit, make_deps, scripted_llm

ANSWER = "Jon Lee is the chief executive of Acme Corp."
CLAIM = "Jon Lee is the chief executive of Acme Corp"
QUOTE = "Priya Raman was appointed chief executive of Acme Corp"
PAGE = f"In February 2026, {QUOTE} after Jon Lee left the company."
REQUEST = VerificationRequest(question="Who runs Acme?", answer=ANSWER)
HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


@pytest.fixture(params=["stub", "real"])
def backend(request, monkeypatch):
    if request.param == "real":
        if not HAS_LANGGRAPH:
            pytest.skip("langgraph not installed")
        return "real"
    pkg = types.ModuleType("langgraph")
    mod = types.ModuleType("langgraph.graph")
    mod.START, mod.END, mod.StateGraph = stub.START, stub.END, stub.StateGraph
    monkeypatch.setitem(sys.modules, "langgraph", pkg)
    monkeypatch.setitem(sys.modules, "langgraph.graph", mod)
    return "stub"


def handlers(stance, queries=None):
    return {
        "ExtractedClaims": {"claims": [{"text": CLAIM, "answer_span": ANSWER}]},
        "VolatilityBatch": {"items": [{"index": 0, "volatility": "slow"}]},
        "QueryBatch": queries or [{"items": [{"index": 0, "queries": ["Acme Corp CEO"]}]}],
        "StanceBatch": stance,
        "CorrectionOut": {
            "correction": "Priya Raman is the chief executive of Acme Corp.",
            "evidence": 1,
        },
    }


async def run(backend, h, search, fetcher=None):
    deps = make_deps(scripted_llm(h), search, fetcher)
    return await verify(build_graph(deps), deps, REQUEST, result_id="r1")


async def test_stale(backend):
    search = FakeSearch({"Acme Corp CEO": [hit("https://www.reuters.com/a", PAGE, age=10)]})
    stance = {"items": [{"source": 1, "stance": "contradicts", "quote": QUOTE}]}
    res = await run(backend, handlers(stance), search)
    assert res.id == "r1" and res.status == VerificationStatus.COMPLETED
    assert res.label == Label.STALE and res.suggested_correction


async def test_reformulates_once_then_unverifiable(backend):
    search = FakeSearch({})
    queries = [
        {"items": [{"index": 0, "queries": ["first q"]}]},
        {"items": [{"index": 0, "queries": ["second q"]}]},
    ]
    res = await run(backend, handlers({"items": []}, queries), search)
    assert res.label == Label.UNVERIFIABLE and res.status == VerificationStatus.COMPLETED
    assert [q for q, _ in search.calls] == ["first q", "second q"]


async def test_second_round_finds_evidence(backend):
    search = FakeSearch({"second q": [hit("https://www.reuters.com/a", PAGE, age=3)]})
    queries = [
        {"items": [{"index": 0, "queries": ["first q"]}]},
        {"items": [{"index": 0, "queries": ["second q"]}]},
    ]
    stance = {"items": [{"source": 1, "stance": "contradicts", "quote": QUOTE}]}
    res = await run(backend, handlers(stance, queries), search)
    assert res.label == Label.STALE


async def test_no_claims_is_unverifiable(backend):
    h = handlers({"items": []})
    h["ExtractedClaims"] = {"claims": []}
    res = await run(backend, h, FakeSearch({}))
    assert res.status == VerificationStatus.COMPLETED and res.label == Label.UNVERIFIABLE
    assert res.claims == []


async def test_extraction_outage_fails(backend):
    h = handlers({"items": []})
    h["ExtractedClaims"] = ProviderUnavailable("fake", "down")
    res = await run(backend, h, FakeSearch({}))
    assert res.status == VerificationStatus.FAILED and res.error
    assert "down" not in res.error


async def test_search_outage_fails(backend):
    class Boom(FakeSearch):
        async def search(self, query, *, max_results):
            raise ProviderUnavailable("fake", "down")

    res = await run(backend, handlers({"items": []}), Boom(), FakeFetcher())
    assert res.status == VerificationStatus.FAILED


async def test_unexpected_crash_becomes_generic_failure(backend):
    h = handlers({"items": []})
    h["VolatilityBatch"] = lambda call: 1 / 0
    res = await run(backend, h, FakeSearch({}))
    assert res.status == VerificationStatus.FAILED
    assert res.error == "Verification failed unexpectedly."


def test_importing_engine_graph_does_not_import_langgraph():
    import app.engine.graph  # noqa: F401

    if not HAS_LANGGRAPH:
        assert "langgraph" not in sys.modules