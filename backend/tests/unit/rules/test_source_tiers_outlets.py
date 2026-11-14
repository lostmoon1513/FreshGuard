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