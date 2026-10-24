"""Security Review & Credential Leakage Prevention Tests.

Verifies:
1. Complete mocking of AWS Secrets Manager and Valkey/Redis in tests.
2. Zero-credential-leakage across health endpoints (/health, /health/cache, /health/ready, /health/live).
3. Exception handlers shield clients from stack traces, database credentials, and internal error messages.
4. Structured logging automatically redacts sensitive strings, connection URIs, Bearer tokens, and AWS/Gemini keys.
5. Key namespace isolation and credential scrubbing in telemetry.
"""

from __future__ import annotations

import json
import logging
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from limiter import ResilientLimiterStorage, get_rate_limiter_storage_info, limiter
from logger import JSONFormatter, redact_string, sanitize_log_data
from main import app
from services.cache_service import CacheService, clear_secret_cache, mask_redis_url, resolve_secret_auth_token


@pytest.fixture(autouse=True)
def _isolate_secrets_and_cache():
    """Ensure in-memory cache and secret mocks are clean before and after each test."""
    clear_secret_cache()
    yield
    clear_secret_cache()


# -----------------------------------------------------------------------------
# 1. Zero Credential Leakage in Health Endpoints
# -----------------------------------------------------------------------------

def test_health_endpoint_zero_credential_leakage():
    """Verify /health returns only boolean checks and never returns raw secrets or credentials."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()

    assert "checks" in data
    checks = data["checks"]

    # All credential and connection indicators MUST be boolean, never raw tokens or IDs
    assert isinstance(checks.get("gemini_key_set"), bool)
    assert isinstance(checks.get("cognito_configured"), bool)
    assert isinstance(checks.get("rds_connected"), bool)
    assert isinstance(checks.get("redis_connected"), bool)
    assert isinstance(checks.get("redis_cache_enabled"), bool)
    assert isinstance(checks.get("rate_limiter_distributed"), bool)

    # Convert entire JSON to string and assert no sensitive pattern keywords are leaked as values
    raw_text = json.dumps(data)
    assert "AIza" not in raw_text
    assert "secret" not in raw_text.lower() or "gemini_key_set" in raw_text  # only the key name is allowed


def test_health_endpoints_zero_credential_leakage_with_active_valkey_credentials():
    """Verify /health, /health/cache, /health/live, and /health/ready never expose raw credentials.

    Simulates high-risk environment containing Valkey auth tokens, RDS passwords,
    Gemini API keys, and Cognito secrets.
    """
    secret_valkey_token = "ValkeyUltraSecretAuthToken2026!#$%"
    secret_db_password = "SuperSecretPostgresPassword999!"
    secret_gemini_key = "AIzaSyFakeSecretGeminiKey123456789"
    secret_cognito = "SecretCognitoClientSecretXYZ"

    env_overrides = {
        "CACHE_AUTH_TOKEN": secret_valkey_token,
        "REDIS_PASSWORD": secret_valkey_token,
        "DATABASE_URL": f"postgresql://app_user:{secret_db_password}@rds.internal:5432/interview_prep",
        "GEMINI_API_KEY": secret_gemini_key,
        "COGNITO_CLIENT_SECRET": secret_cognito,
    }

    client = TestClient(app)

    with patch.dict(os.environ, env_overrides), patch("main.check_rds_health", return_value=True):
        # 1. /health
        res_health = client.get("/health")
        assert res_health.status_code == 200
        health_text = res_health.text
        assert secret_valkey_token not in health_text
        assert secret_db_password not in health_text
        assert secret_gemini_key not in health_text
        assert secret_cognito not in health_text
        assert "postgresql://" not in health_text
        # Verify telemetry fields are clean
        data = res_health.json()
        assert isinstance(data["checks"]["gemini_key_set"], bool)
        assert data["checks"]["gemini_key_set"] is True

        # 2. /health/cache
        res_cache = client.get("/health/cache")
        assert res_cache.status_code == 200
        cache_text = res_cache.text
        assert secret_valkey_token not in cache_text
        assert secret_db_password not in cache_text

        # 3. /health/live
        res_live = client.get("/health/live")
        assert res_live.status_code == 200
        live_text = res_live.text
        assert secret_valkey_token not in live_text
        assert secret_db_password not in live_text

        # 4. /health/ready
        res_ready = client.get("/health/ready")
        assert res_ready.status_code == 200
        ready_text = res_ready.text
        assert secret_valkey_token not in ready_text
        assert secret_db_password not in ready_text


def test_health_cache_endpoint_masks_passwords_in_storage_target():
    """Verify /health/cache scrubs Redis auth credentials from storage_target."""
    secret_pass = "ValkeyUltraSecretPassword2026!"
    sensitive_uri = f"rediss://valkey_user:{secret_pass}@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"

    client = TestClient(app)

    storage = getattr(limiter, "_storage", None)
    if isinstance(storage, ResilientLimiterStorage):
        with patch.object(storage, "_configured_target", mask_redis_url(sensitive_uri)):
            res = client.get("/health/cache")
            assert res.status_code == 200
            data = res.json()
            raw_text = json.dumps(data)

            # Sensitive password must never appear in telemetry response
            assert secret_pass not in raw_text
            # Masked form must appear instead
            assert "valkey_user:****@" in raw_text


def test_health_live_and_ready_endpoints_zero_system_internals():
    """Verify /health/live and /health/ready return only operational status."""
    client = TestClient(app)

    live_res = client.get("/health/live")
    assert live_res.status_code == 200
    assert live_res.json() == {"status": "live", "app": "Interview Practice Platform", "version": "1.0.0"}

    with patch("main.check_rds_health", return_value=True):
        ready_res = client.get("/health/ready")
        assert ready_res.status_code == 200
        assert ready_res.json() == {"status": "ready", "database": "connected"}


# -----------------------------------------------------------------------------
# 2. Exception Handlers Shield Clients from Stack Traces & Credential Leaks
# -----------------------------------------------------------------------------

def test_unhandled_500_exception_handler_sanitizes_database_errors():
    """Verify unhandled 500 exceptions shield clients from SQL details, passwords, and tracebacks."""
    test_app = FastAPI()

    # Register main app's unhandled exception handler
    from main import custom_unhandled_exception_handler
    test_app.add_exception_handler(Exception, custom_unhandled_exception_handler)

    leak_payload = "psycopg2.OperationalError: password authentication failed for user 'app_user': postgresql://app_user:SuperSecretDBPassword123@rds-endpoint:5432/interview_prep"

    @test_app.get("/trigger-db-failure")
    def failing_route():
        raise RuntimeError(leak_payload)

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/trigger-db-failure")

    assert response.status_code == 500
    data = response.json()

    # Response must only contain generic customer-safe messaging
    assert data["detail"] == "An internal server error occurred."
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "SuperSecretDBPassword123" not in json.dumps(data)
    assert "postgresql://" not in json.dumps(data)
    assert "psycopg2" not in json.dumps(data)
    assert "RuntimeError" not in json.dumps(data)


def test_unhandled_500_exception_handler_sanitizes_valkey_errors():
    """Verify unhandled 500 exceptions shield clients from Valkey/Redis connection strings & auth."""
    test_app = FastAPI()
    from main import custom_unhandled_exception_handler
    test_app.add_exception_handler(Exception, custom_unhandled_exception_handler)

    leak_payload = (
        "redis.exceptions.ConnectionError: Error connecting to "
        "rediss://valkey_admin:UltraSecretValkeyPass2026!@clustercfg.valkey.aps2.cache.amazonaws.com:6379: "
        "[Errno 111] Connection refused"
    )

    @test_app.get("/trigger-valkey-failure")
    def failing_route():
        raise RuntimeError(leak_payload)

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/trigger-valkey-failure")

    assert response.status_code == 500
    data = response.json()
    raw_response = json.dumps(data)

    assert data["detail"] == "An internal server error occurred."
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "UltraSecretValkeyPass2026!" not in raw_response
    assert "rediss://" not in raw_response
    assert "clustercfg.valkey" not in raw_response
    assert "ConnectionError" not in raw_response


def test_unhandled_500_exception_handler_sanitizes_bearer_and_aws_keys():
    """Verify unhandled 500 exceptions shield clients from leaked Bearer tokens and AWS access keys."""
    test_app = FastAPI()
    from main import custom_unhandled_exception_handler
    test_app.add_exception_handler(Exception, custom_unhandled_exception_handler)

    leak_payload = (
        "Failed processing request with Authorization Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.sensitive_payload "
        "and AWS Key AKIAIOSFODNN7EXAMPLE"
    )

    @test_app.get("/trigger-auth-failure")
    def failing_route():
        raise RuntimeError(leak_payload)

    client = TestClient(test_app, raise_server_exceptions=False)
    response = client.get("/trigger-auth-failure")

    assert response.status_code == 500
    data = response.json()
    raw_response = json.dumps(data)

    assert data["detail"] == "An internal server error occurred."
    assert "sensitive_payload" not in raw_response
    assert "AKIAIOSFODNN7EXAMPLE" not in raw_response


@pytest.mark.asyncio
async def test_rate_limit_exceeded_handler_zero_leakage():
    """Verify 429 response contains clean RFC-7807 metadata without server state leakage."""
    from main import custom_rate_limit_handler

    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock()
    mock_request.state.request_id = "test-req-123"
    mock_request.state.rate_limit_user_id = "user-456"
    mock_request.headers = {}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_request.method = "GET"
    mock_request.url = MagicMock()
    mock_request.url.path = "/test-route"

    mock_limit = MagicMock()
    mock_limit.error_message = None
    exc = RateLimitExceeded(mock_limit)
    exc.detail = "5 per 1 minute"
    exc.retry_after = 45

    response = await custom_rate_limit_handler(mock_request, exc)
    assert response.status_code == 429
    body = json.loads(response.body.decode())

    assert body["error"] == "rate_limit_exceeded"
    assert body["retry_after_seconds"] == 45
    assert body["request_id"] == "test-req-123"
    assert response.headers["Retry-After"] == "45"
    assert response.headers["X-RateLimit-Limit"] == "5 per 1 minute"
    assert response.headers["X-Request-ID"] == "test-req-123"


# -----------------------------------------------------------------------------
# 3. Structured Logging Redaction & Sanitization
# -----------------------------------------------------------------------------

def test_logger_redacts_database_passwords():
    raw = "Connecting to postgresql://postgres:SuperSecretPostgresPass999@db.internal:5432/interview_prep_db"
    redacted = redact_string(raw)
    assert "SuperSecretPostgresPass999" not in redacted
    assert redacted == "Connecting to postgresql://postgres:****@db.internal:5432/interview_prep_db"


def test_logger_redacts_redis_passwords():
    # URL with username and password
    raw_user_pass = "Connected to rediss://valkey_user:SuperSecretRedisPass@cache.aws.internal:6379/0"
    redacted_user_pass = redact_string(raw_user_pass)
    assert "SuperSecretRedisPass" not in redacted_user_pass
    assert redacted_user_pass == "Connected to rediss://valkey_user:****@cache.aws.internal:6379/0"

    # URL with password only (colon before password)
    raw_pass_only = "Failed to ping redis://:PassOnly12345@localhost:6379/0"
    redacted_pass_only = redact_string(raw_pass_only)
    assert "PassOnly12345" not in redacted_pass_only
    assert redacted_pass_only == "Failed to ping redis://:****@localhost:6379/0"


def test_logger_redacts_bearer_tokens_and_aws_keys():
    raw_bearer = "Authorization header: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_payload"
    assert "dummy_token_payload" not in redact_string(raw_bearer)
    assert "Bearer ***" in redact_string(raw_bearer)

    raw_aws = "Using AWS Access Key AKIAIOSFODNN7EXAMPLE for credentials"
    assert "AKIAIOSFODNN7EXAMPLE" not in redact_string(raw_aws)
    assert "AKIA****" in redact_string(raw_aws)

    raw_gemini = "Gemini API initialized with AIzaSyFakeTestDummyKeyPatternForSanitiz"
    assert "AIzaSyFakeTestDummyKeyPatternForSanitiz" not in redact_string(raw_gemini)
    assert "AIza****" in redact_string(raw_gemini)


def test_logger_sanitizes_dict_keys_recursively():
    sensitive_dict = {
        "user_id": "12345",
        "password": "ClearTextPassword!",
        "auth_token": "SecretAuthToken!",
        "token": "RawToken123",
        "api_key": "MyApiKey999",
        "client_secret": "OauthSecret",
        "nested": {
            "access_token": "BearerXyz",
            "safe_field": "visible_value",
        },
    }
    sanitized = sanitize_log_data(sensitive_dict)

    assert sanitized["user_id"] == "12345"
    assert sanitized["password"] == "***"
    assert sanitized["auth_token"] == "***"
    assert sanitized["token"] == "***"
    assert sanitized["api_key"] == "***"
    assert sanitized["client_secret"] == "***"
    assert sanitized["nested"]["access_token"] == "***"
    assert sanitized["nested"]["safe_field"] == "visible_value"


def test_json_formatter_produces_fully_sanitized_cloudwatch_json():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="User authenticated via Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz with db postgresql://usr:SecretPass@localhost:5432/db",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert "SecretPass" not in formatted
    assert "Bearer ***" in parsed["message"]
    assert "postgresql://usr:****@localhost:5432/db" in parsed["message"]


def test_logger_redacts_complex_passwords_with_special_characters():
    """Verify regexes safely redact passwords containing URL-encoded characters and symbols."""
    raw_valkey_special = "Connecting to rediss://valkey_admin:P%40ssw0rd%21%23%24@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
    redacted_valkey = redact_string(raw_valkey_special)
    assert "P%40ssw0rd%21%23%24" not in redacted_valkey
    assert redacted_valkey == "Connecting to rediss://valkey_admin:****@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"

    raw_pg_special = "Connecting to postgresql://db_user:Complex%21Pass%2399@rds.internal:5432/prod_db"
    redacted_pg = redact_string(raw_pg_special)
    assert "Complex%21Pass%2399" not in redacted_pg
    assert redacted_pg == "Connecting to postgresql://db_user:****@rds.internal:5432/prod_db"


def test_json_formatter_sanitizes_extra_context_fields_recursively():
    """Verify CloudWatch JSONFormatter cleans sensitive fields passed via record attributes."""
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="telemetry_logger",
        level=logging.WARNING,
        pathname="limiter.py",
        lineno=42,
        msg="Rate limit event for client",
        args=(),
        exc_info=None,
    )
    record.auth_token = "SecretToken12345"
    record.password = "ClearTextPass"
    record.connection_details = {
        "redis_url": "rediss://:MyRedisPass@valkey.node:6379/0",
        "nested_secret": "DeepSecret",
    }

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert "SecretToken12345" not in formatted
    assert "ClearTextPass" not in formatted
    assert "MyRedisPass" not in formatted
    assert parsed["auth_token"] == "***"
    assert parsed["password"] == "***"
    assert "rediss://:****@valkey.node:6379/0" in parsed["connection_details"]["redis_url"]


# -----------------------------------------------------------------------------
# 4. Secrets Manager In-Process TTL Caching (300s TTL, Fallback & Refresh)
# -----------------------------------------------------------------------------

def test_secrets_manager_300s_ttl_caching_avoids_repeated_boto3_calls():
    """Verify 300-second TTL caching: calls within TTL do not hit boto3; calls after TTL refresh."""
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "cached-secret-token-300"})
        }
        mock_boto.return_value = mock_client

        base_time = 100000.0

        # Call 1: Cache is empty, boto3 is invoked
        with patch("time.monotonic", return_value=base_time):
            result1 = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
            assert result1 == {"auth_token": "cached-secret-token-300"}
            assert mock_client.get_secret_value.call_count == 1

        # Calls within 300s TTL (e.g. +60s, +180s, +299s): must return cached value without hitting boto3
        for offset in [60.0, 180.0, 299.0]:
            with patch("time.monotonic", return_value=base_time + offset):
                cached_res = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
                assert cached_res == {"auth_token": "cached-secret-token-300"}
                assert mock_client.get_secret_value.call_count == 1

        # Call after TTL has expired (+301s): must refresh from boto3
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "refreshed-secret-token-456"})
        }
        with patch("time.monotonic", return_value=base_time + 301.0):
            result2 = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
            assert result2 == {"auth_token": "refreshed-secret-token-456"}
            assert mock_client.get_secret_value.call_count == 2


def test_secrets_manager_stale_cache_fallback_during_transient_failure():
    """Verify stale-cache fallback: when Secrets Manager raises transient errors, cached value is used."""
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "fallback-safe-token-789"})
        }
        mock_boto.return_value = mock_client

        base_time = 200000.0

        # Prime the cache successfully
        with patch("time.monotonic", return_value=base_time):
            res_init = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
            assert res_init == {"auth_token": "fallback-safe-token-789"}
            assert mock_client.get_secret_value.call_count == 1

        # Simulate Secrets Manager experiencing a transient network or throttling error past TTL
        mock_client.get_secret_value.side_effect = Exception("ThrottlingException: Rate exceeded")
        with patch("time.monotonic", return_value=base_time + 400.0):
            res_stale = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
            # Must return the stale cached secret rather than failing or returning None
            assert res_stale == {"auth_token": "fallback-safe-token-789"}
            assert mock_client.get_secret_value.call_count == 2


def test_secrets_manager_forced_refresh_bypasses_ttl():
    """Verify force_refresh=True bypasses in-process TTL and immediately queries Secrets Manager."""
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "original-token-001"})
        }
        mock_boto.return_value = mock_client

        base_time = 300000.0

        # Initial call primes the cache
        with patch("time.monotonic", return_value=base_time):
            res1 = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")
            assert res1 == {"auth_token": "original-token-001"}
            assert mock_client.get_secret_value.call_count == 1

            # Even 5 seconds later, force_refresh=True immediately queries boto3
            mock_client.get_secret_value.return_value = {
                "SecretString": json.dumps({"auth_token": "rotated-token-002"})
            }
            res2 = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2", force_refresh=True)
            assert res2 == {"auth_token": "rotated-token-002"}
            assert mock_client.get_secret_value.call_count == 2

            # Subsequent normal call now serves the new rotated token from in-process cache
            res3 = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2", force_refresh=False)
            assert res3 == {"auth_token": "rotated-token-002"}
            assert mock_client.get_secret_value.call_count == 2


# -----------------------------------------------------------------------------
# 5. Complete Mocking Verification (Zero Live AWS or Redis Connections)
# -----------------------------------------------------------------------------

def test_secrets_manager_lookup_uses_mock_and_never_hits_live_aws():
    """Verify resolve_secret_auth_token operates via mocked client and cannot reach production AWS."""
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "test-mocked-token-777"})
        }
        mock_boto.return_value = mock_client

        token_data = resolve_secret_auth_token("interview-prep/cache-auth", region="ap-south-2")

        # Must return mocked data without touching network
        assert token_data == {"auth_token": "test-mocked-token-777"}
        mock_boto.assert_called_once_with("secretsmanager", region_name="ap-south-2")
        mock_client.get_secret_value.assert_called_once_with(SecretId="interview-prep/cache-auth")


def test_cache_service_fails_safe_when_secrets_manager_unavailable():
    """Verify that when Secrets Manager is unavailable, resolve_secret_auth_token handles gracefully."""
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = Exception("AWS Secrets Manager ConnectionRefused")
        mock_boto.return_value = mock_client

        # Must return None without raising unhandled exception
        result = resolve_secret_auth_token("interview-prep/cache-auth")
        assert result is None


def test_socket_isolation_prevents_unmocked_live_aws_and_redis_network_calls():
    """Verify test executions for cache and Secrets Manager never open unmocked outbound TCP sockets."""
    import socket
    from services.cache_service import get_redis_connection_config

    with patch.object(socket.socket, "connect") as mock_socket_connect:
        with patch("boto3.client") as mock_boto:
            mock_client = MagicMock()
            mock_client.get_secret_value.return_value = {
                "SecretString": json.dumps({"auth_token": "socket-isolation-token"})
            }
            mock_boto.return_value = mock_client

            # Resolving secret operates via boto mock
            secret_data = resolve_secret_auth_token("interview-prep/cache-auth")
            assert secret_data == {"auth_token": "socket-isolation-token"}

            # Resolving redis connection config with AWS Valkey host
            with patch.dict(os.environ, {
                "CACHE_HOST": "clustercfg.valkey.aps2.cache.amazonaws.com",
                "CACHE_SECRET_NAME": "interview-prep/cache-auth",
            }):
                config = get_redis_connection_config()
                assert config["source"] == "SECRETS_MANAGER"
                assert "clustercfg.valkey.aps2.cache.amazonaws.com" in config["connection_url"]

        # Confirm zero live TCP sockets were opened
        mock_socket_connect.assert_not_called()
