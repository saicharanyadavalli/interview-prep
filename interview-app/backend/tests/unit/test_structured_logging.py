"""Unit tests for structured JSON logging, correlation tracing, and error redaction."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from logger import JSONFormatter, redact_string, request_id_var, sanitize_log_data
from middleware.request_tracing import AccessLoggingMiddleware, RequestIdMiddleware


def test_redact_sensitive_strings():
    # Database URI
    pg_uri = "postgresql://myuser:P@ssword123!@db.example.internal:5432/interview_prep_db"
    assert "P@ssword123!" not in redact_string(pg_uri)
    assert "****" in redact_string(pg_uri)

    # Redis URI
    redis_uri = "rediss://:MyAuthToken999@cache.aws.internal:6379/0"
    assert "MyAuthToken999" not in redact_string(redis_uri)
    assert "****" in redact_string(redis_uri)

    # Bearer token
    bearer = "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc"
    assert "eyJhbG" not in redact_string(bearer)
    assert "Bearer ***" in redact_string(bearer)

    # AWS Key
    aws_key = "AWS_KEY=AKIAIOSFODNN7EXAMPLE"
    assert "AKIA****" in redact_string(aws_key)


def test_sanitize_log_data_dict_and_nested():
    data = {
        "username": "alice",
        "password": "SuperSecretPassword!",
        "access_token": "token123",
        "nested": {
            "api_key": "AIzaSyD-1234567890abcdef",
            "normal_field": 42,
        },
        "list_items": [
            {"token": "secret_in_list", "item_name": "book"}
        ],
    }
    cleaned = sanitize_log_data(data)
    assert cleaned["username"] == "alice"
    assert cleaned["password"] == "***"
    assert cleaned["access_token"] == "***"
    assert cleaned["nested"]["api_key"] == "***"
    assert cleaned["nested"]["normal_field"] == 42
    assert cleaned["list_items"][0]["token"] == "***"
    assert cleaned["list_items"][0]["item_name"] == "book"


def test_json_formatter_outputs_valid_json_with_request_id():
    formatter = JSONFormatter()
    token = request_id_var.set("test-request-id-999")

    try:
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname=__file__,
            lineno=42,
            msg="User login successful for user %s",
            args=("bob",),
            exc_info=None,
        )
        formatted = formatter.format(record)
        data = json.loads(formatted)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "User login successful for user bob"
        assert data["request_id"] == "test-request-id-999"
        assert "timestamp" in data
    finally:
        request_id_var.reset(token)


def test_request_id_middleware_echoes_header():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"ping": "pong"}

    client = TestClient(app)

    # 1. Custom incoming request ID is preserved
    resp1 = client.get("/ping", headers={"X-Request-ID": "custom-uuid-123"})
    assert resp1.headers.get("x-request-id") == "custom-uuid-123"

    # 2. Missing request ID generates a UUID
    resp2 = client.get("/ping")
    gen_id = resp2.headers.get("x-request-id")
    assert gen_id is not None
    assert len(gen_id) >= 16
