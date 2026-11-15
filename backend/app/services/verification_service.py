"""VerificationService: accepts requests, runs verifications in the background, stores results.

Responsibility: job lifecycle (pending -> running -> completed/failed) around a `run` callable.
It does not know how verification works (that is the engine) or how data is stored (a store).
Depends on: `app.db.store`, `app.schemas`, `app.logging`. The engine is injected as `run`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from app.db.store import VerificationRecord, VerificationStore
from app.logging import get_request_id, set_request_id
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest, VerificationResult

REVERIFIED_FROM = "reverified_from"
MAX_METADATA_KEYS = 20  # mirrors the schema limit

log = logging.getLogger(__name__)

RunFn = Callable[[VerificationRequest, str], Awaitable[VerificationResult]]
INTERRUPTED = "The server restarted before this verification finished. Please submit it again."
DONE = (VerificationStatus.COMPLETED, VerificationStatus.FAILED)
POLL_SECONDS = 0.5


class VerificationService:
    def __init__(
        self,
        store: VerificationStore,
        run: RunFn,
        *,
        clock: Callable[[], datetime],
        max_concurrent: int = 2,
    ) -> None:
        self._store = store
        self._run = run
        self._clock = clock
        self._slots = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task[None]] = set()
        self._finished: dict[str, asyncio.Event] = {}

    async def recover(self) -> int:
        """Call once at startup: jobs left open by a crash can never finish, so fail them."""
        count = await self._store.fail_incomplete(INTERRUPTED, self._clock())
        if count:
            log.warning("Marked %d interrupted verification(s) as failed", count)
        return count

    async def submit(self, request: VerificationRequest) -> VerificationResult:
        """Store a pending record and start the job. Returns immediately."""
        rid = uuid.uuid4().hex
        pending = VerificationResult(
            id=rid,
            status=VerificationStatus.PENDING,
            created_at=self._clock(),
            metadata=request.metadata,
        )
        await self._store.create(VerificationRecord(request=request, result=pending))
        self._finished[rid] = asyncio.Event()
        task = asyncio.create_task(
            self._execute(rid, request, pending.created_at, get_request_id())
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return pending

    async def reverify(self, result_id: str) -> VerificationResult | None:
        """Check the same question and answer again as a NEW verification (history is kept).
        The new record's metadata gets `reverified_from` = the original id. None if unknown."""
        record = await self._store.get(result_id)
        if record is None:
            return None
        metadata = {**record.request.metadata, REVERIFIED_FROM: result_id}
        if len(metadata) > MAX_METADATA_KEYS:  # keep the link, drop the oldest caller key
            drop = next(k for k in metadata if k != REVERIFIED_FROM)
            del metadata[drop]
        return await self.submit(record.request.model_copy(update={"metadata": metadata}))

    async def get(self, result_id: str) -> VerificationResult | None:
        record = await self._store.get(result_id)
        return record.result if record else None

    async def list(
        self, *, limit: int, label: Label | None = None, before: str | None = None
    ) -> tuple[list[VerificationResult], str | None]:
        """One page plus the cursor for the next page (None on the last page)."""
        records = await self._store.list(limit=limit + 1, label=label, before=before)
        page = [r.result for r in records[:limit]]
        next_before = page[-1].id if len(records) > limit else None
        return page, next_before

    async def wait(self, result_id: str, timeout: float) -> VerificationResult | None:
        """Wait up to `timeout` seconds for a job to finish; returns its latest state either way.
        None if the id is unknown."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        event = self._finished.get(result_id)
        while True:
            result = await self.get(result_id)
            if result is None or result.status in DONE:
                return result
            remaining = deadline - loop.time()
            if remaining <= 0:
                return result
            if event is not None:
                try:
                    await asyncio.wait_for(event.wait(), remaining)
                except TimeoutError:
                    pass
            else:  # job owned by another process: poll the store
                await asyncio.sleep(min(POLL_SECONDS, remaining))

    async def shutdown(self) -> None:
        """Cancel running jobs and mark them failed, so no record stays 'running' forever."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        await self._store.fail_incomplete(INTERRUPTED, self._clock())

    # ---- internals -------------------------------------------------------------------------
    async def _execute(
        self, rid: str, request: VerificationRequest, created_at: datetime, request_id: str
    ) -> None:
        set_request_id(request_id)
        try:
            async with self._slots:
                await self._set_running(rid)
                result = await self._run(request, rid)
            await self._store.save_result(
                result.model_copy(
                    update={"metadata": request.metadata, "id": rid, "created_at": created_at}
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Verification job crashed", extra={"verification_id": rid})
            await self._save_failure(rid, request)
        finally:
            event = self._finished.get(rid)
            if event is not None:
                event.set()
            # Keep the event briefly for late waiters; it is tiny, but do not grow forever.
            if len(self._finished) > 1000:
                self._finished = {k: v for k, v in self._finished.items() if not v.is_set()}

    async def _set_running(self, rid: str) -> None:
        current = await self.get(rid)
        if current is not None and current.status == VerificationStatus.PENDING:
            await self._store.save_result(
                current.model_copy(update={"status": VerificationStatus.RUNNING})
            )

    async def _save_failure(self, rid: str, request: VerificationRequest) -> None:
        current = await self.get(rid)
        created = current.created_at if current else self._clock()
        failed = VerificationResult(
            id=rid,
            status=VerificationStatus.FAILED,
            error="Verification failed unexpectedly.",
            created_at=created,
            finished_at=self._clock(),
            metadata=request.metadata,
        )
        try:
            await self._store.save_result(failed)
        except Exception:
            log.exception("Could not save failure", extra={"verification_id": rid})