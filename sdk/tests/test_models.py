from datetime import timezone

from freshguard import Verification
from tests._fakes import COMPLETED, FAILED, PENDING


def test_parses_a_full_result():
    v = Verification.from_dict(COMPLETED)
    assert v.id == "abc123" and v.status == "completed" and v.label == "stale"
    assert v.confidence == 0.81 and v.metadata == {"message_id": "m-7"}
    assert v.created_at.tzinfo is not None and v.created_at.utcoffset().total_seconds() == 0
    assert v.finished_at.astimezone(timezone.utc).second == 24
    claim = v.claims[0]
    assert claim.label == "stale" and claim.freshness_window_days == 365
    ev = claim.evidence[0]
    assert ev.stance == "contradicts" and ev.tier == 2 and ev.integrity_ok is True
    assert ev.quoted_span.startswith("Priya Raman") and ev.published_at.year == 2026


def test_helpers():
    v = Verification.from_dict(COMPLETED)
    assert v.is_done and v.is_stale and v.should_warn
    pending = Verification.from_dict(PENDING)
    assert not pending.is_done and not pending.should_warn and pending.label is None
    failed = Verification.from_dict(FAILED)
    assert failed.is_done and failed.error and not failed.should_warn
    maybe = Verification.from_dict({**COMPLETED, "label": "potentially_stale"})
    assert maybe.should_warn and not maybe.is_stale
    fresh = Verification.from_dict({**COMPLETED, "label": "fresh"})
    assert not fresh.should_warn


def test_tolerates_missing_and_unknown_fields():
    v = Verification.from_dict(
        {"id": "x", "status": "completed", "future_field": 1, "claims": None}
    )
    assert v.claims == () and v.metadata == {} and v.created_at is None
    bad_date = Verification.from_dict({"id": "x", "status": "pending", "created_at": "garbage"})
    assert bad_date.created_at is None