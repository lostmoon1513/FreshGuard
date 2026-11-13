"""Tiny helper so providers accept either a plain str or pydantic's SecretStr."""

from __future__ import annotations

from pydantic import SecretStr


def secret_value(key: SecretStr | str) -> str:
    value = key.get_secret_value() if isinstance(key, SecretStr) else key
    value = value.strip()
    if not value:
        raise ValueError("API key must not be empty.")
    return value