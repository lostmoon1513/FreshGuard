"""Verification nodes: small async functions, one job each. M4 wires them into a LangGraph graph.

Nodes never import langgraph, app.api, app.db or app.services. They get their providers through
`Deps` and pass state as immutable `ClaimWork` records.
"""

from app.engine.nodes.assemble import assemble_result, fail_result
from app.engine.nodes.correction import suggest_correction
from app.engine.nodes.decide import decide
from app.engine.nodes.deps import Deps, Limits
from app.engine.nodes.extract import extract_claims
from app.engine.nodes.integrity import check_quote_integrity
from app.engine.nodes.queries import generate_queries
from app.engine.nodes.retrieve import retrieve_evidence
from app.engine.nodes.sources import validate_sources
from app.engine.nodes.stance import compare_stance
from app.engine.nodes.state import ClaimWork, Source, needs_reformulation, needs_search
from app.engine.nodes.volatility import classify_volatility

__all__ = [
    "ClaimWork",
    "Deps",
    "Limits",
    "Source",
    "assemble_result",
    "check_quote_integrity",
    "classify_volatility",
    "compare_stance",
    "decide",
    "extract_claims",
    "fail_result",
    "generate_queries",
    "needs_reformulation",
    "needs_search",
    "retrieve_evidence",
    "suggest_correction",
    "validate_sources",
]