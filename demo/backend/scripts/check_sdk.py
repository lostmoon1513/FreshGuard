"""Live check that the FreshGuard SDK works from this app's environment (no Gemini key needed).

Run from demo/backend, with the FreshGuard backend running (default http://localhost:8000):

    python scripts/check_sdk.py
    python scripts/check_sdk.py --base-url http://localhost:8000 --api-key dev-key --timeout 120

It uses the same adapter the chatbot uses (app.freshguard.real_client), so a pass here means the
chatbot's FreshGuard layer is wired correctly. Exit code 0 = everything passed, 1 = a check failed.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.freshguard.badges import badge_from_verification  # noqa: E402
from app.freshguard.real_client import RealFreshGuard  # noqa: E402

# A deliberately outdated answer: FreshGuard should flag it stale / potentially_stale.
QUESTION = "Who is the CEO of Twitter?"
ANSWER = "Parag Agrawal is the CEO of Twitter."


def step(ok: bool, text: str) -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {text}")
    return ok


def main() -> int:
    p = argparse.ArgumentParser(description="Check the FreshGuard SDK end to end.")
    p.add_argument("--base-url", default=os.getenv("FRESHGUARD_BASE_URL", "http://localhost:8000"))
    p.add_argument("--api-key", default=os.getenv("FRESHGUARD_API_KEY", "dev-key"))
    p.add_argument("--timeout", type=float, default=120, help="seconds to wait for the verdict")
    args = p.parse_args()

    client = RealFreshGuard(args.base_url, args.api_key)
    print(f"SDK freshguard {client.sdk_version} -> {args.base_url}\n")

    status = client.check()
    if not step(status["reachable"], "server reachable (GET /health)"):
        print(f"       {status['error']}")
        return 1
    if not step(status["authenticated"] is not False, "API key accepted"):
        print(f"       {status['error']}")
        return 1

    job = client.submit(QUESTION, ANSWER, {"message_id": "sdk-check"})
    if not step(bool(job.id), f"submit returned a job id ({job.id})"):
        return 1

    deadline = time.monotonic() + args.timeout
    result = client.get(job.id)
    while not result.is_done and time.monotonic() < deadline:
        print(f"       status: {result.status} ...")
        time.sleep(2)
        result = client.get(job.id)
    if not step(result.is_done, f"verification finished (status={result.status})"):
        return 1
    if result.status == "failed":
        step(False, f"job failed on the server: {result.error}")
        return 1

    badge = badge_from_verification(result)
    print(f"\n       label      : {result.label} (confidence {result.confidence})")
    print(f"       badge      : {badge['color']} / {badge['text']}")
    if badge.get("suggested_correction"):
        print(f"       correction : {badge['suggested_correction']}")
    if badge.get("source_url"):
        print(f"       source     : {badge['source_url']}")
    return 0 if step(result.label is not None, "got a label and a badge") else 1


if __name__ == "__main__":
    raise SystemExit(main())
