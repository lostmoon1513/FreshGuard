"""FreshGuard integration layer used by the API.

Key rule from the contract: FreshGuard being down must NEVER break the chatbot.
Every call into the client is wrapped; failures become a "no badge" state.
"""
import logging
import threading
from functools import lru_cache

from app.config import settings
from app.freshguard.badges import badge_from_verification, checking_badge, unavailable_badge
from app.freshguard.mock_client import MockFreshGuard

log = logging.getLogger(__name__)

# A badge poll that fails with a transient SDK error (network blip, 429, 5xx) keeps showing
# "Checking..." instead of hiding the badge; after this many failures in a row we give up.
MAX_TRANSIENT_POLL_FAILURES = 5


class FreshGuardService:
    def __init__(self, client):
        self.client = client
        self._jobs: dict[str, str | None] = {}  # message_id -> verification id (None = submit failed)
        self._poll_failures: dict[str, int] = {}
        self._submit_errors: dict[str, str] = {}  # message_id -> why the submit failed
        self._lock = threading.Lock()

    def start(self, message_id: str) -> None:
        """Register a message as 'checking' immediately (before the background submit runs)."""
        with self._lock:
            self._jobs.setdefault(message_id, "__pending__")

    def submit(self, message_id: str, question: str, answer: str, conversation_id: str) -> None:
        """Runs in a background task, after the user already has the answer."""
        try:
            job = self.client.submit(
                question=question, answer=answer,
                metadata={"conversation_id": conversation_id, "message_id": message_id},
            )
            job_id = job.id
            reason = None
        except Exception as exc:  # noqa: BLE001 - FreshGuard must never break chat
            log.warning("FreshGuard submit failed (%s): %s", type(exc).__name__, exc)
            job_id = None
            reason = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._jobs[message_id] = job_id
            if reason:
                self._submit_errors[message_id] = reason

    def badge(self, message_id: str) -> dict | None:
        """Return the current badge dict, or None if the message is unknown."""
        with self._lock:
            if message_id not in self._jobs:
                return None
            job_id = self._jobs[message_id]
        if job_id == "__pending__":
            return checking_badge()
        if job_id is None:
            reason = self._submit_errors.get(message_id, "FreshGuard unreachable")
            return unavailable_badge(reason)
        try:
            result = badge_from_verification(self.client.get(job_id))
        except Exception as exc:  # noqa: BLE001
            return self._on_poll_error(message_id, exc)
        with self._lock:
            self._poll_failures.pop(message_id, None)
        return result

    def _on_poll_error(self, message_id: str, exc: Exception) -> dict:
        log.warning("FreshGuard get failed (%s): %s", type(exc).__name__, exc)
        transient = getattr(self.client, "transient_errors", ())
        if transient and isinstance(exc, transient):
            with self._lock:
                n = self._poll_failures.get(message_id, 0) + 1
                self._poll_failures[message_id] = n
            if n < MAX_TRANSIENT_POLL_FAILURES:
                return checking_badge()
        return unavailable_badge(f"{type(exc).__name__}: {exc}")

    def status(self) -> dict:
        """Is the FreshGuard connection healthy? Used by the UI and for demo-time sanity checks.

        Never raises and never includes secrets (no API key)."""
        info = {
            "mode": getattr(self.client, "mode", "unknown"),
            "base_url": getattr(self.client, "base_url", None),
            "sdk_version": getattr(self.client, "sdk_version", None),
        }
        try:
            info.update(self.client.check())
        except Exception as exc:  # noqa: BLE001
            log.warning("FreshGuard check failed (%s): %s", type(exc).__name__, exc)
            info.update(reachable=False, authenticated=None, error="FreshGuard check failed")
        return info


@lru_cache
def get_service() -> FreshGuardService:
    if settings.use_mock_freshguard:
        client = MockFreshGuard(delay_seconds=settings.mock_delay_seconds)
    else:
        from app.freshguard.real_client import RealFreshGuard
        client = RealFreshGuard(settings.freshguard_base_url, settings.freshguard_api_key,
                                timeout=settings.freshguard_timeout)
    return FreshGuardService(client)
