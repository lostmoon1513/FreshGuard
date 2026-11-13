import asyncio

import pytest

from app.engine.providers.errors import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.engine.providers.http import (
    HttpTransportError,
    RetryPolicy,
    classify_response,
    post_json_with_retry,
)
from tests.unit.providers._helpers import FakeHttp, Sleeper, ok, status

SECRET = "sk-super-secret-key"


def call(http, sleeper=None, retry=None, quota=frozenset()):
    sleeper = sleeper or Sleeper()
    retry = retry or RetryPolicy()
    return asyncio.run(
        post_json_with_retry(
            http,
            provider="t",
            url="https://x.test/api",
            headers={"authorization": f"Bearer {SECRET}"},
            body={"q": 1},
            timeout=5.0,
            retry=retry,
            quota_statuses=quota,
            sleep=sleeper,
        )
    )


def test_success_returns_parsed_json_and_passes_request_through():
    http = FakeHttp(ok({"a": 1}))
    assert call(http) == {"a": 1}
    assert http.calls == [
        {
            "url": "https://x.test/api",
            "headers": {"authorization": f"Bearer {SECRET}"},
            "body": {"q": 1},
            "timeout": 5.0,
        }
    ]


@pytest.mark.parametrize(("code", "exc"), [(401, ProviderAuthError), (403, ProviderAuthError)])
def test_auth_errors_are_not_retried(code, exc):
    http, sleeper = FakeHttp(status(code)), Sleeper()
    with pytest.raises(exc):
        call(http, sleeper)
    assert len(http.calls) == 1 and sleeper.delays == []


def test_quota_status_only_when_declared():
    with pytest.raises(ProviderQuotaExceeded):
        call(FakeHttp(status(432)), quota=frozenset({432, 433}))
    with pytest.raises(ProviderBadResponse):  # undeclared: just a rejected request
        call(FakeHttp(status(432)))


def test_429_uses_retry_after_then_succeeds():
    http, sleeper = FakeHttp(status(429, headers={"Retry-After": "2"}), ok({"ok": True})), Sleeper()
    assert call(http, sleeper) == {"ok": True}
    assert sleeper.delays == [2.0]


def test_429_without_header_backs_off_exponentially():
    http = FakeHttp(status(429), status(429), ok({"ok": 1}))
    sleeper = Sleeper()
    assert call(http, sleeper) == {"ok": 1}
    assert sleeper.delays == [0.5, 1.0]


def test_429_with_very_long_retry_after_fails_fast_so_fallback_can_take_over():
    http, sleeper = FakeHttp(status(429, headers={"retry-after": "120"})), Sleeper()
    with pytest.raises(ProviderRateLimited) as info:
        call(http, sleeper)
    assert info.value.retry_after == 120.0
    assert len(http.calls) == 1 and sleeper.delays == []


def test_5xx_retries_then_gives_up():
    http, sleeper = FakeHttp(status(500), status(502), status(503)), Sleeper()
    with pytest.raises(ProviderUnavailable):
        call(http, sleeper)
    assert len(http.calls) == 3 and sleeper.delays == [0.5, 1.0]


def test_transport_error_is_retried():
    http = FakeHttp(HttpTransportError("request timed out"), ok({"ok": 1}))
    assert call(http) == {"ok": 1}


def test_transport_error_exhausts_attempts():
    http = FakeHttp(*[HttpTransportError("down")] * 3)
    with pytest.raises(ProviderUnavailable, match="network error"):
        call(http)


def test_other_4xx_is_a_bad_response_not_retried_and_body_is_truncated():
    http = FakeHttp(status(400, body="x" * 5000))
    with pytest.raises(ProviderBadResponse) as info:
        call(http)
    assert len(http.calls) == 1 and len(str(info.value)) < 400


def test_non_json_success_body_is_bad_response():
    http = FakeHttp(status(200, body="<html>oops</html>"))
    with pytest.raises(ProviderBadResponse, match="not valid JSON"):
        call(http)


def test_single_attempt_policy_never_sleeps():
    http, sleeper = FakeHttp(status(500)), Sleeper()
    with pytest.raises(ProviderUnavailable):
        call(http, sleeper, retry=RetryPolicy(max_attempts=1))
    assert sleeper.delays == []


def test_backoff_is_capped():
    p = RetryPolicy(base_delay=1, max_delay=4)
    assert [p.backoff(n) for n in (1, 2, 3, 4, 5)] == [1, 2, 4, 4, 4]


@pytest.mark.parametrize("kwargs", [{"max_attempts": 0}, {"base_delay": -1}, {"max_delay": -1}])
def test_retry_policy_validates(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


@pytest.mark.parametrize(
    "reply",
    [status(401), status(403), status(429), status(432), status(500), status(400, body=SECRET)],
)
def test_errors_never_contain_the_api_key(reply):
    # Even if an upstream error body echoed something, the key we sent is only in headers.
    err = classify_response("t", reply, frozenset({432}))
    assert isinstance(err, ProviderError)
    assert "Bearer" not in str(err)


def test_classify_success_is_none():
    assert classify_response("t", status(204)) is None