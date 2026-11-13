import pytest
from pydantic import SecretStr

from app.api.errors import code_for_status, error_body, validation_message
from app.api.ratelimit import RateLimiter
from app.api.security import key_is_valid


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limiter_allows_up_to_limit_then_blocks_with_retry_after():
    clock = Clock()
    limiter = RateLimiter(3, 60, clock)
    assert [limiter.check("k") for _ in range(3)] == [None, None, None]
    clock.now += 10
    assert limiter.check("k") == 50
    assert limiter.check("other") is None  # keys are independent


def test_rate_limiter_window_slides():
    clock = Clock()
    limiter = RateLimiter(2, 60, clock)
    limiter.check("k")
    clock.now += 30
    limiter.check("k")
    clock.now += 31  # first hit is now 61 s old
    assert limiter.check("k") is None
    assert limiter.check("k") == 29


def test_rate_limiter_rejects_bad_config():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_key_validation():
    secret = SecretStr("s3cret")
    assert key_is_valid(secret, "s3cret")
    assert not key_is_valid(secret, "wrong")
    assert not key_is_valid(secret, None)
    assert not key_is_valid(secret, "")
    assert key_is_valid(None, None)  # auth disabled
    assert key_is_valid(SecretStr("  "), None)  # blank key = disabled


def test_error_helpers():
    assert error_body("not_found", "x") == {"error": {"code": "not_found", "message": "x"}}
    assert code_for_status(404) == "not_found" and code_for_status(503) == "internal_error"
    assert code_for_status(400) == "bad_request"
    msg = validation_message(
        [{"loc": ("body", "answer"), "msg": "Field required", "input": "SECRET", "type": "x"}]
    )
    assert msg == "answer: Field required" and "SECRET" not in msg
    assert validation_message([]) == "Invalid request."