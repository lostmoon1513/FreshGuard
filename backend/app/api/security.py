"""API-key check. Constant-time comparison; never logs the key."""

from __future__ import annotations

import hmac

from pydantic import SecretStr


def key_is_valid(expected: SecretStr | None, supplied: str | None) -> bool:
    """No configured key means auth is disabled (the settings validator forbids that in
    production). Otherwise the supplied key must match exactly."""
    if expected is None or not expected.get_secret_value().strip():
        return True
    if not supplied:
        return False
    return hmac.compare_digest(
        expected.get_secret_value().encode("utf-8"), supplied.encode("utf-8")
    )