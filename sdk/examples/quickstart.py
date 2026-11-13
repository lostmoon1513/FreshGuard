"""Smallest possible use of the SDK.   python examples/quickstart.py

Start the backend first (from backend/):  uvicorn app.main:app --port 8000
"""

import os

from freshguard import FreshGuard, FreshGuardError

fg = FreshGuard(
    base_url=os.getenv("FRESHGUARD_URL", "http://localhost:8000"),
    api_key=os.getenv("FRESHGUARD_API_KEY"),
)

try:
    result = fg.verify(
        question="Who is the CEO of Twitter?",
        answer="Jack Dorsey is the CEO of Twitter.",
        wait_seconds=110,  # the first run can take a minute or more on free-tier models
    )
except FreshGuardError as exc:  # never let FreshGuard break your app
    print("Could not verify:", exc)
else:
    print("status:", result.status, "| label:", result.label, "| confidence:", result.confidence)
    if result.error:
        print("error:", result.error)
    for claim in result.claims:
        print(f"- [{claim.label}] {claim.text}")
        for ev in claim.evidence:
            if ev.stance != "neutral":
                print(f'    {ev.stance}: {ev.url}\n    "{ev.quoted_span}"')
    if result.suggested_correction:
        print("suggested correction:", result.suggested_correction)