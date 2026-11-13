"""The same behaviour tests run against every store implementation."""

import importlib.util
from datetime import UTC, datetime, timedelta

import pytest

from app.db.memory import InMemoryStore
from app.db.store import VerificationRecord
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest, VerificationResult
from tests.unit._factories import completed_result

T0 = datetime(2026, 11, 13, 3, 0, tzinfo=UTC)
HAS_SQLALCHEMY = importlib.util.find_spec("sqlalchemy") is not None


@pytest.fixture(params=["memory", "sql"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryStore()
    if not HAS_SQLALCHEMY:
        pytest.skip("sqlalchemy not installed")
    from app.db.sql import SqlStore, make_engine

    s = SqlStore(make_engine(f"sqlite:///{tmp_path / 'test.db'}"))
    s.create_tables()
    return s


def record(rid: str, minutes: int = 0, **result_fields) -> VerificationRecord:
    fields = {
        "id": rid,
        "status": VerificationStatus.PENDING,
        "created_at": T0 + timedelta(minutes=minutes),
        "metadata": {"message_id": rid},
    }
    fields.update(result_fields)
    return VerificationRecord(
        request=VerificationRequest(question="q?", answer=f"answer {rid}", metadata={"m": rid}),
        result=VerificationResult(**fields),
    )


def completed(rid: str, label: Label, minutes: int = 0) -> VerificationResult:
    return completed_result(rid, label, created_at=T0 + timedelta(minutes=minutes))


async def test_create_get_roundtrip(store):
    await store.create(record("a"))
    got = await store.get("a")
    assert got is not None
    assert got.request.answer == "answer a" and got.request.metadata == {"m": "a"}
    assert got.result.status == VerificationStatus.PENDING
    assert got.result.created_at == T0
    assert await store.get("missing") is None


async def test_duplicate_id_rejected(store):
    await store.create(record("a"))
    with pytest.raises(ValueError):
        await store.create(record("a"))


async def test_save_result_replaces_result_but_keeps_request(store):
    await store.create(record("a"))
    assert await store.save_result(completed("a", Label.STALE)) is True
    got = await store.get("a")
    assert got.result.label == Label.STALE and got.result.status == VerificationStatus.COMPLETED
    assert got.request.answer == "answer a"
    assert await store.save_result(completed("zzz", Label.FRESH)) is False


async def test_list_orders_newest_first_and_pages(store):
    for i, rid in enumerate(["a", "b", "c", "d", "e"]):
        await store.create(record(rid, minutes=i))
    first = await store.list(limit=2)
    assert [r.result.id for r in first] == ["e", "d"]
    second = await store.list(limit=2, before="d")
    assert [r.result.id for r in second] == ["c", "b"]
    third = await store.list(limit=2, before="b")
    assert [r.result.id for r in third] == ["a"]
    assert await store.list(limit=2, before="unknown") == []


async def test_list_ties_break_by_id(store):
    for rid in ["a", "b", "c"]:
        await store.create(record(rid, minutes=0))
    assert [r.result.id for r in await store.list(limit=10)] == ["c", "b", "a"]
    assert [r.result.id for r in await store.list(limit=10, before="c")] == ["b", "a"]


async def test_list_filters_by_label(store):
    for i, (rid, label) in enumerate([("a", Label.STALE), ("b", Label.FRESH), ("c", Label.STALE)]):
        await store.create(record(rid, minutes=i))
        await store.save_result(completed(rid, label, minutes=i))
    stale = await store.list(limit=10, label=Label.STALE)
    assert [r.result.id for r in stale] == ["c", "a"]
    assert await store.list(limit=10, label=Label.POTENTIALLY_STALE) == []


async def test_fail_incomplete_only_touches_open_records(store):
    await store.create(record("open1"))
    await store.create(record("open2", status=VerificationStatus.RUNNING))
    await store.create(record("done"))
    await store.save_result(completed("done", Label.FRESH))
    when = T0 + timedelta(hours=1)
    assert await store.fail_incomplete("Interrupted by restart.", when) == 2
    for rid in ("open1", "open2"):
        r = (await store.get(rid)).result
        assert r.status == VerificationStatus.FAILED and r.error == "Interrupted by restart."
        assert r.finished_at == when and r.label is None
    assert (await store.get("done")).result.label == Label.FRESH
    assert await store.fail_incomplete("again", when) == 0