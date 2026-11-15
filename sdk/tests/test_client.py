import pytest

from freshguard import (
    AuthError,
    ConnectionFailed,
    FreshGuard,
    FreshGuardError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    VerificationTimeout,
)
from tests._fakes import COMPLETED, DOWN, FAILED, PENDING, Clock, FakeTransport, err, ok


def make(*replies, **kw):
    clock = Clock()
    transport = FakeTransport(*replies)
    fg = FreshGuard(
        "http://api.test/",
        "key-1",
        transport=transport,
        sleep=clock.sleep,
        clock=clock,
        **kw,
    )
    return fg, transport, clock


def test_submit_sends_body_headers_and_returns_pending():
    fg, t, _ = make(ok(PENDING, 202))
    v = fg.submit("Q?", "A.", metadata={"message_id": 7})
    assert v.id == "abc123" and v.status == "pending"
    call = t.calls[0]
    assert call["method"] == "POST" and call["url"] == "http://api.test/v1/verifications"
    assert call["json"] == {"question": "Q?", "answer": "A.", "metadata": {"message_id": "7"}}
    assert call["headers"]["x-api-key"] == "key-1"


def test_no_api_key_sends_no_key_header():
    transport = FakeTransport(ok(PENDING, 202))
    FreshGuard("http://x", transport=transport).submit("Q?", "A.")
    assert "x-api-key" not in transport.calls[0]["headers"]


def test_submit_is_never_retried():
    fg, t, _ = make(err(500, "internal_error", "boom"), ok(PENDING, 202))
    with pytest.raises(ServerError):
        fg.submit("Q?", "A.")
    assert len(t.calls) == 1
    fg2, t2, _ = make(DOWN, ok(PENDING, 202))
    with pytest.raises(ConnectionFailed):
        fg2.submit("Q?", "A.")
    assert len(t2.calls) == 1


def test_local_validation_before_any_request():
    fg, t, _ = make()
    for q, a in [("", "A"), ("Q", "  "), (None, "A")]:
        with pytest.raises(ValidationError):
            fg.submit(q, a)
    assert t.calls == []


def test_get_retries_network_errors_and_5xx_then_succeeds():
    fg, t, clock = make(DOWN, err(503, "internal_error", "x"), ok(COMPLETED))
    v = fg.get("abc123")
    assert v.label == "stale" and len(t.calls) == 3
    assert clock.sleeps == [0.5, 1.0]


def test_get_gives_up_after_max_retries():
    fg, t, _ = make(DOWN, DOWN, DOWN, max_retries=2)
    with pytest.raises(ConnectionFailed):
        fg.get("abc123")
    assert len(t.calls) == 3
    fg2, t2, _ = make(
        err(500, "internal_error", "x"), err(500, "internal_error", "y"), max_retries=1
    )
    with pytest.raises(ServerError):
        fg2.get("abc123")
    assert len(t2.calls) == 2


def test_error_mapping():
    cases = [
        (err(401, "unauthorized", "Missing or invalid API key."), AuthError),
        (err(404, "not_found", "Verification not found."), NotFoundError),
        (err(422, "validation_error", "answer: too short"), ValidationError),
        (err(400, "bad_request", "odd"), FreshGuardError),
    ]
    for response, expected in cases:
        fg, _, _ = make(response)
        with pytest.raises(expected) as info:
            fg.get("x")
        assert info.value.status == response.status and info.value.code
    fg, _, _ = make(
        err(429, "rate_limited", "Too many requests.", retry_after="12", x_request_id="r1")
    )
    with pytest.raises(RateLimitError) as info:
        fg.get("x")
    assert info.value.retry_after == 12.0 and info.value.request_id == "r1"
    assert str(info.value) == "Too many requests."


def test_not_found_is_not_retried_and_non_json_is_server_error():
    fg, t, _ = make(err(404, "not_found", "x"), ok(None, 200))
    with pytest.raises(NotFoundError):
        fg.get("x")
    assert len(t.calls) == 1
    with pytest.raises(ServerError):
        fg.get("y")


def test_verify_uses_server_side_wait_and_returns_result():
    fg, t, _ = make(ok(COMPLETED, 200))
    v = fg.verify("Q?", "A.", wait_seconds=45)
    assert v.is_stale and v.suggested_correction
    call = t.calls[0]
    assert call["params"] == {"wait": "true", "timeout": 45}
    assert call["timeout"] >= 55  # HTTP timeout outlasts the server-side wait


def test_verify_returns_failed_job_without_raising():
    fg, _, _ = make(ok(FAILED, 200))
    v = fg.verify("Q?", "A.")
    assert v.status == "failed" and v.error


def test_verify_times_out_when_server_returns_202():
    fg, _, _ = make(ok(PENDING, 202))
    with pytest.raises(VerificationTimeout) as info:
        fg.verify("Q?", "A.", wait_seconds=30)
    assert info.value.verification_id == "abc123" and info.value.waited == 30


def test_verify_with_long_wait_submits_then_polls():
    fg, t, _ = make(ok(PENDING, 202), ok({**PENDING, "status": "running"}), ok(COMPLETED))
    v = fg.verify("Q?", "A.", wait_seconds=300)
    assert v.is_done and [c["method"] for c in t.calls] == ["POST", "GET", "GET"]
    assert "params" not in t.calls[0] or t.calls[0]["params"] is None


def test_wait_polls_until_done():
    fg, t, clock = make(
        ok({**PENDING, "status": "running"}), ok({**PENDING, "status": "running"}), ok(COMPLETED)
    )
    v = fg.wait("abc123", timeout=60, poll_interval=2.0)
    assert v.label == "stale" and clock.sleeps == [2.0, 2.0]


def test_wait_times_out_with_fake_clock():
    fg, _, clock = make(*[ok({**PENDING, "status": "running"}) for _ in range(10)])
    with pytest.raises(VerificationTimeout) as info:
        fg.wait("abc123", timeout=5, poll_interval=2.0)
    assert info.value.verification_id == "abc123" and clock.now >= 5


def test_list_parses_page_and_sends_filters():
    fg, t, _ = make(ok({"items": [COMPLETED, FAILED], "next_before": "zzz"}))
    page = fg.list(limit=2, label="stale", before="aaa")
    assert [v.status for v in page.items] == ["completed", "failed"] and page.next_before == "zzz"
    assert t.calls[0]["params"] == {"limit": 2, "label": "stale", "before": "aaa"}


def test_health_and_context_manager():
    fg, _, _ = make(ok({"status": "ok"}))
    assert fg.health() is True
    fg2, _, _ = make(DOWN)
    assert fg2.health() is False
    transport = FakeTransport()
    with FreshGuard("http://x", transport=transport):
        pass
    assert transport.closed is True


def test_reverify_posts_to_reverify_path_and_is_not_retried():
    fg, t, _ = make(ok(PENDING, 202))
    v = fg.reverify("abc123")
    assert v.status == "pending"
    call = t.calls[0]
    assert (
        call["method"] == "POST"
        and call["url"] == "http://api.test/v1/verifications/abc123/reverify"
    )
    fg2, t2, _ = make(err(500, "internal_error", "boom"), ok(PENDING, 202))
    with pytest.raises(ServerError):
        fg2.reverify("abc123")
    assert len(t2.calls) == 1


def test_reverify_unknown_id_raises_not_found():
    fg, _, _ = make(err(404, "not_found", "Verification not found."))
    with pytest.raises(NotFoundError):
        fg.reverify("nope")