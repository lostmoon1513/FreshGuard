from datetime import UTC, datetime, timedelta

from app.engine.nodes.sources import _with_credible_modified
from app.engine.providers.html_text import extract_page
from app.schemas.evidence import Document
from app.schemas.labels import SourceTier

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def doc(published=None, modified=None):
    return Document(url="https://example.org/a", text="Merz is chancellor of Germany.",
                    published_at=published, modified_at=modified, fetched_at=NOW)  # fmt: skip


def effective(document, tier):
    return _with_credible_modified(document, tier).published_at


def test_extracts_modified_from_meta_and_json_ld():
    meta = '<meta property="article:modified_time" content="2026-10-01T10:00:00Z"><p>Hello</p>'
    assert extract_page(meta, NOW).modified_at == datetime(2026, 10, 1, 10, tzinfo=UTC)
    ld = (
        '<script type="application/ld+json">'
        '{"dateModified":"2026-09-02","datePublished":"2001-01-01"}</script><p>x</p>'
    )
    page = extract_page(ld, NOW)
    assert page.published_at.year == 2001 and page.modified_at.month == 9


def test_no_modified_date_is_none():
    assert extract_page("<p>Hello world</p>", NOW).modified_at is None


def test_credible_source_uses_later_modified_date():
    modified = NOW - timedelta(days=20)
    for published in (None, datetime(2001, 1, 1, tzinfo=UTC)):
        assert effective(doc(published, modified), SourceTier.TIER_2) == modified


def test_tier3_never_uses_modified():
    out = _with_credible_modified(doc(None, NOW - timedelta(days=5)), SourceTier.TIER_3)
    assert out.published_at is None


def test_modified_not_used_when_older_future_or_absent():
    published = NOW - timedelta(days=3)
    assert (
        _with_credible_modified(
            doc(published, NOW - timedelta(days=9)), SourceTier.TIER_1
        ).published_at
        == published
    )
    assert effective(doc(None, NOW + timedelta(days=2)), SourceTier.TIER_1) is None
    assert effective(doc(None, None), SourceTier.TIER_1) is None