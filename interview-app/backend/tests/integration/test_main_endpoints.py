"""Integration tests for root health endpoints, CORS headers, and rate limiting handler."""

import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def test_root_health_check_returns_200_ok(unauth_client: TestClient):
    """Verify GET / returns 200 with application status metadata."""
    res = unauth_client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert data["app"] == "Interview Practice Platform"


def test_health_check_returns_status_and_checks(unauth_client: TestClient):
    """Verify GET /health checks environment configuration, cache, and RDS status."""
    with patch("main.check_rds_health", return_value=True):
        res = unauth_client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ("ok", "degraded", "partial")
        assert "checks" in data
        assert "gemini_key_set" in data["checks"]
        assert "rds_connected" in data["checks"]
        assert "redis_connected" in data["checks"]
        assert "cognito_configured" in data["checks"]


def test_health_cache_diagnostics_endpoint(unauth_client: TestClient):
    """Verify GET /health/cache returns cache metrics and telemetry."""
    res = unauth_client.get("/health/cache")
    assert res.status_code == 200
    data = res.json()
    assert "available" in data
    assert "ping_ok" in data
    assert "metrics" in data
    assert "hits" in data["metrics"]
    assert "misses" in data["metrics"]


def test_health_live_endpoint(unauth_client: TestClient):
    """Verify GET /health/live returns 200 liveness probe."""
    res = unauth_client.get("/health/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "live"


def test_health_ready_endpoint_healthy(unauth_client: TestClient):
    """Verify GET /health/ready returns 200 when database check succeeds."""
    with patch("main.check_rds_health", return_value=True):
        res = unauth_client.get("/health/ready")
        assert res.status_code == 200
        assert res.json()["status"] == "ready"
        assert res.json()["database"] == "connected"


def test_health_ready_endpoint_unhealthy_returns_503(unauth_client: TestClient):
    """Verify GET /health/ready returns 503 when database connectivity fails."""
    with patch("main.check_rds_health", return_value=False):
        res = unauth_client.get("/health/ready")
        assert res.status_code == 503
        assert res.json()["status"] == "not_ready"
        assert res.json()["database"] == "disconnected"


def test_cors_headers_present_on_response(unauth_client: TestClient):
    """Verify CORS allow headers are included."""
    res = unauth_client.get(
        "/",
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 200
    assert "access-control-allow-origin" in res.headers


def test_custom_rate_limit_exceeded_handler_returns_rfc7807(client: TestClient):
    """Verify triggering rate limit returns RFC-7807 429 response with headers."""
    from limiter import limiter
    limiter.reset()

    def dummy_stream(*args, **kwargs):
        yield "Dummy response"

    with patch("routes.assistant.ask_gemini_stream", side_effect=dummy_stream):
        payload = {
            "interview_question": "Two Sum",
            "user_doubt": "Complexity hint?",
            "conversation_history": [],
        }

        # 5 allowed calls
        for _ in range(5):
            client.post("/assistant/ask", json=payload)

        # 6th call hits rate limit
        res = client.post("/assistant/ask", json=payload)
        assert res.status_code == 429
        data = res.json()
        assert data["error"] == "rate_limit_exceeded"
        assert "detail" in data
        assert "retry_after_seconds" in data
        assert "Retry-After" in res.headers
        assert "X-RateLimit-Limit" in res.headers
        assert "X-Request-ID" in res.headers
