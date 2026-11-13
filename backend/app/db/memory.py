"""In-memory store: for tests and throw-away local runs. Data is lost on restart."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.db.store import VerificationRecord, sort_key
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationResult

_OPEN = (VerificationStatus.PENDING, VerificationStatus.RUNNING)


class InMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, VerificationRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: VerificationRecord) -> None:
        async with self._lock:
            if record.result.id in self._records:
                raise ValueError("duplicate id")
            self._records[record.result.id] = record.model_copy(deep=True)

    async def save_result(self, result: VerificationResult) -> bool:
        async with self._lock:
            current = self._records.get(result.id)
            if current is None:
                return False
            self._records[result.id] = VerificationRecord(
                request=current.request, result=result.model_copy(deep=True)
            )
            return True

    async def get(self, result_id: str) -> VerificationRecord | None:
        record = self._records.get(result_id)
        return record.model_copy(deep=True) if record else None

    async def list(
        self, *, limit: int, label: Label | None = None, before: str | None = None
    ) -> list[VerificationRecord]:
        ordered = sorted(self._records.values(), key=sort_key, reverse=True)
        if before is not None:
            anchor = self._records.get(before)
            if anchor is None:
                return []
            ordered = [r for r in ordered if sort_key(r) < sort_key(anchor)]
        if label is not None:
            ordered = [r for r in ordered if r.result.label == label]
        return [r.model_copy(deep=True) for r in ordered[:limit]]

    async def fail_incomplete(self, error: str, finished_at: datetime) -> int:
        count = 0
        async with self._lock:
            for rid, record in list(self._records.items()):
                if record.result.status in _OPEN:
                    failed = record.result.model_copy(
                        update={
                            "status": VerificationStatus.FAILED,
                            "error": error,
                            "label": None,
                            "confidence": None,
                            "finished_at": finished_at,
                        }
                    )
                    self._records[rid] = VerificationRecord(request=record.request, result=failed)
                    count += 1
        return count