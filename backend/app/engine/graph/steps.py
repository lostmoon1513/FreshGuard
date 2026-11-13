"""Graph node functions and routers. Plain async code: no langgraph import, so it is unit-testable.

Each step receives the graph state (a dict) and returns a partial update. Claims are processed
in parallel with asyncio.gather inside a step (the 'fan-out per claim').
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypedDict

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
    needs_search,
    retrieve_evidence,
    suggest_correction,
    validate_sources,
)
from app.engine.providers.errors import ProviderError
from app.schemas.verification import VerificationResult

log = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    result_id: str
    question: str
    answer: str
    created_at: datetime
    claims: list[ClaimWork]
    error: str
    result: VerificationResult


async def _map(
    claims: list[ClaimWork],
    fn: Callable[[ClaimWork], Awaitable[ClaimWork]],
    pick: Callable[[ClaimWork], bool],
) -> list[ClaimWork]:
    """Apply `fn` concurrently to the claims that `pick` selects; others pass through."""
    done = await asyncio.gather(*(fn(c) if pick(c) else _same(c) for c in claims))
    return list(done)


async def _same(claim: ClaimWork) -> ClaimWork:
    return claim


class Steps:
    """Binds the nodes to one `Deps`. `build_graph` registers these by name."""

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    async def extract(self, state: GraphState) -> GraphState:
        try:
            claims = await extract_claims(state["question"], state["answer"], self.deps)
        except ProviderError as exc:
            # Provider errors never contain API keys (see providers/errors.py), so this is safe.
            log.warning("Claim extraction failed: %s", exc)
            return {"error": "The language model provider was unavailable."}
        return {"claims": claims}

    async def classify(self, state: GraphState) -> GraphState:
        return {"claims": await classify_volatility(state["claims"], self.deps)}

    async def queries(self, state: GraphState) -> GraphState:
        return {"claims": await generate_queries(state["claims"], self.deps)}

    async def retrieve(self, state: GraphState) -> GraphState:
        return {"claims": await self._retrieve(state["claims"], attempt=1)}

    async def validate(self, state: GraphState) -> GraphState:
        return {"claims": await self._validate(state["claims"], attempt=1)}

    async def reformulate(self, state: GraphState) -> GraphState:
        return {"claims": await generate_queries(state["claims"], self.deps, reformulate=True)}

    async def retrieve_retry(self, state: GraphState) -> GraphState:
        return {"claims": await self._retrieve(state["claims"], attempt=2)}

    async def validate_retry(self, state: GraphState) -> GraphState:
        return {"claims": await self._validate(state["claims"], attempt=2)}

    async def stance(self, state: GraphState) -> GraphState:
        claims = await _map(
            state["claims"], lambda c: compare_stance(c, self.deps), lambda c: bool(c.sources)
        )
        return {"claims": claims}

    async def integrity(self, state: GraphState) -> GraphState:
        return {"claims": [check_quote_integrity(c) for c in state["claims"]]}

    async def decide(self, state: GraphState) -> GraphState:
        return {"claims": [decide(c, self.deps) for c in state["claims"]]}

    async def correct(self, state: GraphState) -> GraphState:
        claims = await _map(
            state["claims"], lambda c: suggest_correction(c, self.deps), lambda c: True
        )
        return {"claims": claims}

    async def assemble(self, state: GraphState) -> GraphState:
        result = assemble_result(
            state["result_id"], state["claims"], state["created_at"], self.deps.clock()
        )
        return {"result": result}

    async def fail(self, state: GraphState) -> GraphState:
        error = state.get("error") or "Verification failed."
        return {
            "result": fail_result(state["result_id"], error, state["created_at"], self.deps.clock())
        }

    # ---- routers ---------------------------------------------------------------------------
    @staticmethod
    def after_extract(state: GraphState) -> str:
        if state.get("error"):
            return "fail"
        return "classify" if state.get("claims") else "assemble"

    @staticmethod
    def after_validate(state: GraphState) -> str:
        return "reformulate" if any(needs_reformulation(c) for c in state["claims"]) else "stance"

    # ---- helpers ---------------------------------------------------------------------------
    async def _retrieve(self, claims: list[ClaimWork], attempt: int) -> list[ClaimWork]:
        return await _map(
            claims,
            lambda c: retrieve_evidence(c, self.deps),
            lambda c: needs_search(c) and c.attempts == attempt,
        )

    async def _validate(self, claims: list[ClaimWork], attempt: int) -> list[ClaimWork]:
        return await _map(
            claims,
            lambda c: validate_sources(c, self.deps),
            lambda c: needs_search(c) and c.attempts == attempt,
        )