from datetime import UTC, datetime, timedelta

import pytest

from app.engine.providers.dates import parse_published_date

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-11-01", datetime(2026, 11, 1, tzinfo=UTC)),
        ("2026-11-01T10:30:00Z", datetime(2026, 11, 1, 10, 30, tzinfo=UTC)),
        ("2026-11-01T10:30:00+05:30", datetime(2026, 11, 1, 5, 0, tzinfo=UTC)),
        ("2026-11-01T10:30:00", datetime(2026, 11, 1, 10, 30, tzinfo=UTC)),  # naive = UTC
        ("Fri, 06 Nov 2026 09:00:00 GMT", datetime(2026, 11, 6, 9, 0, tzinfo=UTC)),
        ("Nov 5, 2026", datetime(2026, 11, 5, tzinfo=UTC)),
        ("November 5, 2026", datetime(2026, 11, 5, tzinfo=UTC)),
        ("Sept 3, 2025", datetime(2025, 9, 3, tzinfo=UTC)),
        ("Nov. 5, 2026", datetime(2026, 11, 5, tzinfo=UTC)),
        ("5 Nov 2026", datetime(2026, 11, 5, tzinfo=UTC)),
        ("5 November 2026", datetime(2026, 11, 5, tzinfo=UTC)),
        ("  Nov   5,   2026  ", datetime(2026, 11, 5, tzinfo=UTC)),
    ],
)
def test_absolute_dates(raw, expected):
    assert parse_published_date(raw, NOW) == expected


@pytest.mark.parametrize(
    ("raw", "delta"),
    [
        ("5 minutes ago", timedelta(minutes=5)),
        ("1 hour ago", timedelta(hours=1)),
        ("3 hours ago", timedelta(hours=3)),
        ("3 days ago", timedelta(days=3)),
        ("2 weeks ago", timedelta(weeks=2)),
        ("2 months ago", timedelta(days=90)),  # coarse unit: older end (N+1) x 30 days
        ("1 year ago", timedelta(days=730)),  # coarse unit: older end (N+1) x 365 days
        ("3 DAYS AGO", timedelta(days=3)),
    ],
)
def test_relative_dates(raw, delta):
    assert parse_published_date(raw, NOW) == NOW - delta


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "recently",
        "yesterday-ish",
        "Foo 5, 2026",
        "Feb 30, 2026",
        "13/45/2026",
        "soon",
        "99999999999 days ago",  # overflow, not a crash
    ],
)
def test_unreadable_dates_are_none_never_guessed(raw):
    assert parse_published_date(raw, NOW) is None


def test_future_dates_are_rejected_but_small_skew_is_allowed():
    assert parse_published_date("2027-01-01", NOW) is None
    assert parse_published_date("2026-11-11T20:00:00Z", NOW) is not None  # within a day


def test_naive_now_is_rejected():
    with pytest.raises(ValueError):
        parse_published_date("2026-11-01", datetime(2026, 11, 11))