"""Test matrix: one scenario per FreshGuard outcome, via the mock client + badge mapping."""
import pytest

from app.freshguard.badges import badge_from_verification
from app.freshguard.mock_client import MockFreshGuard
from app.freshguard.service import FreshGuardService

CASES = [
    # (question, answer, expected state, expected colour)
    ("What is the latest stable version of Python?", "The latest stable version of Python is 3.9.", "stale", "red"),
    ("What is the latest version of React?", "The latest stable React version is 17.", "stale", "red"),
    ("Who is the CEO of Twitter?", "Parag Agrawal is the CEO of Twitter.", "stale", "red"),
    ("Who is the CEO of Microsoft?", "Satya Nadella is the CEO of Microsoft.", "fresh", "green"),
    ("What is the capital of India?", "The capital of India is New Delhi.", "fresh", "green"),
    ("How much is the Acme Cloud Pro plan?", "The Acme Cloud Pro plan costs 49 dollars.", "potentially_stale", "amber"),
    ("When do Example University exams start?", "They begin on 15 March 2027.", "unverifiable", "grey"),
]


@pytest.mark.parametrize("question,answer,state,color", CASES)
def test_scenarios(question, answer, state, color):
    fg = MockFreshGuard(delay_seconds=0)
    job = fg.submit(question, answer, {"message_id": "m1"})
    badge = badge_from_verification(fg.get(job.id))
    assert badge["state"] == state
    assert badge["color"] == color


def test_stale_badge_has_correction_and_source():
    fg = MockFreshGuard(delay_seconds=0)
    job = fg.submit("latest python?", "The latest stable version of Python is 3.9.")
    badge = badge_from_verification(fg.get(job.id))
    assert badge["suggested_correction"]
    assert badge["source_url"].startswith("https://")


def test_non_stale_badges_have_no_correction():
    fg = MockFreshGuard(delay_seconds=0)
    job = fg.submit("capital?", "The capital of India is New Delhi.")
    badge = badge_from_verification(fg.get(job.id))
    assert badge["suggested_correction"] is None


def test_checking_then_completed():
    fg = MockFreshGuard(delay_seconds=0.4)
    job = fg.submit("q", "The capital of India is New Delhi.")
    assert badge_from_verification(fg.get(job.id))["state"] == "checking"
    import time
    time.sleep(0.5)
    assert badge_from_verification(fg.get(job.id))["state"] == "fresh"


def test_failed_run_shows_not_verified_badge():
    fg = MockFreshGuard(delay_seconds=0)
    job = fg.submit("simulate failure", "anything")
    badge = badge_from_verification(fg.get(job.id))
    assert badge["state"] == "unavailable"
    assert badge["text"] == "Not verified"
    assert badge["error"]


class ExplodingClient:
    def submit(self, **kwargs):
        raise ConnectionError("FreshGuard is down")

    def get(self, job_id):
        raise ConnectionError("FreshGuard is down")


def test_freshguard_down_never_breaks_chat():
    svc = FreshGuardService(ExplodingClient())
    svc.start("m1")
    assert svc.badge("m1")["state"] == "checking"
    svc.submit("m1", "q", "a", "c1")  # must not raise
    badge = svc.badge("m1")
    assert badge["state"] == "unavailable" and badge["text"] == "Not verified"
    assert "FreshGuard is down" in badge["error"]


def test_unknown_message_returns_none():
    svc = FreshGuardService(MockFreshGuard(0))
    assert svc.badge("nope") is None
