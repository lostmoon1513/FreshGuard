"""Turn an HTML page into plain text, a title and a publish date. Pure: no I/O, no clock.

Quotes are later checked as verbatim substrings of THIS text, so the extraction is deliberately
simple and deterministic. The publish date is read only from structured metadata (JSON-LD
`datePublished`, `article:published_time`, ...), never guessed from prose, and "modified" dates
are ignored: they do not say when the content was written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from app.engine.providers.dates import parse_published_date

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "canvas"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article",
        "header", "footer", "nav", "aside", "main", "figure", "figcaption", "blockquote", "pre",
        "hr", "dl", "dt", "dd", "form", "h1", "h2", "h3", "h4", "h5", "h6", "title",
    }
)  # fmt: skip

# Metadata keys that mean "published at", best first. 'date' is the weakest and comes last.
_DATE_KEYS = (
    "article:published_time", "og:article:published_time", "datepublished", "pubdate",
    "publishdate", "publish-date", "publish_date", "dc.date.issued", "dcterms.created",
    "parsely-pub-date", "sailthru.date", "citation_publication_date", "citation_date",
    "dc.date", "dcterms.date", "date",
)  # fmt: skip
_JSON_LD_PRIORITY = -1  # structured data beats meta tags


@dataclass(frozen=True)
class ExtractedPage:
    title: str | None
    text: str
    published_at: datetime | None


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.date_candidates: list[tuple[int, str]] = []
        self._skip_depth = 0
        self._in_title = False
        self._ld_chunks: list[str] | None = None
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").strip().lower()
            content = a.get("content", "").strip()
            if key in _DATE_KEYS and content:
                self.date_candidates.append((_DATE_KEYS.index(key), content))
        elif tag == "time" and a.get("itemprop", "").lower() == "datepublished":
            if a.get("datetime"):
                self.date_candidates.append((_DATE_KEYS.index("datepublished"), a["datetime"]))
        elif tag == "title":
            self._in_title = True
        if tag == "script" and a.get("type", "").lower().startswith("application/ld+json"):
            self._ld_chunks = []
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Self-closing tags (<br/>, <meta .../>) never get an end tag, so do not track depth.
        if tag in _SKIP_TAGS:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._ld_chunks is not None:
            self.json_ld.append("".join(self._ld_chunks))
            self._ld_chunks = None
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ld_chunks is not None:
            self._ld_chunks.append(data)
            return
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        # Newlines inside a text node are plain whitespace; only block tags break lines.
        self.parts.append(data.replace("\r", " ").replace("\n", " "))


def normalize_text(raw: str) -> str:
    """Collapse whitespace inside lines and drop blank lines."""
    lines = (" ".join(line.split()) for line in raw.replace("\r", "\n").split("\n"))
    return "\n".join(line for line in lines if line)


def _json_ld_dates(blobs: list[str]) -> list[str]:
    found: list[str] = []

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(node, dict):
            value = node.get("datePublished")
            if isinstance(value, str):
                found.append(value)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node[:50]:
                walk(child, depth + 1)

    for blob in blobs:
        try:
            walk(json.loads(blob))
        except ValueError:
            continue
    return found


def extract_page(html: str, now: datetime) -> ExtractedPage:
    """Best-effort extraction. Never raises on malformed HTML."""
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not lose the text already read
        pass

    candidates = [(_JSON_LD_PRIORITY, v) for v in _json_ld_dates(parser.json_ld)]
    candidates += parser.date_candidates
    published = None
    for _, raw in sorted(candidates, key=lambda c: c[0]):
        published = parse_published_date(raw, now)
        if published is not None:
            break

    title = normalize_text("".join(parser.title_parts)).replace("\n", " ") or None
    return ExtractedPage(
        title=title, text=normalize_text("".join(parser.parts)), published_at=published
    )