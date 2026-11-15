import asyncio
from datetime import UTC, datetime, timedelta

from app.db.memory import InMemoryStore
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest, VerificationResult
from app.services.verification_service import INTERRUPTED, VerificationService
from tests.unit._factories import completed_result

NOW = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)
REQ = VerificationRequest(question="q?", answer="an answer", metadata={"message_id": "m1"})


def make_service(run, *, max_concurrent=2, store=None):
    store = store or InMemoryStore()
    return VerificationService(store, run, clock=lambda: NOW, max_concurrent=max_concurrent), store


async def ok_run(request, rid):
    return completed_result(rid, Label.STALE, correction="Priya Raman is the CEO.")


async def test_submit_returns_pending_immediately_then_completes():
    gate = asyncio.Event()

    async def run(request, rid):
        await gate.wait()
        return await ok_run(request, rid)

    service, _ = make_service(run)
    pending = await service.submit(REQ)
    assert pending.status == VerificationStatus.PENDING and pending.metadata == {"message_id": "m1"}
    await asyncio.sleep(0.05)
    assert (await service.get(pending.id)).status == VerificationStatus.RUNNING
    gate.set()
    done = await service.wait(pending.id, timeout=2)
    assert done.status == VerificationStatus.COMPLETED and done.label == Label.STALE
    assert done.id == pending.id and done.metadata == {"message_id": "m1"}
    assert done.suggested_correction == "Priya Raman is the CEO."


async def test_wait_times_out_with_current_state_and_job_continues():
    gate = asyncio.Event()

    async def run(request, rid):
        await gate.wait()
        return await ok_run(request, rid)

    service, _ = make_service(run)
    pending = await service.submit(REQ)
    early = await service.wait(pending.id, timeout=0.1)
    assert early.status in (VerificationStatus.PENDING, VerificationStatus.RUNNING)
    gate.set()
    assert (await service.wait(pending.id, timeout=2)).status == VerificationStatus.COMPLETED


async def test_wait_unknown_id_returns_none_and_finished_job_returns_at_once():
    service, _ = make_service(ok_run)
    assert await service.wait("nope", timeout=0.1) is None
    pending = await service.submit(REQ)
    await service.wait(pending.id, timeout=2)
    assert (await service.wait(pending.id, timeout=0.01)).status == VerificationStatus.COMPLETED


async def test_crashing_run_becomes_generic_failure():
    async def run(request, rid):
        raise RuntimeError("secret internal detail")

    service, _ = make_service(run)
    pending = await service.submit(REQ)
    result = await service.wait(pending.id, timeout=2)
    assert result.status == VerificationStatus.FAILED
    assert result.error == "Verification failed unexpectedly."
    assert "secret" not in result.model_dump_json()
    assert result.metadata == {"message_id": "m1"}


async def test_concurrency_is_limited():
    active = peak = 0

    async def run(request, rid):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return await ok_run(request, rid)

    service, _ = make_service(run, max_concurrent=2)
    jobs = [await service.submit(REQ) for _ in range(6)]
    for job in jobs:
        await service.wait(job.id, timeout=5)
    assert peak == 2


async def test_list_pages_with_cursor():
    ticks = iter(NOW + timedelta(seconds=i) for i in range(100))
    store = InMemoryStore()
    service = VerificationService(store, ok_run, clock=lambda: next(ticks), max_concurrent=5)
    ids = [(await service.submit(REQ)).id for _ in range(5)]
    for rid in ids:
        await service.wait(rid, timeout=2)
    page1, cursor = await service.list(limit=2)
    assert [r.id for r in page1] == ids[::-1][:2] and cursor == page1[-1].id
    page2, cursor2 = await service.list(limit=2, before=cursor)
    assert [r.id for r in page2] == ids[::-1][2:4] and cursor2 == page2[-1].id
    page3, cursor3 = await service.list(limit=2, before=cursor2)
    assert [r.id for r in page3] == ids[::-1][4:] and cursor3 is None
    stale, _ = await service.list(limit=10, label=Label.FRESH)
    assert stale == []


async def test_recover_fails_open_jobs():
    service, store = make_service(ok_run)
    from app.db.store import VerificationRecord

    pending = VerificationResult(id="old", status=VerificationStatus.RUNNING, created_at=NOW)
    await store.create(VerificationRecord(request=REQ, result=pending))
    assert await service.recover() == 1
    result = await service.get("old")
    assert result.status == VerificationStatus.FAILED and result.error == INTERRUPTED


async def test_shutdown_cancels_running_jobs_and_marks_failed():
    async def run(request, rid):
        await asyncio.sleep(60)

    service, _ = make_service(run)
    pending = await service.submit(REQ)
    await asyncio.sleep(0.05)
    await service.shutdown()
    result = await service.get(pending.id)
    assert result.status == VerificationStatus.FAILED


async def test_reverify_creates_a_new_linked_verification_and_keeps_history():
    service, store = make_service(ok_run)
    first = await service.submit(REQ)
    await service.wait(first.id, timeout=2)
    again = await service.reverify(first.id)
    assert again is not None and again.id != first.id
    assert again.metadata == {"message_id": "m1", "reverified_from": first.id}
    done = await service.wait(again.id, timeout=2)
    assert done.status == VerificationStatus.COMPLETED
    original = await service.get(first.id)
    assert original.metadata == {"message_id": "m1"}  # history untouched


async def test_reverify_unknown_id_is_none():
    service, _ = make_service(ok_run)
    assert await service.reverify("nope") is None


async def test_reverify_of_a_reverify_replaces_the_link_and_respects_metadata_limit():
    service, _ = make_service(ok_run)
    full = VerificationRequest(
        question="q?", answer="a", metadata={f"k{i}": "v" for i in range(20)}
    )
    first = await service.submit(full)
    await service.wait(first.id, timeout=2)
    second = await service.reverify(first.id)
    assert len(second.metadata) == 20 and second.metadata["reverified_from"] == first.id
    await service.wait(second.id, timeout=2)
    third = await service.reverify(second.id)
    assert len(third.metadata) == 20 and third.metadata["reverified_from"] == second.id