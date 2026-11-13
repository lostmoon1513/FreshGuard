"""Parse publication dates from search providers. Pure: `now` is passed in.

Returns None whenever a date cannot be read with confidence. We never guess a date, because a
guessed date could make old evidence look recent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

_MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may", "may"), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "september", "sept"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}  # fmt: skip
_MDY = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$")
_DMY = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$")
_RELATIVE = re.compile(r"^(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$", re.IGNORECASE)
_UNIT_DAYS = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}
_FUTURE_TOLERANCE = timedelta(days=1)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def parse_published_date(raw: str | None, now: datetime) -> datetime | None:
    """ISO 8601, RFC 2822, 'Jan 5, 2025', '5 Jan 2025' and 'N units ago' (relative to `now`).

    'N months/years ago' is coarse (it means N to N+1 units), so we take the OLDER end: N+1 units
    of 30/365 days. Evidence can look older than it is, never newer. Naive dates are taken as UTC.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware.")
    if not raw or not raw.strip():
        return None
    text = " ".join(raw.split())

    parsed = _parse_absolute(text)
    if parsed is None:
        rel = _RELATIVE.match(text)
        if rel:
            amount, unit = int(rel.group(1)), rel.group(2).lower()
            if unit in ("month", "year"):
                amount += 1  # "N months ago" means N to N+1: take the older end, never the newer
            try:
                parsed = now - timedelta(days=amount * _UNIT_DAYS[unit])
            except OverflowError:
                return None
    if parsed is None:
        return None
    parsed = _aware(parsed)
    if parsed - now > _FUTURE_TOLERANCE:
        return None
    return parsed


def _parse_absolute(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        pass
    for pattern, order in ((_MDY, "mdy"), (_DMY, "dmy")):
        m = pattern.match(text)
        if not m:
            continue
        month_txt, day, year = (
            (m.group(1), m.group(2), m.group(3))
            if order == "mdy"
            else (m.group(2), m.group(1), m.group(3))
        )
        month = _MONTHS.get(month_txt.lower())
        if month is None:
            return None
        try:
            return datetime(int(year), month, int(day), tzinfo=UTC)
        except ValueError:
            return None
    return None