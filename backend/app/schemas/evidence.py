"""Evidence-related schemas."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.schemas.labels import SourceTier, Stance


class Document(BaseModel):
    """A page the system actually fetched. Quotes may only come from `text`."""

    model_config = ConfigDict(frozen=True)

    url: HttpUrl
    title: str | None = None
    text: str = Field(min_length=1)
    published_at: AwareDatetime | None = None
    modified_at: AwareDatetime | None = None  # page's own 'last updated'; see D38
    fetched_at: AwareDatetime


class Evidence(BaseModel):
    """One document's stance toward one claim, with the quote that justifies it."""

    url: HttpUrl
    tier: SourceTier
    published_at: AwareDatetime | None = None
    fetched_at: AwareDatetime
    stance: Stance
    quoted_span: str | None = None
    # None = integrity check not run yet; True/False = verbatim-quote check result.
    integrity_ok: bool | None = None

    @model_validator(mode="after")
    def _stance_needs_quote(self) -> Self:
        if self.stance in (Stance.SUPPORTS, Stance.CONTRADICTS) and not (
            self.quoted_span and self.quoted_span.strip()
        ):
            raise ValueError("A supporting or contradicting stance must include a quoted span.")
        return self