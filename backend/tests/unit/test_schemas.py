from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import (
    ClaimVerdict,
    Document,
    Evidence,
    Label,
    SourceTier,
    Stance,
    VerificationRequest,
    VerificationResult,
    VerificationStatus,
    Volatility,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def make_evidence(stance=Stance.SUPPORTS, quote="v5 was released", integrity_ok=True):
    return Evidence(
        url="https://example.com/changelog",
        tier=SourceTier.TIER_1,
        fetched_at=NOW,
        stance=stance,
        quoted_span=quote,
        integrity_ok=integrity_ok,
    )


# ---------- requests ----------


def test_request_strips_whitespace():
    req = VerificationRequest(question="  Who is CEO?  ", answer="  Alice  ")
    assert req.question == "Who is CEO?"
    assert req.answer == "Alice"


@pytest.mark.parametrize("field", ["question", "answer"])
def test_request_rejects_empty_text(field):
    data = {"question": "q", "answer": "a", field: "   "}
    with pytest.raises(ValidationError):
        VerificationRequest(**data)


def test_request_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        VerificationRequest(
            question="q", answer="a", answer_generated_at=datetime(2026, 1, 1)  # no tzinfo
        )


# ---------- documents and evidence ----------


def test_document_requires_text_and_valid_url():
    with pytest.raises(ValidationError):
        Document(url="https://example.com", text="", fetched_at=NOW)
    with pytest.raises(ValidationError):
        Document(url="not-a-url", text="hello", fetched_at=NOW)


@pytest.mark.parametrize("stance", [Stance.SUPPORTS, Stance.CONTRADICTS])
def test_stance_without_quote_is_rejected(stance):
    with pytest.raises(ValidationError):
        make_evidence(stance=stance, quote=None)
    with pytest.raises(ValidationError):
        make_evidence(stance=stance, quote="   ")


def test_neutral_evidence_needs_no_quote():
    assert make_evidence(stance=Stance.NEUTRAL, quote=None).quoted_span is None


# ---------- claim verdicts: no result without evidence ----------


def test_stale_requires_verified_contradicting_evidence():
    with pytest.raises(ValidationError):
        ClaimVerdict(text="c", volatility=Volatility.FAST, label=Label.STALE)
    with pytest.raises(ValidationError):  # supporting, not contradicting
        ClaimVerdict(
            text="c", volatility=Volatility.FAST, label=Label.STALE, evidence=[make_evidence()]
        )
    with pytest.raises(ValidationError):  # contradicting but quote not verified
        ClaimVerdict(
            text="c",
            volatility=Volatility.FAST,
            label=Label.STALE,
            evidence=[make_evidence(stance=Stance.CONTRADICTS, integrity_ok=False)],
        )
    ok = ClaimVerdict(
        text="c",
        volatility=Volatility.FAST,
        label=Label.STALE,
        evidence=[make_evidence(stance=Stance.CONTRADICTS)],
    )
    assert ok.label == Label.STALE


def test_fresh_non_static_requires_verified_supporting_evidence():
    with pytest.raises(ValidationError):
        ClaimVerdict(text="c", volatility=Volatility.SLOW, label=Label.FRESH)
    ok = ClaimVerdict(
        text="c", volatility=Volatility.SLOW, label=Label.FRESH, evidence=[make_evidence()]
    )
    assert ok.label == Label.FRESH


def test_fresh_static_needs_no_evidence():
    verdict = ClaimVerdict(text="c", volatility=Volatility.STATIC, label=Label.FRESH)
    assert verdict.evidence == []


@pytest.mark.parametrize("label", [Label.UNVERIFIABLE, Label.POTENTIALLY_STALE])
def test_uncertain_labels_do_not_need_evidence(label):
    assert ClaimVerdict(text="c", volatility=Volatility.FAST, label=label).label == label


# ---------- verification results ----------


def stale_claim():
    return ClaimVerdict(
        text="c",
        volatility=Volatility.FAST,
        label=Label.STALE,
        evidence=[make_evidence(stance=Stance.CONTRADICTS)],
    )


def test_completed_result_label_must_match_worst_claim():
    fresh_static = ClaimVerdict(text="d", volatility=Volatility.STATIC, label=Label.FRESH)
    ok = VerificationResult(
        id="v1",
        status=VerificationStatus.COMPLETED,
        label=Label.STALE,
        claims=[fresh_static, stale_claim()],
        created_at=NOW,
    )
    assert ok.label == Label.STALE
    with pytest.raises(ValidationError):
        VerificationResult(
            id="v1",
            status=VerificationStatus.COMPLETED,
            label=Label.FRESH,
            claims=[fresh_static, stale_claim()],
            created_at=NOW,
        )


def test_completed_result_without_claims_must_be_unverifiable():
    ok = VerificationResult(
        id="v1", status=VerificationStatus.COMPLETED, label=Label.UNVERIFIABLE, created_at=NOW
    )
    assert ok.claims == []
    with pytest.raises(ValidationError):
        VerificationResult(
            id="v1", status=VerificationStatus.COMPLETED, label=Label.FRESH, created_at=NOW
        )


def test_completed_result_requires_label():
    with pytest.raises(ValidationError):
        VerificationResult(id="v1", status=VerificationStatus.COMPLETED, created_at=NOW)


def test_failed_result_requires_error():
    with pytest.raises(ValidationError):
        VerificationResult(id="v1", status=VerificationStatus.FAILED, created_at=NOW)
    assert VerificationResult(
        id="v1", status=VerificationStatus.FAILED, error="search provider down", created_at=NOW
    ).error


def test_correction_only_allowed_for_stale_answers():
    with pytest.raises(ValidationError):
        VerificationResult(
            id="v1",
            status=VerificationStatus.COMPLETED,
            label=Label.UNVERIFIABLE,
            suggested_correction="It is now X.",
            created_at=NOW,
        )
    ok = VerificationResult(
        id="v1",
        status=VerificationStatus.COMPLETED,
        label=Label.STALE,
        claims=[stale_claim()],
        suggested_correction="It is now X.",
        created_at=NOW,
    )
    assert ok.suggested_correction


def test_confidence_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        VerificationResult(
            id="v1",
            status=VerificationStatus.PENDING,
            confidence=1.5,
            created_at=NOW,
        )
