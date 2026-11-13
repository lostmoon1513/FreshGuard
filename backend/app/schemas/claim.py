"""Claim schemas."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.schemas.evidence import Evidence
from app.schemas.labels import Label, Stance, Volatility

ClaimText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Claim(BaseModel):
    """An atomic, checkable statement extracted from an answer."""

    text: ClaimText


class ClaimVerdict(BaseModel):
    text: ClaimText
    volatility: Volatility
    label: Label
    reasoning: str = ""
    freshness_window_days: int | None = Field(default=None, ge=1)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _label_must_be_backed_by_evidence(self) -> Self:
        """Schema-level guard for 'never invent results'.

        STALE needs a verified contradicting quote. FRESH needs a verified supporting
        quote, except for static claims, which are not searched.
        """
        if self.label == Label.STALE and not self._has_verified(Stance.CONTRADICTS):
            raise ValueError("A STALE verdict needs at least one verified contradicting evidence.")
        if (
            self.label == Label.FRESH
            and self.volatility != Volatility.STATIC
            and not self._has_verified(Stance.SUPPORTS)
        ):
            raise ValueError(
                "A FRESH verdict on a non-static claim needs verified supporting evidence."
            )
        return self

    def _has_verified(self, stance: Stance) -> bool:
        return any(e.stance == stance and e.integrity_ok is True for e in self.evidence)
