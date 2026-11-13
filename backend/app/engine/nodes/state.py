"""Working state of one claim as it moves through the verification nodes.

Every node is `(ClaimWork, deps) -> ClaimWork` (or a list-level equivalent) and returns an
updated copy; nothing is mutated. M4 wires these into a LangGraph graph.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.engine.providers.models import SearchHit
from app.engine.rules.decision import Decision
from app.schemas.claim import ClaimVerdict
from app.schemas.evidence import Document, Evidence
from app.schemas.labels import SourceTier, Volatility


class Source(BaseModel):
    """A validated page we hold the text of. Quotes may only come from `document.text`."""

    model_config = ConfigDict(frozen=True)

    document: Document
    tier: SourceTier
    from_fetch: bool = False


class ClaimWork(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    text: str
    answer_span: str | None = None
    volatility: Volatility = Volatility.SLOW
    window_days: int | None = None
    queries: tuple[str, ...] = ()
    attempts: int = 0  # query generations done: 1 after the first, 2 after the one reformulation
    hits: tuple[SearchHit, ...] = ()
    sources: tuple[Source, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    decision: Decision | None = None
    verdict: ClaimVerdict | None = None
    correction: str | None = None
    provider_failed: bool = False  # a provider outage (not "no evidence") blocked this claim
    notes: tuple[str, ...] = ()

    def noted(self, message: str) -> ClaimWork:
        return self.model_copy(update={"notes": (*self.notes, message)})


def needs_search(claim: ClaimWork) -> bool:
    """Static claims are not searched."""
    return claim.volatility != Volatility.STATIC


def needs_reformulation(claim: ClaimWork) -> bool:
    """True when the first search round left no usable source and nothing was broken.

    The graph reformulates at most once: a second failure ends in UNVERIFIABLE.
    """
    return (
        needs_search(claim)
        and claim.attempts == 1
        and not claim.sources
        and not claim.provider_failed
    )