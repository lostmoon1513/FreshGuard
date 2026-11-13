"""Storage interface for verifications. Imports `app.schemas` only.

A record is the caller's request plus the current result. Stores never run verification and
never decide labels; they only persist what the service gives them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.schemas.labels import Label
from app.schemas.verification import VerificationRequest, VerificationResult


class VerificationRecord(BaseModel):
    request: VerificationRequest
    result: VerificationResult


class VerificationStore(Protocol):
    async def create(self, record: VerificationRecord) -> None:
        """Insert a new record. Raises ValueError if the id already exists."""
        ...

    async def save_result(self, result: VerificationResult) -> bool:
        """Replace the result of an existing record. False if the id is unknown."""
        ...

    async def get(self, result_id: str) -> VerificationRecord | None: ...

    async def list(
        self, *, limit: int, label: Label | None = None, before: str | None = None
    ) -> list[VerificationRecord]:
        """Newest first. `before` = id of the last item of the previous page (exclusive).
        An unknown `before` id yields an empty page."""
        ...

    async def fail_incomplete(self, error: str, finished_at: datetime) -> int:
        """Mark every pending/running record FAILED (used after a server restart). Returns count."""
        ...


def sort_key(record: VerificationRecord) -> tuple[int, str]:
    """Ordering shared by all stores: creation time (microseconds), then id."""
    return epoch_us(record.result.created_at), record.result.id


def epoch_us(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000)