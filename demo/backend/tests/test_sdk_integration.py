"""The demo's FreshGuard layer driven by the REAL `freshguard` SDK over a fake HTTP transport.

No network and no FreshGuard server needed: the SDK's own request building, response parsing and
error mapping all run for real; only the wire is replaced. Skipped if the SDK is not installed
(`pip install -e ../../sdk`).
"""
import pytest

pytest.importorskip("freshguard")

from fastapi.testclient import TestClient  # noqa: E402
from freshguard import ConnectionFailed, RateLimitError  # noqa: E402
from freshguard._core import Response  # noqa: E402

import app.main as main  # noqa: E402
from app.freshguard.badges import badge_from_verification  # noqa: E402
from app.freshguard.real_client import RealFreshGuard  # noqa: E402
from app.freshguard.service import MAX_TRANSIENT_POLL_FAILURES, FreshGuardService  # noqa: E402

COMPLETED_STALE = {
    "id": "job-1", "status": "completed", "label": "stale", "confidence": 0.81,
    "suggested_correction": "Priya Raman is the chief executive of Acme Corp.",
    "metadata": {"message_id": "m1"},
    "claims": [{
        "text": "Jon Lee is the chief executive of Acme Corp", "label": "stale", "volatility": "slow",
        "reasoning": "A credible, recent source contradicts the claim.",
        "evidence": [{"url": "https://www.reuters.com/acme", "tier": 2, "stance": "contradicts",
                      "quoted_span": "Priya Raman was appointed chief executive of Acme Corp"}],
    }],
}


class ScriptedTransport:
    """Replays scripted replies in order (a Response, or an exception to raise)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def request(self, method, url, *, headers, json=None, params=None, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def ok(body, status=200):
    return Response(status, body, {})


def err(status, code, message):
    return Response(status, {"error": {"code": code, "message": message}}, {})


def real(*replies):
    transport = ScriptedTransport(*replies)
    client = RealFreshGuard("http://fg.test", "secret-key", transport=transport)
    client._fg._sleep = lambda seconds: None  # skip the SDK's retry back-off delays
    return client, transport


def test_submit_sends_api_key_metadata_and_timestamp():
    client, transport = real(ok({"id": "job-1", "status": "pending"}, 202))
    job = client.submit("q?", "a.", {"message_id": "m1", "conversation_id": "c1"})
    assert job.id == "job-1" and job.status == "pending"
    call = transport.calls[0]
    assert call["method"] == "POST" and call["url"] == "http://fg.test/v1/verifications"
    assert call["headers"]["x-api-key"] == "secret-key"
    assert call["json"]["metadata"] == {"message_id": "m1", "conversation_id": "c1"}
    assert "answer_generated_at" in call["json"]


def test_sdk_verification_maps_to_stale_badge():
    client, _ = real(ok(COMPLETED_STALE))
    badge = badge_from_verification(client.get("job-1"))
    assert badge["state"] == "stale" and badge["color"] == "red"
    assert badge["suggested_correction"].startswith("Priya Raman")
    assert badge["source_url"] == "https://www.reuters.com/acme"
    assert badge["claims"][0]["evidence"][0]["stance"] == "contradicts"


def test_sdk_failed_job_shows_not_verified():
    client, _ = real(ok({"id": "job-1", "status": "failed", "error": "providers down"}))
    badge = badge_from_verification(client.get("job-1"))
    assert badge["state"] == "unavailable" and badge["text"] == "Not verified"
    assert badge["error"] == "providers down"


def test_full_flow_through_service():
    client, _ = real(
        ok({"id": "job-1", "status": "pending"}, 202),
        ok({"id": "job-1", "status": "running"}),
        ok(COMPLETED_STALE),
    )
    svc = FreshGuardService(client)
    svc.start("m1")
    svc.submit("m1", "Who runs Acme?", "Jon Lee.", "c1")
    assert svc.badge("m1")["state"] == "checking"
    assert svc.badge("m1")["state"] == "stale"


def test_submit_rejected_by_server_shows_reason_and_does_not_raise():
    client, _ = real(err(401, "unauthorized", "bad key"))
    svc = FreshGuardService(client)
    svc.start("m1")
    svc.submit("m1", "q", "a", "c1")  # must not raise
    badge = svc.badge("m1")
    assert badge["state"] == "unavailable" and badge["text"] == "Not verified"
    assert "AuthError" in badge["error"] and "secret-key" not in badge["error"]


def test_transient_poll_errors_keep_checking_then_give_up():
    client, _ = real(
        ok({"id": "job-1", "status": "pending"}, 202),
        *[ConnectionFailed("blip")] * (MAX_TRANSIENT_POLL_FAILURES * 3),  # reads are retried
    )
    svc = FreshGuardService(client)
    svc.start("m1")
    svc.submit("m1", "q", "a", "c1")
    for _ in range(MAX_TRANSIENT_POLL_FAILURES - 1):
        assert svc.badge("m1")["state"] == "checking"
    assert svc.badge("m1")["state"] == "unavailable"


def test_non_transient_poll_error_shows_not_verified_at_once():
    client, _ = real(
        ok({"id": "job-1", "status": "pending"}, 202),
        err(404, "not_found", "unknown id"),
    )
    svc = FreshGuardService(client)
    svc.start("m1")
    svc.submit("m1", "q", "a", "c1")
    assert svc.badge("m1")["state"] == "unavailable"


def test_rate_limit_is_treated_as_transient():
    assert RateLimitError in real(ok({}))[0].transient_errors


# ---- /freshguard/status ---------------------------------------------------------------------
def test_check_ok():
    client, _ = real(ok({"status": "ok"}), ok({"items": [], "next_before": None}))
    assert client.check() == {"reachable": True, "authenticated": True, "error": None}


def test_check_unreachable():
    # health() makes a single attempt (no retry)
    client, _ = real(ConnectionFailed("down"))
    out = client.check()
    assert out["reachable"] is False and out["authenticated"] is None


def test_check_wrong_api_key():
    client, _ = real(ok({"status": "ok"}), err(401, "unauthorized", "bad key"))
    out = client.check()
    assert out["reachable"] is True and out["authenticated"] is False
    assert "FRESHGUARD_API_KEY" in out["error"]


def test_status_endpoint_reports_real_mode_without_leaking_the_key(monkeypatch):
    client, _ = real(ok({"status": "ok"}), ok({"items": [], "next_before": None}))
    monkeypatch.setattr(main, "get_service", lambda: FreshGuardService(client))
    body = TestClient(main.app).get("/freshguard/status").json()
    assert body["mode"] == "real" and body["reachable"] is True and body["authenticated"] is True
    assert body["base_url"] == "http://fg.test" and body["sdk_version"]
    assert "secret-key" not in str(body)
