"""A stand-in for the real FreshGuard SDK that follows INTEGRATION_GUIDE.md exactly.

Same surface as the real client: submit(question, answer, metadata) -> job with .id,
get(id) -> Verification (status/label/confidence/suggested_correction/claims/...).
Results are decided by keyword rules so every badge can be demoed offline.
Swap to the real SDK by setting USE_MOCK_FRESHGUARD=false.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Evidence:
    url: str
    tier: int
    stance: str  # supports | contradicts | neutral
    quoted_span: str
    published_at: str | None = None
    fetched_at: str | None = None
    integrity_ok: bool = True


@dataclass
class Claim:
    text: str
    label: str
    volatility: str = "slow"
    reasoning: str = ""
    freshness_window_days: int = 365
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Verification:
    id: str
    status: str  # pending | running | completed | failed
    label: str | None = None
    confidence: float | None = None
    suggested_correction: str | None = None
    error: str | None = None
    claims: list[Claim] = field(default_factory=list)
    created_at: str = ""
    finished_at: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def is_stale(self) -> bool:
        return self.label == "stale"

    @property
    def should_warn(self) -> bool:
        return self.label in ("stale", "potentially_stale")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale(claim, url, quote, correction, tier=1):
    return dict(
        label="stale", confidence=0.86, correction=correction,
        claims=[Claim(
            text=claim, label="stale", volatility="fast",
            reasoning="A credible, recent source contradicts the claim (0 supporting, 1 contradicting verified source(s)). [MOCK]",
            freshness_window_days=30,
            evidence=[Evidence(url=url, tier=tier, stance="contradicts", quoted_span=quote,
                               published_at="2026-09-01T00:00:00Z", fetched_at=_now())],
        )],
    )


def _fresh(claim, url, quote, volatility="slow", window=365):
    return dict(
        label="fresh", confidence=0.9, correction=None,
        claims=[Claim(
            text=claim, label="fresh", volatility=volatility,
            reasoning="Credible, recent sources support the claim (1 supporting, 0 contradicting verified source(s)). [MOCK]",
            freshness_window_days=window,
            evidence=[Evidence(url=url, tier=1, stance="supports", quoted_span=quote,
                               published_at="2026-06-01T00:00:00Z", fetched_at=_now())],
        )],
    )


# (keywords that must ALL appear in question+answer, outcome). First match wins.
RULES = [
    (("simulate failure",), dict(fail=True)),
    (("python", "3.9"), _stale("The latest stable Python version is 3.9",
        "https://www.python.org/downloads/", "Python 3.9 has reached end of life; newer releases are available",
        "Python 3.9 is no longer the latest stable version. See python.org/downloads for the current release.")),
    (("react", "17"), _stale("The latest stable React version is 17",
        "https://react.dev/blog", "React 17 is no longer the latest major version",
        "React 17 is outdated; check react.dev for the current stable release.")),
    (("node", "16"), _stale("The current Node.js LTS is version 16",
        "https://nodejs.org/en/about/previous-releases", "Node.js 16 reached end-of-life",
        "Node.js 16 is end-of-life; see nodejs.org for the current LTS.")),
    (("parag agrawal",), _stale("Parag Agrawal is the CEO of Twitter",
        "https://en.wikipedia.org/wiki/Twitter", "Twitter was renamed X and Parag Agrawal left the company in 2022",
        "Parag Agrawal is no longer CEO; Twitter is now X and has had different leadership since 2022.", tier=2)),
    (("boris johnson",), _stale("Boris Johnson is the UK Prime Minister",
        "https://www.gov.uk/government/history/past-prime-ministers", "Boris Johnson left office as Prime Minister in 2022",
        "Boris Johnson is no longer Prime Minister. See gov.uk for the current office holder.")),
    (("satya nadella",), _fresh("Satya Nadella is the CEO of Microsoft",
        "https://news.microsoft.com/leadership/", "Satya Nadella is Chairman and Chief Executive Officer of Microsoft", "slow")),
    (("new delhi",), _fresh("The capital of India is New Delhi",
        "https://en.wikipedia.org/wiki/New_Delhi", "New Delhi is the capital of India", "static", 3650)),
    (("guido",), _fresh("Python was created by Guido van Rossum",
        "https://www.python.org/doc/essays/blurb/", "Python was created by Guido van Rossum", "static", 3650)),
    (("acme cloud",), dict(
        label="potentially_stale", confidence=0.35, correction=None,
        claims=[Claim(text="The Acme Cloud Pro plan costs 49 US dollars per month", label="potentially_stale",
                      volatility="fast", reasoning="Only old or undated evidence was found. [MOCK]",
                      freshness_window_days=30,
                      evidence=[Evidence(url="https://example.com/acme-pricing", tier=3, stance="neutral",
                                         quoted_span="Pricing may vary by region", published_at=None, fetched_at=_now())])])),
]


class MockFreshGuard:
    mode = "mock"
    base_url = None
    sdk_version = None
    transient_errors: tuple = ()

    def __init__(self, delay_seconds: float = 6.0):
        self.delay = delay_seconds
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def check(self) -> dict:
        return {"reachable": True, "authenticated": True, "error": None}

    def submit(self, question: str, answer: str, metadata: dict | None = None) -> Verification:
        job_id = str(uuid.uuid4())
        text = f"{question} {answer}".lower()
        outcome = {}  # default => unverifiable
        for keywords, result in RULES:
            if all(k in text for k in keywords):
                outcome = result
                break
        with self._lock:
            self._jobs[job_id] = {"t0": time.monotonic(), "created": _now(), "outcome": outcome,
                                  "metadata": dict(metadata or {})}
        return Verification(id=job_id, status="pending", created_at=self._jobs[job_id]["created"],
                            metadata=dict(metadata or {}))

    def get(self, job_id: str) -> Verification:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"unknown verification id {job_id}")
        elapsed = time.monotonic() - job["t0"]
        base = dict(id=job_id, created_at=job["created"], metadata=job["metadata"])
        if elapsed < self.delay * 0.25:
            return Verification(status="pending", **base)
        if elapsed < self.delay:
            return Verification(status="running", **base)
        out = job["outcome"]
        if out.get("fail"):
            return Verification(status="failed", error="Verification providers are unavailable. Please retry later. [MOCK]",
                                finished_at=_now(), **base)
        if not out:
            return Verification(status="completed", label="unverifiable", confidence=0.0, claims=[],
                                finished_at=_now(), **base)
        return Verification(status="completed", label=out["label"], confidence=out["confidence"],
                            suggested_correction=out["correction"], claims=out["claims"],
                            finished_at=_now(), **base)
