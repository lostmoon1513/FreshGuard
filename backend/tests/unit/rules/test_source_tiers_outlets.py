import pytest

from app.engine.rules.source_tiers import classify_source
from app.schemas.labels import SourceTier


@pytest.mark.parametrize(
    "url",
    ["https://www.cbsnews.com/news/x", "https://abcnews.go.com/a", "https://www.theverge.com/x"],
)
def test_major_outlets_are_tier_2(url):
    assert classify_source(url) == SourceTier.TIER_2


def test_lookalike_hosts_stay_tier_3():
    assert classify_source("https://cbsnews.com.evil.example/x") == SourceTier.TIER_3
    assert classify_source("https://notcbsnews.com/x") == SourceTier.TIER_3


@pytest.mark.parametrize(
    "url",
    [
        "https://m.economictimes.indiatimes.com/news/x",
        "https://www.moneycontrol.com/technology/x",
        "https://www.cnbc.com/2026/04/20/x.html",
        "https://techcrunch.com/2026/09/01/x",
    ],
)
def test_more_established_outlets_are_tier_2(url):
    assert classify_source(url) == SourceTier.TIER_2


def test_other_indiatimes_hosts_and_lookalikes_stay_tier_3():
    assert classify_source("https://blogs.indiatimes.com/x") == SourceTier.TIER_3
    assert classify_source("https://moneycontrol.com.fake.example/x") == SourceTier.TIER_3