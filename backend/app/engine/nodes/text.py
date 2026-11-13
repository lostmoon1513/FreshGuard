"""Pure text helpers shared by the nodes: verbatim matching, passage selection, query/URL cleanup.

No I/O, no clock, no LLM. `contains_verbatim` is the heart of the "never fabricate evidence"
rule, so it is intentionally small and strict.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Typographic variants that mean the same text. Applied to BOTH sides of a comparison, so it can
# never make a fabricated quote match; it only stops curly quotes and dashes failing a real one.
_CHAR_MAP = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-", "−": "-",
        " ": " ", " ": " ", " ": " ", "​": "",
    }
)  # fmt: skip

_STOPWORDS = frozenset(
    "the and for are was were has have had its that this with from into than then them they "
    "their there which who whom whose what when where while will would could should about "
    "been being also not but all any can may more most other some such only over under after "
    "before between per via his her him she our your you out off".split()
)
_WORD = re.compile(r"[a-z0-9]+")
_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid")


def norm_for_match(text: str) -> str:
    """Whitespace-collapsed text with typographic quotes/dashes mapped to ASCII."""
    return " ".join(text.translate(_CHAR_MAP).split())


def contains_verbatim(haystack: str, needle: str) -> bool:
    """True if `needle` appears in `haystack` character for character (ignoring only whitespace
    layout and typographic quote/dash variants). Case-sensitive. Empty needles never match."""
    wanted = norm_for_match(needle)
    return bool(wanted) and wanted in norm_for_match(haystack)


def content_tokens(text: str) -> set[str]:
    """Lower-case words of length >= 3 that are not stop words (digits count as words)."""
    return {w for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in _STOPWORDS}


def shares_content_token(a: str, b: str) -> bool:
    return bool(content_tokens(a) & content_tokens(b))


def select_passage(text: str, claim: str, max_chars: int) -> str:
    """A slice of `text` (at most `max_chars`) that overlaps most with the claim's words.

    Always a contiguous slice of the original, so a quote taken from it is still a substring of
    the full text.
    """
    if len(text) <= max_chars:
        return text
    wanted = content_tokens(claim)
    if not wanted:
        return text[:max_chars]
    step = max(1, max_chars // 4)
    starts = list(range(0, len(text) - max_chars + 1, step))
    if starts[-1] != len(text) - max_chars:
        starts.append(len(text) - max_chars)
    best_start, best_score = 0, -1
    for start in starts:
        score = len(wanted & content_tokens(text[start : start + max_chars]))
        if score > best_score:
            best_start, best_score = start, score
    return text[best_start : best_start + max_chars]


def clean_query(query: str, max_chars: int = 200) -> str | None:
    """One search query: printable, single-spaced, bounded. None if nothing is left."""
    cleaned = " ".join("".join(ch for ch in query if ch.isprintable()).split())
    cleaned = cleaned.strip("\"'` ")[:max_chars].strip()
    return cleaned or None


def normalize_url(url: str) -> str:
    """Canonical form for de-duplication: lower-case host, no fragment, no tracking params,
    no trailing slash (except the root)."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = urlencode(
        [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING_PARAMS)]
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), (parts.netloc or "").lower(), path, query, ""))


def fence(tag: str, text: str) -> str:
    """Wrap untrusted text in <tag>...</tag> so the prompt can say 'this is data'.

    Any tag-like text inside is removed first, so the content cannot close the block early.
    """
    safe = re.sub(rf"</?\s*{re.escape(tag)}\s*>", "", text, flags=re.IGNORECASE)
    return f"<{tag}>\n{safe.strip()}\n</{tag}>"


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_CAPITALISED = re.compile(r"\b[A-Z][\w&'-]*")


def numbers_in(text: str) -> set[str]:
    return {m.replace(",", "") for m in _NUMBER.findall(text)}


def capitalised_terms(text: str) -> set[str]:
    """Capitalised words other than the first word of the text (likely names), lower-cased."""
    return {m.group(0).lower() for m in _CAPITALISED.finditer(text) if m.start() > 0}