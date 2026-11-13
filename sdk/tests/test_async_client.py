import pytest

from freshguard import AsyncFreshGuard, ConnectionFailed, NotFoundError, VerificationTimeout
from tests._fakes import (
    COMPLETED,
    DOWN,
    PENDING,
    Clock,
    FakeAsyncTransport,
    err,
    ok,
)


def make(*replies, **kw):
    clock = Clock()
    transport = FakeAsyncTransport(*replies)
    fg = AsyncFreshGuard(
        "http://api.test", "key-1", transport=transport, sleep=clock.asleep, clock=clock, **kw
    )
    return fg, transport, clock


async def test_submit_and_get():
    fg, t, _ = make(ok(PENDING, 202), ok(COMPLETED))
    pending = await fg.submit("Q?", "A.", metadata={"m": "1"})
    assert pending.status == "pending"
    assert t.calls[0]["json"]["metadata"] == {"m": "1"}
    assert (await fg.get("abc123")).is_stale


async def test_get_retries_then_raises_mapped_errors():
    fg, t, clock = make(DOWN, ok(COMPLETED))
    assert (await fg.get("abc123")).label == "stale" and clock.sleeps == [0.5]
    fg2, _, _ = make(err(404, "not_found", "x"))
    with pytest.raises(NotFoundError):
        await fg2.get("x")
    fg3, _, _ = make(DOWN, DOWN, DOWN)
    with pytest.raises(ConnectionFailed):
        await fg3.get("x")


async def test_verify_and_timeout():
    fg, t, _ = make(ok(COMPLETED, 200))
    v = await fg.verify("Q?", "A.", wait_seconds=30)
    assert v.is_done and t.calls[0]["params"] == {"wait": "true", "timeout": 30}
    fg2, _, _ = make(ok(PENDING, 202))
    with pytest.raises(VerificationTimeout):
        await fg2.verify("Q?", "A.", wait_seconds=10)


async def test_wait_polls_and_times_out():
    fg, _, clock = make(ok({**PENDING, "status": "running"}), ok(COMPLETED))
    assert (await fg.wait("abc123")).is_done and clock.sleeps == [2.0]
    fg2, _, _ = make(*[ok({**PENDING, "status": "running"}) for _ in range(10)])
    with pytest.raises(VerificationTimeout):
        await fg2.wait("abc123", timeout=3, poll_interval=2.0)


async def test_list_health_and_context_manager():
    fg, _, _ = make(ok({"items": [COMPLETED], "next_before": None}), ok({"status": "ok"}))
    page = await fg.list(limit=5)
    assert len(page.items) == 1 and page.next_before is None
    assert await fg.health() is True
    transport = FakeAsyncTransport()
    async with AsyncFreshGuard("http://x", transport=transport):
        pass
    assert transport.closed is True