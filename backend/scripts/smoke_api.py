"""Live end-to-end check of a RUNNING FreshGuard server (real providers, real web).

    python scripts/smoke_api.py
    python scripts/smoke_api.py --question "Who runs X?" --answer "Alice runs X."

Start the server first (from backend/):  uvicorn app.main:app --port 8000
Uses only the standard library. Prints the label, claims and evidence quotes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_QUESTION = "Who is the CEO of Twitter?"
DEFAULT_ANSWER = "Jack Dorsey is the CEO of Twitter."


def call(method: str, url: str, key: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--answer", default=DEFAULT_ANSWER)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    status, body = call("GET", f"{base}/health", "")
    print(f"health: {status} {body}")
    if status != 200:
        print("Server not reachable. Start it with: uvicorn app.main:app --port 8000")
        return 1

    started = time.time()
    status, body = call(
        "POST",
        f"{base}/v1/verifications",
        args.api_key,
        {"question": args.question, "answer": args.answer, "metadata": {"source": "smoke"}},
    )
    print(f"submit: {status} {body}")
    if status != 202:
        return 1
    rid = body["id"]
    while time.time() - started < args.timeout:
        status, result = call("GET", f"{base}/v1/verifications/{rid}", args.api_key)
        if status != 200:
            print(f"poll error: {status} {result}")
            return 1
        if result["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    else:
        print("Timed out waiting for the result.")
        return 1

    print(
        f"\nstatus={result['status']} label={result['label']} "
        f"confidence={result['confidence']} took={time.time() - started:.0f}s"
    )
    if result.get("error"):
        print("error:", result["error"])
    for claim in result["claims"]:
        print(f"\n- [{claim['label']}] {claim['text']}  ({claim['volatility']})")
        print(f"  why: {claim['reasoning']}")
        for ev in claim["evidence"]:
            if ev["stance"] != "neutral":
                print(f"  {ev['stance']} tier{ev['tier']} {ev['url']}")
                print(f'    "{ev["quoted_span"]}"  (published {ev["published_at"]})')
    if result.get("suggested_correction"):
        print("\nsuggested correction:", result["suggested_correction"])
    return 0


if __name__ == "__main__":
    sys.exit(main())