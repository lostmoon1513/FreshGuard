"""Shapes the LLM must return. Lenient on purpose (defaults, no max lengths): the nodes clamp and
validate in code, so a slightly long string never throws away a whole reply."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.labels import Stance, Volatility


class ExtractedClaim(BaseModel):
    text: str
    answer_span: str = ""


class ExtractedClaims(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class VolatilityItem(BaseModel):
    index: int
    volatility: Volatility
    window_days: int | None = None
    reason: str = ""


class VolatilityBatch(BaseModel):
    items: list[VolatilityItem] = Field(default_factory=list)


class QueryItem(BaseModel):
    index: int
    queries: list[str] = Field(default_factory=list)


class QueryBatch(BaseModel):
    items: list[QueryItem] = Field(default_factory=list)


class StanceItem(BaseModel):
    source: int
    stance: Stance
    quote: str | None = None


class StanceBatch(BaseModel):
    items: list[StanceItem] = Field(default_factory=list)


class CorrectionOut(BaseModel):
    correction: str | None = None
    evidence: int | None = None