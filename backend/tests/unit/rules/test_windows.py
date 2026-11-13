from datetime import datetime, timedelta, timezone

import pytest

from app.engine.rules.windows import (
    DEFAULT_POLICY,
    FUTURE_TOLERANCE,
    FreshnessPolicy,
    Recency,
    classify_recency,
    evidence_age_days,
    freshness_window_days,
)
from app.schemas.labels import Volatility
from tests.unit.rules._factory import NOW, days_ago


def test_default_windows():
    assert freshness_window_days(Volatility.FAST) == 30
    assert freshness_window_days(Volatility.SLOW) == 365
    assert freshness_window_days(Volatility.STATIC) is None


def test_custom_policy_and_override():
    policy = FreshnessPolicy(fast_days=7, slow_days=90)
    assert freshness_window_days(Volatility.FAST, policy) == 7
    assert freshness_window_days(Volatility.SLOW, policy) == 90
    assert freshness_window_days(Volatility.FAST, policy, override=3) == 3
    assert freshness_window_days(Volatility.SLOW, override=10) == 10


def test_static_ignores_override():
    assert freshness_window_days(Volatility.STATIC, override=5) is None


@pytest.mark.parametrize("bad", [0, -1])
def test_override_must_be_positive(bad):
    with pytest.raises(ValueError):
        freshness_window_days(Volatility.FAST, override=bad)


@pytest.mark.parametrize("fast, slow", [(0, 10), (10, 5), (-1, 5)])
def test_policy_validates(fast, slow):
    with pytest.raises(ValueError):
        FreshnessPolicy(fast_days=fast, slow_days=slow)


def test_default_policy_is_the_documented_one():
    assert (DEFAULT_POLICY.fast_days, DEFAULT_POLICY.slow_days) == (30, 365)


def test_age_basic_and_undated():
    assert evidence_age_days(days_ago(10), NOW) == pytest.approx(10.0)
    assert evidence_age_days(None, NOW) is None


def test_age_is_timezone_independent():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert evidence_age_days(days_ago(2).astimezone(ist), NOW.astimezone(ist)) == pytest.approx(2)
    assert evidence_age_days(days_ago(2).astimezone(ist), NOW) == pytest.approx(2)


def test_future_dates():
    assert evidence_age_days(NOW + timedelta(hours=3), NOW) == 0.0  # clock skew
    assert evidence_age_days(NOW + FUTURE_TOLERANCE, NOW) == 0.0  # exactly at tolerance
    assert evidence_age_days(NOW + FUTURE_TOLERANCE + timedelta(seconds=1), NOW) is None
    assert evidence_age_days(NOW + timedelta(days=400), NOW) is None


def test_naive_datetimes_are_rejected():
    naive = datetime(2026, 1, 1)
    with pytest.raises(ValueError):
        evidence_age_days(days_ago(1), naive)
    with pytest.raises(ValueError):
        evidence_age_days(naive, NOW)
    with pytest.raises(ValueError):
        classify_recency(days_ago(1), naive, 30)


def test_recency_boundaries():
    assert classify_recency(days_ago(30), NOW, 30) == Recency.RECENT  # inclusive boundary
    assert classify_recency(days_ago(30.01), NOW, 30) == Recency.OLD
    assert classify_recency(days_ago(0), NOW, 30) == Recency.RECENT
    assert classify_recency(None, NOW, 30) == Recency.UNDATED
    assert classify_recency(NOW + timedelta(days=9), NOW, 30) == Recency.UNDATED


def test_no_window_means_everything_is_recent():
    assert classify_recency(days_ago(10_000), NOW, None) == Recency.RECENT
    assert classify_recency(None, NOW, None) == Recency.RECENT
    assert classify_recency(NOW + timedelta(days=99), NOW, None) == Recency.RECENT