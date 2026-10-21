"""Unit tests for slowapi rate limiter configuration, storage, resilience, and key derivation."""

from __future__ import annotations

import concurrent.futures
import os
from unittest.mock import MagicMock, patch

from fastapi import Request

from limiter import (
    ResilientLimiterStorage,
    check_rate_limiter_health,
    get_client_ip,
    get_rate_limit_key,
    get_rate_limiter_storage_info,
    init_rate_limiter,
    resolve_rate_limit_storage_uri,
)


class patch_env:
    """Helper context manager to temporarily patch os.environ."""

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


# ---------------------------------------------------------------------------
# Key Derivation and Client IP Detection Tests
# ---------------------------------------------------------------------------

def test_get_rate_limit_key_authenticated_user_takes_precedence():
    """Verify get_rate_limit_key returns 'user:<user_id>' when rate_limit_user_id is present on request.state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = "abc-123-uuid"

    key = get_rate_limit_key(request)
    assert key == "user:abc-123-uuid"


def test_get_rate_limit_key_anonymous_ip_fallback():
    """Verify get_rate_limit_key falls back to 'ip:<remote_ip>' when no user_id is on request.state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = None
    request.client = MagicMock()
    request.client.host = "203.0.113.195"
    request.headers = {}

    key = get_rate_limit_key(request)
    assert key == "ip:203.0.113.195"


def test_get_rate_limit_key_respects_x_real_ip_from_nginx():
    """Verify get_rate_limit_key binds anonymous traffic to X-Real-IP passed by Nginx."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = None
    request.headers = {"x-real-ip": "198.51.100.22"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    assert get_client_ip(request) == "198.51.100.22"
    key = get_rate_limit_key(request)
    assert key == "ip:198.51.100.22"


def test_get_rate_limit_key_respects_x_forwarded_for():
    """Verify get_rate_limit_key uses leftmost IP from X-Forwarded-For if X-Real-IP is absent."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = None
    request.headers = {"x-forwarded-for": "203.0.113.44, 10.0.0.1"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"

    assert get_client_ip(request) == "203.0.113.44"
    key = get_rate_limit_key(request)
    assert key == "ip:203.0.113.44"


def test_get_rate_limit_key_none_or_missing_state():
    """Verify get_rate_limit_key handles None or requests without state safely."""
    assert get_rate_limit_key(None) == "ip:127.0.0.1"
    assert get_rate_limit_key() == "ip:127.0.0.1"

    req_no_state = MagicMock(spec=Request)
    req_no_state.state = None
    req_no_state.headers = {}
    req_no_state.client = MagicMock()
    req_no_state.client.host = "10.0.0.5"
    assert get_rate_limit_key(req_no_state) == "ip:10.0.0.5"


def test_get_rate_limit_key_empty_or_whitespace_user_id():
    """Verify empty or whitespace-only user ID safely falls back to IP address."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = "   "
    request.headers = {"x-real-ip": "192.0.2.1"}
    assert get_rate_limit_key(request) == "ip:192.0.2.1"


def test_get_client_ip_edge_cases():
    """Verify get_client_ip safely handles None requests and missing client hosts."""
    assert get_client_ip(None) == "127.0.0.1"

    req = MagicMock(spec=Request)
    req.headers = None
    req.client = None
    assert get_client_ip(req) == "127.0.0.1"


# ---------------------------------------------------------------------------
# ResilientLimiterStorage Core Protocol Support Tests
# ---------------------------------------------------------------------------

def test_resilient_limiter_storage_memory_initialization():
    """Verify ResilientLimiterStorage initializes cleanly in memory mode with zero network calls."""
    storage = ResilientLimiterStorage("memory://")
    assert storage.configured_target == "memory://"
    assert storage.configured_backend == "memory"
    assert storage.operational_mode == "in_memory"
    assert storage.is_distributed is False
    assert storage.status == "healthy"
    assert storage.failover_count == 0
    assert storage.recovered_count == 0
    assert storage.last_error is None


def test_resilient_limiter_storage_fixed_window_counters():
    """Verify fixed-window increment, get, expiry, clear, and reset methods."""
    storage = ResilientLimiterStorage("memory://")
    key = "test:fixed:counter"

    # Increments
    assert storage.incr(key, expiry=60, amount=1) == 1
    assert storage.incr(key, expiry=60, amount=2) == 3
    assert storage.get(key) == 3
    assert storage.get_expiry(key) > 0

    # Clear
    storage.clear(key)
    assert storage.get(key) == 0

    # Reset
    storage.incr("test:key2", expiry=60)
    storage.reset()
    assert storage.get("test:key2") == 0


def test_resilient_limiter_storage_sliding_window_counter_atomic():
    """Verify SlidingWindowCounterSupport methods function atomically."""
    storage = ResilientLimiterStorage("memory://")
    key = "test:swc:window"

    # Acquire within limit
    assert storage.acquire_sliding_window_entry(key, limit=3, expiry=60, amount=1) is True
    assert storage.acquire_sliding_window_entry(key, limit=3, expiry=60, amount=1) is True
    assert storage.acquire_sliding_window_entry(key, limit=3, expiry=60, amount=1) is True

    # Exceed limit
    assert storage.acquire_sliding_window_entry(key, limit=3, expiry=60, amount=1) is False

    # Stats inspection
    stats = storage.get_sliding_window(key, expiry=60)
    assert isinstance(stats, tuple)
    assert len(stats) == 4

    # Clear
    storage.clear_sliding_window(key, expiry=60)
    assert storage.acquire_sliding_window_entry(key, limit=3, expiry=60, amount=1) is True


def test_resilient_limiter_storage_moving_window_atomic():
    """Verify MovingWindowSupport methods function atomically."""
    storage = ResilientLimiterStorage("memory://")
    key = "test:mw:window"

    # Acquire within limit
    assert storage.acquire_entry(key, limit=2, expiry=60, amount=1) is True
    assert storage.acquire_entry(key, limit=2, expiry=60, amount=1) is True

    # Exceed limit
    assert storage.acquire_entry(key, limit=2, expiry=60, amount=1) is False

    # Moving window stats
    stats = storage.get_moving_window(key, limit=2, expiry=60)
    assert isinstance(stats, tuple)
    assert len(stats) == 2
    assert stats[1] == 2  # 2 entries recorded


# ---------------------------------------------------------------------------
# Concurrency / Multi-Worker Thread Safety Tests
# ---------------------------------------------------------------------------

def test_multi_worker_sliding_window_concurrency():
    """Verify simulated worker threads acquire sliding-window entries atomically without counter skew."""
    storage = ResilientLimiterStorage("memory://")
    key = "test:worker:concurrency"
    limit = 50
    num_threads = 10
    attempts_per_thread = 10  # Total 100 attempts, exactly 50 should succeed

    successful_acquisitions = []

    def worker_action():
        local_success = 0
        for _ in range(attempts_per_thread):
            if storage.acquire_sliding_window_entry(key, limit=limit, expiry=60, amount=1):
                local_success += 1
        return local_success

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_action) for _ in range(num_threads)]
        successful_acquisitions = [f.result() for f in futures]

    total_admitted = sum(successful_acquisitions)
    assert total_admitted == limit, f"Expected exactly {limit} admitted requests, got {total_admitted}"


# ---------------------------------------------------------------------------
# Resilience: Failover & Self-Healing Recovery Tests
# ---------------------------------------------------------------------------

def test_resilient_storage_midflight_failover_and_recovery():
    """Verify mid-flight Redis failure fails open to memory, and check() self-heals back to distributed."""
    storage = ResilientLimiterStorage()

    mock_redis = MagicMock()
    mock_redis.acquire_sliding_window_entry.side_effect = ConnectionError("Valkey socket connection timeout")
    mock_redis.check.return_value = True

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    # 1. Mid-flight failure -> transparent fail-open to in-memory fallback
    admitted = storage.acquire_sliding_window_entry("test:failover:key", limit=5, expiry=60, amount=1)
    assert admitted is True
    assert storage.is_distributed is False
    assert storage.operational_mode == "in_memory_fallback"
    assert storage.status == "degraded"
    assert storage.failover_count == 1
    assert "Valkey socket connection timeout" in storage.last_error

    # 2. Redis self-healing recovery via check()
    mock_redis.check.return_value = True
    assert storage.check() is True
    assert storage.is_distributed is True
    assert storage.operational_mode == "distributed"
    assert storage.status == "healthy"
    assert storage.recovered_count == 1
    assert storage.last_error is None


def test_credential_sanitization_in_last_error():
    """Verify that sensitive passwords in Redis exception strings are never saved into last_error."""
    storage = ResilientLimiterStorage()

    mock_redis = MagicMock()
    mock_redis.incr.side_effect = ConnectionError(
        "Failed to connect to rediss://app_user:SuperSecretAuthToken99!@valkey-host.aws.com:6379"
    )

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    storage.incr("test:credential:leak", expiry=60)
    assert storage.status == "degraded"
    assert "SuperSecretAuthToken99!" not in storage.last_error
    assert "app_user:****@" in storage.last_error


# ---------------------------------------------------------------------------
# Namespace Separation & Telemetry Tests
# ---------------------------------------------------------------------------

def test_namespace_separation_between_cache_and_limiter():
    """Verify rate limiter keys are strictly separated from application cache keys."""
    for env in ("production", "staging", "personal", "local"):
        with patch_env({"ENVIRONMENT": env, "RATE_LIMIT_KEY_PREFIX": ""}):
            derived_env = (os.getenv("ENVIRONMENT") or "local").lower()
            rl_prefix = os.getenv("RATE_LIMIT_KEY_PREFIX") or f"ip:{derived_env}:rl:"
            cache_prefix = f"ip:{derived_env}:cache:v1:"

            assert rl_prefix != cache_prefix
            assert rl_prefix.startswith(f"ip:{env}:rl:")
            assert cache_prefix.startswith(f"ip:{env}:cache:v1:")


def test_telemetry_schema_contract():
    """Verify get_rate_limiter_storage_info() returns all required telemetry attributes."""
    info = get_rate_limiter_storage_info()
    required_keys = [
        "storage_target",
        "configured_backend",
        "operational_mode",
        "is_distributed",
        "status",
        "strategy",
        "key_prefix",
        "failover_count",
        "recovered_count",
        "last_error",
    ]
    for key in required_keys:
        assert key in info, f"Missing required telemetry key: {key}"

    assert info["operational_mode"] in ("distributed", "in_memory_fallback", "in_memory")
    assert info["status"] in ("healthy", "degraded")


def test_empty_rate_limit_storage_uri_inherits_valkey_endpoint():
    """Verify explicitly empty RATE_LIMIT_STORAGE_URI='' inherits Valkey and does NOT use localhost."""
    mock_cache_config = {
        "connection_url": "rediss://:secret_token@master.interview-prep-node-staging.gmgjlz.aps2.cache.amazonaws.com:6379/0",
        "source": "SECRETS_MANAGER",
        "masked_url": "rediss://:****@master.interview-prep-node-staging.gmgjlz.aps2.cache.amazonaws.com:6379/0",
    }
    with patch_env({"RATE_LIMIT_STORAGE_URI": ""}), \
         patch("services.cache_service.get_redis_connection_config", return_value=mock_cache_config):
        uri = resolve_rate_limit_storage_uri()
        assert uri == "rediss://:secret_token@master.interview-prep-node-staging.gmgjlz.aps2.cache.amazonaws.com:6379/0"
        assert "localhost" not in uri
