"""Source tiering: how much do we trust a URL's domain?

Responsibility: map a URL to a `SourceTier`. Pure and deterministic; no network, no LLM.
Inputs: a URL (str or pydantic `Url`), optional per-claim extra tier-1 domains.
Outputs: `SourceTier`.
Dependencies: `app.schemas` only.

Tiers (see `SourceTier`): 1 = official/primary, 2 = reputable secondary, 3 = everything else.

Known limitation: tiering is by domain only. A student page on a university host is still tier 1,
and a vendor's own docs are tier 3 unless the caller passes the vendor's domain in
`extra_tier1_domains` (a later graph node can do that when the claim names the vendor).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

from app.schemas.labels import SourceTier

# Suffixes: "gov" matches any host whose last label is "gov"; "gov.uk" matches *.gov.uk, etc.
TIER1_SUFFIXES: frozenset[str] = frozenset(
    {
        # governments and militaries
        "gov", "mil", "gov.uk", "gov.in", "nic.in", "gov.au", "gc.ca", "gouv.fr",
        "europa.eu", "go.jp", "gov.sg", "gov.za",
        # intergovernmental organisations (the .int TLD)
        "int",
        # academia
        "edu", "ac.uk", "ac.in", "edu.in", "edu.au", "ac.jp",
    }
)  # fmt: skip

# Exact registrable domains (and their subdomains) that are primary/standards sources.
TIER1_DOMAINS: frozenset[str] = frozenset(
    {"un.org", "worldbank.org", "imf.org", "oecd.org", "w3.org", "ietf.org", "iso.org"}
)

TIER2_DOMAINS: frozenset[str] = frozenset(
    {
        "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com", "wsj.com",
        "ft.com", "bloomberg.com", "theguardian.com", "washingtonpost.com", "economist.com",
        "npr.org", "thehindu.com", "indianexpress.com", "nature.com", "science.org",
        "arstechnica.com", "wikipedia.org", "britannica.com", "cbsnews.com", "nbcnews.com",
        "abcnews.go.com", "cnn.com", "aljazeera.com", "dw.com", "theverge.com",
        # more established newsrooms (Indian and international)
        "economictimes.indiatimes.com", "timesofindia.indiatimes.com", "hindustantimes.com",
        "ndtv.com", "livemint.com", "moneycontrol.com", "business-standard.com", "cnbc.com",
        "forbes.com", "businessinsider.com", "techcrunch.com", "wired.com", "time.com",
        "usatoday.com", "latimes.com", "politico.com", "axios.com", "euronews.com",
        "france24.com", "scmp.com", "abc.net.au", "cbc.ca", "variety.com",
        # vendors speaking about their own products (python.org, Microsoft docs, ...)
        "python.org", "microsoft.com", "openai.com", "anthropic.com", "apple.com",
    }
)  # fmt: skip


def _matches(host: str, domain: str) -> bool:
    """True if `host` is `domain` or a subdomain of it (label-boundary match)."""
    return host == domain or host.endswith("." + domain)


def extract_host(url: object) -> str | None:
    """Lower-cased hostname of `url`, or None if there is no usable host.

    Only http(s) URLs have a usable host. IP literals return None so they can never match a
    domain list. Never raises on malformed input.
    """
    try:
        parts = urlsplit(str(url).strip())
        if parts.scheme.lower() not in ("http", "https"):
            return None
        host = parts.hostname  # strips userinfo and port, lower-cases
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    return None


def classify_source(url: object, extra_tier1_domains: Iterable[str] = ()) -> SourceTier:
    """Return the trust tier of `url`. Unknown or unparseable URLs are tier 3, never higher."""
    host = extract_host(url)
    if host is None:
        return SourceTier.TIER_3

    extra = {d.lower().strip().strip(".") for d in extra_tier1_domains if d.strip()}
    if any(_matches(host, d) for d in extra | TIER1_DOMAINS | TIER1_SUFFIXES):
        return SourceTier.TIER_1
    if any(_matches(host, d) for d in TIER2_DOMAINS):
        return SourceTier.TIER_2
    return SourceTier.TIER_3


def is_credible(tier: SourceTier) -> bool:
    """Credible = tier 1 or 2. Only credible evidence can be decisive in the decision table."""
    return tier <= SourceTier.TIER_2