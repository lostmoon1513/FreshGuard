"""Seed knowledge base for the demo.

Some documents are DELIBERATELY OUTDATED (stale) so the chatbot answers confidently
with a wrong-by-now fact and FreshGuard can catch it live. Others are current or static,
to prove FreshGuard does not raise false alarms.

`expected` is only for our own test matrix / README; it is not used at runtime.
"""

KB_DOCUMENTS = [
    # ---------------- Deliberately STALE ----------------
    {
        "id": "python-version",
        "title": "Python Release Notes (internal wiki, archived)",
        "last_updated": "2021-10-05",
        "topic": "software_version",
        "expected": "stale",
        "text": (
            "Python release status. The latest stable version of Python is 3.9. "
            "Python 3.9 is the version recommended for all new projects. "
            "Last reviewed by the platform team on 2021-10-05."
        ),
    },
    {
        "id": "react-version",
        "title": "Frontend Guide (internal wiki, archived)",
        "last_updated": "2021-03-12",
        "topic": "software_version",
        "expected": "stale",
        "text": (
            "Frontend stack notes. The latest stable release of React is version 17. "
            "New components should target React 17 and avoid unreleased features. "
            "Last reviewed on 2021-03-12."
        ),
    },
    {
        "id": "node-lts",
        "title": "Runtime Policy (internal wiki, archived)",
        "last_updated": "2021-11-01",
        "topic": "software_version",
        "expected": "stale",
        "text": (
            "Runtime policy. The current Node.js LTS release is version 16, codename Gallium. "
            "All services must run on Node.js 16 LTS. Last reviewed on 2021-11-01."
        ),
    },
    {
        "id": "twitter-ceo",
        "title": "Social Media Companies Overview (2021 edition)",
        "last_updated": "2021-12-15",
        "topic": "leadership",
        "expected": "stale",
        "text": (
            "Social media companies overview. Parag Agrawal is the CEO of Twitter, "
            "having taken over the role in November 2021. Twitter is headquartered in "
            "San Francisco, California."
        ),
    },
    {
        "id": "uk-pm",
        "title": "World Leaders Handbook (2021 edition)",
        "last_updated": "2021-06-01",
        "topic": "politics",
        "expected": "stale",
        "text": (
            "World leaders handbook. The Prime Minister of the United Kingdom is Boris Johnson, "
            "who leads the Conservative Party government."
        ),
    },
    # ---------------- Current / should stay FRESH ----------------
    {
        "id": "microsoft-ceo",
        "title": "Big Tech Leadership Overview",
        "last_updated": "2026-05-20",
        "topic": "leadership",
        "expected": "fresh",
        "text": (
            "Big tech leadership overview. Satya Nadella is the Chief Executive Officer of Microsoft. "
            "Microsoft is headquartered in Redmond, Washington."
        ),
    },
    # ---------------- Static facts (must NOT be flagged) ----------------
    {
        "id": "static-geography",
        "title": "General Knowledge: Geography",
        "last_updated": "2020-01-10",
        "topic": "static",
        "expected": "fresh",
        "text": (
            "General knowledge. The capital of India is New Delhi. "
            "The Earth revolves around the Sun once every 365.25 days approximately."
        ),
    },
    {
        "id": "static-python-history",
        "title": "General Knowledge: Programming history",
        "last_updated": "2020-01-10",
        "topic": "static",
        "expected": "fresh",
        "text": (
            "Programming history. Python was created by Guido van Rossum and first released in 1991."
        ),
    },
    # ---------------- Unverifiable on the open web ----------------
    {
        "id": "example-university-exams",
        "title": "Example University Notice Board",
        "last_updated": "2026-01-10",
        "topic": "university",
        "expected": "unverifiable",
        "text": (
            "Example University notice. The semester examinations of Example University "
            "begin on 15 March 2027. Hall tickets are issued one week before the exams "
            "from the department office."
        ),
    },
    # ---------------- Weak evidence / pricing ----------------
    {
        "id": "internal-pricing",
        "title": "Acme Cloud Pricing Sheet",
        "last_updated": "2025-02-01",
        "topic": "pricing",
        "expected": "potentially_stale",
        "text": (
            "Acme Cloud pricing. The Starter plan costs 12 US dollars per month and the "
            "Pro plan costs 49 US dollars per month. Prices exclude taxes."
        ),
    },
]

SAMPLE_QUESTIONS = [
    "What is the latest stable version of Python?",
    "What is the latest version of React?",
    "Which Node.js LTS version should we use?",
    "Who is the CEO of Twitter?",
    "Who is the Prime Minister of the UK?",
    "Who is the CEO of Microsoft?",
    "What is the capital of India?",
    "When do the Example University semester exams begin?",
    "How much does the Acme Cloud Pro plan cost?",
]
