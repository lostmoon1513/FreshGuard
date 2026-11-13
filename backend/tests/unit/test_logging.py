import json
import logging

from app.logging import (
    JsonFormatter,
    get_logger,
    is_sensitive,
    new_request_id,
    redact_extra,
    set_request_id,
    setup_logging,
)


def make_record(message="hello", **extra):
    record = logging.LogRecord("freshguard.test", logging.INFO, __file__, 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_includes_core_fields_and_request_id():
    token = set_request_id("req-123")
    try:
        data = json.loads(JsonFormatter().format(make_record("hi", claim_count=3)))
    finally:
        from app.logging import request_id_var

        request_id_var.reset(token)
    assert data["message"] == "hi"
    assert data["level"] == "INFO"
    assert data["logger"] == "freshguard.test"
    assert data["request_id"] == "req-123"
    assert data["claim_count"] == 3


def test_json_formatter_masks_sensitive_extra_fields():
    data = json.loads(
        JsonFormatter().format(make_record(api_key="abc123", Authorization="Bearer x", note="ok"))
    )
    assert data["api_key"] == "***"
    assert data["Authorization"] == "***"
    assert data["note"] == "ok"


def test_is_sensitive_and_redact_extra():
    assert is_sensitive("tavily_api_key")
    assert is_sensitive("PASSWORD")
    assert not is_sensitive("claim_count")
    assert redact_extra({"secret": "s", "n": 1}) == {"secret": "***", "n": 1}


def test_new_request_ids_are_unique():
    assert new_request_id() != new_request_id()


def test_setup_logging_is_idempotent():
    root = logging.getLogger()
    setup_logging("INFO")
    setup_logging("DEBUG", json_logs=True)
    ours = [h for h in root.handlers if getattr(h, "_freshguard_handler", False)]
    assert len(ours) == 1
    assert root.level == logging.DEBUG
    get_logger("freshguard.test").info("smoke")
