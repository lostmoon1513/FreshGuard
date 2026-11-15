"""Thin adapter over the real FreshGuard SDK (package `freshguard`, in the repo's `sdk/` folder).

It exposes the same methods as the mock (submit, get, check), so nothing else in the app changes.
The SDK is imported lazily, so the app still starts without it while the mock is on.

Install the SDK into this app's virtual environment:
    pip install -e ../../sdk
"""
from datetime import datetime, timezone


class RealFreshGuard:
    mode = "real"

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0, transport=None):
        try:
            import freshguard
            from freshguard import FreshGuard
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "USE_MOCK_FRESHGUARD=false but the `freshguard` SDK is not installed. "
                "Run:  pip install -e ../../sdk   (from demo/backend)"
            ) from exc
        from freshguard import ConnectionFailed, RateLimitError, ServerError

        self.base_url = base_url
        self.sdk_version = getattr(freshguard, "__version__", "unknown")
        # Errors that may clear on their own: keep showing "Checking..." instead of hiding the badge.
        self.transient_errors = (ConnectionFailed, RateLimitError, ServerError)
        # `transport` is only for tests (a fake HTTP layer); production uses the SDK's httpx.
        kwargs = {"transport": transport} if transport is not None else {}
        self._fg = FreshGuard(base_url=base_url, api_key=api_key, timeout=timeout, **kwargs)

    def submit(self, question: str, answer: str, metadata: dict | None = None):
        """Start a verification (returns at once, status "pending")."""
        return self._fg.submit(
            question=question,
            answer=answer,
            answer_generated_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

    def get(self, job_id: str):
        return self._fg.get(job_id)

    def check(self) -> dict:
        """Is the FreshGuard server reachable, and is our API key accepted?

        /health needs no key, so we also make one authenticated call (list 1 result).
        """
        from freshguard import AuthError, FreshGuardError

        if not self._fg.health():
            return {"reachable": False, "authenticated": None,
                    "error": f"Cannot reach FreshGuard at {self.base_url}"}
        try:
            self._fg.list(limit=1)
        except AuthError:
            return {"reachable": True, "authenticated": False,
                    "error": "FreshGuard rejected the API key (check FRESHGUARD_API_KEY)"}
        except FreshGuardError as exc:
            return {"reachable": True, "authenticated": None, "error": str(exc)}
        return {"reachable": True, "authenticated": True, "error": None}
