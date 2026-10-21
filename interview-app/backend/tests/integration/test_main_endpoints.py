"""Integration tests for root health endpoints, CORS headers, and rate limiting handler."""

import os
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from limiter import ResilientLimiterStorage, get_resilient_storage, limiter
from services.cache_service import get_cache_service


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


def test_health_reports_rate_limiter_telemetry_fields(unauth_client: TestClient):
    """Verify /health returns rate_limiter_distributed, rate_limiter_mode, and rate_limiter_status."""
    with patch("main.check_rds_health", return_value=True):
        res = unauth_client.get("/health")
        assert res.status_code == 200
        data = res.json()
        checks = data["checks"]

        assert "rate_limiter_distributed" in checks
        assert isinstance(checks["rate_limiter_distributed"], bool)
        assert "rate_limiter_mode" in checks
        assert checks["rate_limiter_mode"] in ("in_memory", "distributed", "in_memory_fallback")
        assert "rate_limiter_status" in checks
        assert checks["rate_limiter_status"] in ("healthy", "degraded", "uninitialized")


def test_health_cache_reports_backward_compatible_and_rich_telemetry(unauth_client: TestClient):
    """Verify /health/cache returns backward-compatible keys and rich rate_limiter telemetry."""
    res = unauth_client.get("/health/cache")
    assert res.status_code == 200
    data = res.json()

    # Backward-compatible root keys
    assert "available" in data
    assert isinstance(data["available"], bool)
    assert "ping_ok" in data
    assert isinstance(data["ping_ok"], bool)
    assert "metrics" in data
    metrics = data["metrics"]
    for field in ["hits", "misses", "errors", "total_requests", "hit_ratio_percent", "average_read_latency_ms"]:
        assert field in metrics

    # Nested cache diagnostics
    assert "cache" in data
    assert data["cache"]["available"] == data["available"]
    assert data["cache"]["ping_ok"] == data["ping_ok"]

    # Rate limiter telemetry
    assert "rate_limiter" in data
    rl = data["rate_limiter"]
    assert "storage_target" in rl
    assert "configured_backend" in rl
    assert "operational_mode" in rl
    assert "mode" in rl
    assert "engine" in rl
    assert "strategy" in rl
    assert "is_distributed" in rl
    assert "status" in rl
    assert "key_prefix" in rl
    assert "failover_count" in rl
    assert "recovered_count" in rl


def test_health_telemetry_degraded_and_recovery_transitions(unauth_client: TestClient):
    """Verify rate limiter telemetry transitions to degraded on failure and recovers to healthy."""
    storage = get_resilient_storage()
    assert storage is not None

    mock_redis = MagicMock()
    mock_redis.check.return_value = True

    # Save original storage state
    orig_primary = storage._primary_storage
    orig_backend = storage._configured_backend
    orig_target = storage._configured_target
    orig_op_mode = storage._operational_mode
    orig_status = storage._status
    orig_fallback = storage._fallback_active
    orig_target_uri = storage._target_uri

    try:
        # Phase 1: Distributed and Healthy
        storage._primary_storage = mock_redis
        storage._configured_backend = "redis"
        storage._configured_target = "rediss://:****@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
        storage._operational_mode = "distributed"
        storage._status = "healthy"
        storage._fallback_active = False

        res_h1 = unauth_client.get("/health")
        assert res_h1.status_code == 200
        checks1 = res_h1.json()["checks"]
        assert checks1["rate_limiter_distributed"] is True
        assert checks1["rate_limiter_mode"] == "distributed"
        assert checks1["rate_limiter_status"] == "healthy"

        res_c1 = unauth_client.get("/health/cache")
        rl1 = res_c1.json()["rate_limiter"]
        assert rl1["is_distributed"] is True
        assert rl1["operational_mode"] == "distributed"
        assert rl1["status"] == "healthy"

        # Phase 2: Redis fails/degrades -> Transition to in_memory_fallback
        mock_redis.check.return_value = False

        res_h2 = unauth_client.get("/health")
        assert res_h2.status_code == 200
        checks2 = res_h2.json()["checks"]
        assert checks2["rate_limiter_distributed"] is False
        assert checks2["rate_limiter_mode"] == "in_memory_fallback"
        assert checks2["rate_limiter_status"] == "degraded"

        res_c2 = unauth_client.get("/health/cache")
        rl2 = res_c2.json()["rate_limiter"]
        assert rl2["is_distributed"] is False
        assert rl2["operational_mode"] == "in_memory_fallback"
        assert rl2["status"] == "degraded"
        assert rl2["failover_count"] >= 1

        # Phase 3: Redis recovers -> Transition back to distributed and healthy
        mock_redis.check.return_value = True

        res_h3 = unauth_client.get("/health")
        assert res_h3.status_code == 200
        checks3 = res_h3.json()["checks"]
        assert checks3["rate_limiter_distributed"] is True
        assert checks3["rate_limiter_mode"] == "distributed"
        assert checks3["rate_limiter_status"] == "healthy"

        res_c3 = unauth_client.get("/health/cache")
        rl3 = res_c3.json()["rate_limiter"]
        assert rl3["is_distributed"] is True
        assert rl3["operational_mode"] == "distributed"
        assert rl3["status"] == "healthy"
        assert rl3["recovered_count"] >= 1

    finally:
        # Restore original state
        storage._primary_storage = orig_primary
        storage._configured_backend = orig_backend
        storage._configured_target = orig_target
        storage._operational_mode = orig_op_mode
        storage._status = orig_status
        storage._fallback_active = orig_fallback
        storage._target_uri = orig_target_uri


def test_health_endpoint_degraded_when_cache_ping_fails(unauth_client: TestClient):
    """Verify /health returns status 'degraded' when Redis cache ping fails but RDS is ok."""
    cache = get_cache_service()
    with patch.object(cache, "ping", new=AsyncMock(return_value=False)), \
         patch.object(cache, "_enabled", True), \
         patch("main.check_rds_health", return_value=True):
        res = unauth_client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "degraded"
        assert data["checks"]["rds_connected"] is True
        assert data["checks"]["redis_connected"] is False


def test_health_endpoint_unhealthy_when_rds_check_fails(unauth_client: TestClient):
    """Verify /health returns status 'unhealthy' with HTTP 503 when RDS check fails."""
    with patch("main.check_rds_health", return_value=False):
        res = unauth_client.get("/health")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "unhealthy"
        assert data["checks"]["rds_connected"] is False
