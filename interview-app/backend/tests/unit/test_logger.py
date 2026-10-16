"""Unit tests for JSON logging and sensitive key sanitization."""

import json
import logging
from logger import JSONFormatter, request_id_var


def test_json_formatter_outputs_valid_json():
    """Verify JSONFormatter converts a LogRecord into valid JSON with expected core fields."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Test log message",
        args=(),
        exc_info=None,
    )
    request_id_var.set("req-test-999")

    formatted_str = formatter.format(record)
    data = json.loads(formatted_str)

    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["message"] == "Test log message"
    assert data["request_id"] == "req-test-999"
    assert "timestamp" in data


def test_json_formatter_sanitizes_sensitive_keys():
    """Verify JSONFormatter masks sensitive credential keys."""
    formatter = JSONFormatter()
    raw_data = {
        "password": "supersecretpassword",
        "access_token": "jwt.header.payload",
        "api_key": "ai-secret-123",
        "authorization": "Bearer token",
        "public_field": "visible_value",
        "nested": {
            "secret": "confidential",
            "safe": "hello",
        },
    }

    sanitized = formatter._sanitize(raw_data)
    assert sanitized["password"] == "***"
    assert sanitized["access_token"] == "***"
    assert sanitized["api_key"] == "***"
    assert sanitized["authorization"] == "***"
    assert sanitized["public_field"] == "visible_value"
    assert sanitized["nested"]["secret"] == "***"
    assert sanitized["nested"]["safe"] == "hello"
