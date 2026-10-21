"""Unit tests for distributed rate limiting, proxy header parsing, and key derivation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from fastapi import Request

from limiter import (
    get_client_ip,
    get_rate_limit_key,
    get_rate_limiter_storage_info,
    resolve_rate_limit_storage_uri,
)


def _build_mock_request(
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
    user_id: str | None = None,
) -> Request:
    """Build a mock Request object with configured headers and state."""
    req = MagicMock(spec=Request)
    req.headers = headers or {}
    req.client = MagicMock()
    req.client.host = client_host
    req.state = MagicMock()
    req.state.rate_limit_user_id = user_id
    return req


def test_resolve_rate_limit_storage_uri_explicit():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "rediss://:mypass@cache.aws:6379/1"}):
        assert resolve_rate_limit_storage_uri() == "rediss://:mypass@cache.aws:6379/1"


def test_resolve_rate_limit_storage_uri_from_cache_url():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "", "CACHE_URL": "redis://localhost:6379/0"}):
        assert resolve_rate_limit_storage_uri() == "redis://localhost:6379/0"


def test_resolve_rate_limit_storage_uri_fallback():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "", "CACHE_URL": "", "REDIS_URL": "", "CACHE_HOST": "", "REDIS_HOST": ""}):
        assert resolve_rate_limit_storage_uri() == "memory://"


def test_get_client_ip_prioritizes_x_real_ip():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195", "x-forwarded-for": "198.51.100.1, 10.0.0.1"},
        client_host="10.0.0.2",
    )
    assert get_client_ip(req) == "203.0.113.195"


def test_get_client_ip_falls_back_to_x_forwarded_for():
    req = _build_mock_request(
        headers={"x-forwarded-for": "198.51.100.42, 10.0.0.1"},
        client_host="10.0.0.2",
    )
    assert get_client_ip(req) == "198.51.100.42"


def test_get_client_ip_falls_back_to_client_host():
    req = _build_mock_request(headers={}, client_host="192.168.1.100")
    assert get_client_ip(req) == "192.168.1.100"


def test_get_rate_limit_key_authenticated_user():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195"},
        user_id="user-uuid-1234",
    )
    assert get_rate_limit_key(req) == "user:user-uuid-1234"


def test_get_rate_limit_key_anonymous():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195"},
        user_id=None,
    )
    assert get_rate_limit_key(req) == "ip:203.0.113.195"


def test_resolve_rate_limit_storage_uri_inherits_cache_config():
    """Verify limiter automatically inherits host and Secrets Manager auth from cache_service."""
    mock_config = {
        "connection_url": "rediss://:resolved_token@cache.aps2.cache.amazonaws.com:6379/0",
        "source": "SECRETS_MANAGER",
        "masked_url": "rediss://:****@cache.aps2.cache.amazonaws.com:6379/0",
    }
    with patch_env({"RATE_LIMIT_STORAGE_URI": ""}), \
         patch("services.cache_service.get_redis_connection_config", return_value=mock_config):
        uri = resolve_rate_limit_storage_uri()
        assert uri == "rediss://:resolved_token@cache.aps2.cache.amazonaws.com:6379/0"


def test_get_rate_limiter_storage_info_observable_telemetry():
    """Verify rate limiter telemetry reveals whether enforcement is distributed or in-memory."""
    info = get_rate_limiter_storage_info()
    assert "mode" in info
    assert "engine" in info
    assert "is_distributed" in info
    assert "storage_target" in info
    assert "key_prefix" in info
    assert "operational_mode" in info
    assert "failover_count" in info
    assert "recovered_count" in info
    assert info["mode"] in ("distributed", "in_memory")


def test_import_time_has_no_secrets_manager_calls():
    """Verify that importing limiter and constructing storage performs no AWS Secrets Manager lookups."""
    with patch("boto3.client") as mock_boto:
        from limiter import ResilientLimiterStorage
        storage = ResilientLimiterStorage()
        assert storage.configured_backend == "memory"
        assert storage.is_distributed is False
        mock_boto.assert_not_called()


def test_init_rate_limiter_handles_temporary_secrets_manager_failure():
    """Verify transient Secrets Manager error during startup results in in-memory fallback without crash."""
    from limiter import ResilientLimiterStorage
    storage = ResilientLimiterStorage()

    # Simulate Secrets Manager failing on startup
    with patch("services.cache_service.resolve_secret_auth_token", return_value=None):
        ok = storage.configure("redis://nonexistent-host:6379/0", test_connection=True)
        assert ok is False
        assert storage.operational_mode == "in_memory_fallback"
        assert storage.is_distributed is False
        assert storage.status == "degraded"
        assert storage.failover_count == 0  # Startup failover, runtime not hit yet

        # In-memory fallback still functions for rate-limiting calls
        count = storage.incr("test:key", expiry=60)
        assert count == 1


def test_runtime_failover_and_recovery():
    """Verify runtime Redis errors trigger transparent failover and subsequent recovery."""
    from limiter import ResilientLimiterStorage
    storage = ResilientLimiterStorage()

    mock_redis = MagicMock()
    mock_redis.check.return_value = True
    mock_redis.incr.side_effect = ConnectionError("Connection refused by peer")

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    # 1. Runtime call fails on primary -> transparent failover to internal memory
    val = storage.incr("test:user:1", expiry=60)
    assert val == 1
    assert storage.is_distributed is False
    assert storage.operational_mode == "in_memory_fallback"
    assert storage.failover_count == 1
    assert storage.status == "degraded"

    # 2. Subsequent call uses fallback storage directly
    val2 = storage.incr("test:user:1", expiry=60)
    assert val2 == 2

    # 3. Redis recovers
    mock_redis.check.return_value = True
    assert storage.check() is True
    assert storage.is_distributed is True
    assert storage.operational_mode == "distributed"
    assert storage.recovered_count == 1
    assert storage.status == "healthy"


def test_fastapi_slowapi_integration_compatibility():
    """Verify existing @limiter.limit() decorators function seamlessly with ResilientLimiterStorage."""
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from limiter import limiter

    app = FastAPI()
    app.state.limiter = limiter

    @app.get("/test-limit")
    @limiter.limit("2/minute")
    def limited_endpoint(request: Request):
        return {"status": "ok"}

    client = TestClient(app)
    limiter.reset()

    r1 = client.get("/test-limit")
    assert r1.status_code == 200

    r2 = client.get("/test-limit")
    assert r2.status_code == 200

    r3 = client.get("/test-limit")
    assert r3.status_code == 429


class patch_env:
    def __init__(self, envs: dict[str, str]):
        self.envs = envs
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.envs.items():
            self.old[k] = os.environ.get(k)
            if v:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]

    def __exit__(self, *args):
        for k, v in self.old.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]
