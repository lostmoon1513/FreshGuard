"""Diagnose the page fetcher on real URLs: does it download, extract text, and find a date?

    python scripts/smoke_fetch.py https://www.bbc.com/news/world-asia-india-59472676
    python scripts/smoke_fetch.py URL1 URL2 ...

Run from backend/. Reads backend/.env like the server does. Prints title, date, text size or error.
"""

from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.engine.providers.errors import FetchError
from app.engine.providers.factory import build_fetcher, user_agent_for

DEFAULT_URLS = [
    "https://www.npr.org/2021/11/30/1060035782/parag-agarwal-twitter-ceo",
    "https://www.bbc.com/news/world-asia-india-59472676",
    "https://en.wikipedia.org/wiki/Friedrich_Merz",
    "https://www.britannica.com/biography/Olaf-Scholz",
    "https://worldleaders.columbia.edu/directory/olaf-scholz",
]


async def main(urls: list[str]) -> int:
    settings = get_settings()  # same .env as the server: FETCH_CONTACT, FETCH_TIMEOUT_SECONDS
    fetcher = build_fetcher(settings)
    print(f"user-agent: {user_agent_for(settings.fetch_contact)}")
    print(f"timeout:    {settings.fetch_timeout_seconds}s")
    failures = 0
    for url in urls:
        print(f"\\n{url}")
        try:
            doc = await fetcher.fetch(url)
        except FetchError as exc:
            failures += 1
            print(f"  FAILED: {type(exc).__name__}: {exc.message}")
            continue
        print(f"  title:     {doc.title!r}")
        print(f"  published: {doc.published_at}")
        print(f"  modified:  {doc.modified_at}")
        print(f"  text:      {len(doc.text)} chars; starts: {doc.text[:100]!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:] or DEFAULT_URLS)))