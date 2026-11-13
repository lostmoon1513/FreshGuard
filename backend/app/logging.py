"""Structured logging with request IDs and secret redaction.

Responsibility: configure logging once; make every log line traceable to a request.
Rule: never log secrets. Extra fields whose names look sensitive are masked.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SENSITIVE_PARTS = ("key", "token", "secret", "password", "authorization")
_MASK = "***"
_HANDLER_MARK = "_freshguard_handler"
# Attributes every LogRecord has; anything else came from `extra=`.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(value: str) -> contextvars.Token[str]:
    return request_id_var.set(value)


def get_request_id() -> str:
    return request_id_var.get()


def is_sensitive(name: str) -> bool:
    """Over-redacting is the safe side: any name containing a sensitive word is masked."""
    lowered = name.lower()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def redact_extra(extra: dict[str, Any]) -> dict[str, Any]:
    return {k: (_MASK if is_sensitive(k) else v) for k, v in extra.items()}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")
        }
        payload.update(redact_extra(extras))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure the root logger. Safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _HANDLER_MARK, True)
    handler.addFilter(RequestIdFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
