"""Request and result schemas for a verification."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.schemas.claim import ClaimVerdict
from app.schemas.labels import Label, VerificationStatus, worst_label

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Answer = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


MAX_METADATA_ITEMS = 20
MAX_METADATA_KEY = 64
MAX_METADATA_VALUE = 256


def _check_metadata(value: dict[str, str]) -> dict[str, str]:
    if len(value) > MAX_METADATA_ITEMS:
        raise ValueError(f"metadata allows at most {MAX_METADATA_ITEMS} entries.")
    for key, item in value.items():
        if not key or len(key) > MAX_METADATA_KEY:
            raise ValueError(f"metadata keys must be 1-{MAX_METADATA_KEY} characters.")
        if len(item) > MAX_METADATA_VALUE:
            raise ValueError(f"metadata values must be at most {MAX_METADATA_VALUE} characters.")
    return value


class VerificationRequest(BaseModel):
    question: Question
    answer: Answer
    answer_generated_at: AwareDatetime | None = None
    # Caller's own labels (e.g. a chat message id), stored and returned unchanged.
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _metadata_limits(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_metadata(value)


class VerificationResult(BaseModel):
    id: str
    status: VerificationStatus
    label: Label | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    claims: list[ClaimVerdict] = Field(default_factory=list)
    suggested_correction: str | None = None
    error: str | None = None
    created_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status == VerificationStatus.COMPLETED:
            if self.label is None:
                raise ValueError("A completed verification must have a label.")
            expected = worst_label(c.label for c in self.claims)
            if self.label != expected:
                raise ValueError(
                    f"Answer label '{self.label}' must equal the worst claim label '{expected}'."
                )
        if self.status == VerificationStatus.FAILED and not self.error:
            raise ValueError("A failed verification must carry an error message.")
        if self.suggested_correction and self.label != Label.STALE:
            raise ValueError("A correction can only be suggested for a STALE answer.")
        return self