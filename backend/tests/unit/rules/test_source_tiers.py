import pytest
from pydantic import HttpUrl

from app.engine.rules.source_tiers import classify_source, extract_host, is_credible
from app.schemas.labels import SourceTier

T1, T2, T3 = SourceTier.TIER_1, SourceTier.TIER_2, SourceTier.TIER_3


@pytest.mark.parametrize(
    ("url", "tier"),
    [
        ("https://www.sec.gov/filing", T1),
        ("https://nist.gov", T1),
        ("https://www.gov.uk/vat-rates", T1),
        ("https://www.india.gov.in/x", T1),
        ("https://meity.nic.in", T1),
        ("https://who.int/news", T1),
        ("https://cs.stanford.edu/people", T1),
        ("https://www.ox.ac.uk", T1),
        ("https://www.w3.org/TR/html", T1),
        ("https://docs.un.org/en", T1),
        ("https://www.reuters.com/world/x", T2),
        ("https://en.wikipedia.org/wiki/Python", T2),
        ("https://www.bbc.co.uk/news", T2),
        ("https://randomblog.example.com/post", T3),
        ("https://medium.com/@someone/post", T3),
        ("https://github.com/org/repo", T3),
    ],
)
def test_known_domains(url, tier):
    assert classify_source(url) == tier


@pytest.mark.parametrize(
    "url",
    [
        "https://notgov.com",  # suffix lookalike, not a label boundary
        "https://gov.com",  # .com, not .gov
        "https://gov.evil.com",  # gov is a subdomain, not the TLD
        "https://evilreuters.com",
        "https://reuters.com.evil.io",
        "https://evil.com/reuters.com",  # domain in the path
        "https://evil.com/?u=https://www.sec.gov",
        "https://who.int.evil.com",
        "https://example.edu.evil.com",
        "https://user@bbc.com@evil.com/",  # userinfo trick: real host is evil.com
    ],
)
def test_lookalikes_are_tier3(url):
    assert classify_source(url) == T3


def test_case_port_trailing_dot_and_userinfo_are_normalised():
    assert classify_source("HTTPS://WWW.REUTERS.COM:443/x") == T2
    assert classify_source("https://sec.gov./x") == T1
    assert classify_source("https://anon:pw@sec.gov/x") == T1


@pytest.mark.parametrize(
    "url",
    [
        "", "   ", "not a url", "ftp://sec.gov/file", "file:///etc/passwd",
        "javascript:alert(1)", "https://", "http://[::1", "https://127.0.0.1/",
        "http://192.168.1.1/gov", "https://[2001:db8::1]/",
    ],
)  # fmt: skip
def test_garbage_and_ip_hosts_never_raise_and_are_tier3(url):
    assert classify_source(url) == T3


def test_accepts_pydantic_url_objects():
    assert classify_source(HttpUrl("https://www.reuters.com/x")) == T2


def test_extra_tier1_domains_promote_vendor_sites():
    url = "https://docs.python.org/3/whatsnew"
    assert classify_source(url) == T3
    assert classify_source(url, extra_tier1_domains=["python.org"]) == T1
    assert classify_source(url, extra_tier1_domains=[" PYTHON.ORG. "]) == T1
    assert classify_source("https://notpython.org", extra_tier1_domains=["python.org"]) == T3
    assert classify_source(url, extra_tier1_domains=["", "  "]) == T3


def test_extract_host():
    assert extract_host("https://A.b.com:8080/p?q#f") == "a.b.com"
    assert extract_host("ftp://a.com") is None
    assert extract_host("https://1.2.3.4") is None


def test_is_credible():
    assert is_credible(T1) and is_credible(T2) and not is_credible(T3)