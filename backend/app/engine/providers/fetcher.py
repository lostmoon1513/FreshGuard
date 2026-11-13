"""Fetch a web page safely and turn it into a `Document` (text, title, publish date).

Responsibility: the "fetched page" behind every quote. Safety rules, because search results are
attacker-influenced URLs and this runs on a server:
  - only http(s); never IP literals or hosts that resolve to private/loopback/link-local/reserved
    addresses (blocks cloud-metadata and internal services); every redirect hop is re-checked;
  - size cap (bytes), timeout, at most `max_redirects` hops, text-like content types only.
Known limitation: DNS is checked before the connection, so a DNS-rebinding attacker could still
race it. Mitigate at deploy time with egress rules (M10).
Pages are fetched with a fixed, honest User-Agent. robots.txt is not consulted yet.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from app.engine.providers.errors import FetchError, UnsafeURLError
from app.engine.providers.html_text import extract_page, normalize_text
from app.engine.providers.http import HttpResponse, HttpTransportError
from app.engine.providers.models import utc_now
from app.schemas.evidence import Document

log = logging.getLogger(__name__)

USER_AGENT = "FreshGuardBot/0.1 (+freshness checking; respectful, low volume)"
MAX_PAGE_CHARS = 100_000
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp")
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_CHARSET = re.compile(r"charset\s*=\s*['\"]?([\w.-]+)", re.IGNORECASE)

Resolver = Callable[[str], Awaitable[list[str]]]


class PageHttp(Protocol):
    """The one GET we need. `HttpxClient` implements it; tests use a scripted fake."""

    async def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> HttpResponse: ...


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> Document:
        """Return the page as a `Document`, or raise `FetchError`. Never returns empty text."""
        ...


async def default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(value: str) -> bool:
    try:
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def check_public_url(url: str, resolver: Resolver = default_resolver) -> str:
    """Return the validated URL, or raise `UnsafeURLError`."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        raise UnsafeURLError("malformed URL", url) from None
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise UnsafeURLError("only http(s) URLs with a host are allowed", url)
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError("internal host names are not allowed", url)
    try:
        ipaddress.ip_address(host)
    except ValueError:  # a name: resolve and check every address it maps to
        try:
            addresses = await resolver(host)
        except (OSError, UnicodeError):
            raise FetchError("host could not be resolved", url) from None
        if not addresses:
            raise FetchError("host could not be resolved", url) from None
    else:
        addresses = [host]
    if not all(is_public_ip(a) for a in addresses):
        raise UnsafeURLError("address is not public", url)
    return url


def _decode(resp: HttpResponse) -> str:
    match = _CHARSET.search(resp.headers.get("content-type", ""))
    for charset in ([match.group(1)] if match else []) + ["utf-8"]:
        try:
            return resp.body.decode(charset, errors="replace")
        except LookupError:
            continue
    return resp.body.decode("utf-8", errors="replace")  # pragma: no cover


class HttpPageFetcher:
    def __init__(
        self,
        http: PageHttp,
        *,
        timeout: float = 10.0,
        max_bytes: int = 1_500_000,
        max_redirects: int = 4,
        user_agent: str = USER_AGENT,
        resolver: Resolver = default_resolver,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._http = http
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._user_agent = user_agent
        self._resolver = resolver
        self._clock = clock

    async def fetch(self, url: str) -> Document:
        headers = {
            "user-agent": self._user_agent,
            "accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            "accept-language": "en",
        }
        current = url
        resp: HttpResponse | None = None
        for _ in range(self._max_redirects + 1):
            await check_public_url(current, self._resolver)
            try:
                resp = await self._http.get(
                    current, headers=headers, timeout=self._timeout, max_bytes=self._max_bytes
                )
            except HttpTransportError as exc:
                raise FetchError(f"network error: {exc}", url) from None
            location = resp.headers.get("location")
            if 300 <= resp.status < 400 and location:
                current = urljoin(current, location)
                continue
            break
        else:
            raise FetchError("too many redirects", url)

        assert resp is not None
        if resp.status != 200:
            raise FetchError(f"HTTP {resp.status}", url)
        kind = resp.headers.get("content-type", "text/html").split(";")[0].strip().lower()
        if kind not in _TEXT_TYPES:
            raise FetchError(f"unsupported content type: {kind[:40]}", url)

        decoded = _decode(resp)
        now = self._clock()
        if kind == "text/plain":
            title, text, published = None, normalize_text(decoded), None
        else:
            page = extract_page(decoded, now)
            title, text, published = page.title, page.text, page.published_at
        if not text:
            raise FetchError("page had no readable text", url)
        return Document(
            url=current,  # type: ignore[arg-type]  # validated by pydantic
            title=title,
            text=text[:MAX_PAGE_CHARS],
            published_at=published,
            fetched_at=now,
        )


def describe(error: BaseException) -> str:
    """Short, safe description of a fetch failure for logs and notes."""
    return error.message if isinstance(error, FetchError) else type(error).__name__


__all__ = [
    "HttpPageFetcher",
    "PageFetcher",
    "PageHttp",
    "Resolver",
    "check_public_url",
    "default_resolver",
    "describe",
    "is_public_ip",
]
_ = Any  # keep typing import used by type checkers on some versions