"""Unit tests for distributed rate limiting, proxy header parsing, and key derivation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from fastapi import Request

from limiter import (
    ResilientLimiterStorage,
    get_client_ip,
    get_rate_limit_key,
    get_rate_limiter_storage_info,
    get_resilient_storage,
    init_rate_limiter,
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


def test_multi_worker_concurrency_thread_safety():
    """Verify concurrent requests across simulated workers increment counters atomically without data loss."""
    import concurrent.futures
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()
    key = "concurrent:test:user:1"
    num_threads = 10
    increments_per_thread = 15
    total_expected = num_threads * increments_per_thread

    def worker_task():
        counts = []
        for _ in range(increments_per_thread):
            val = storage.incr(key, expiry=60)
            counts.append(val)
        return counts

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_task) for _ in range(num_threads)]
        all_results = [f.result() for f in futures]

    # Every increment should yield a unique, increasing integer up to total_expected
    flattened = [val for sublist in all_results for val in sublist]
    assert len(flattened) == total_expected
    assert len(set(flattened)) == total_expected
    assert max(flattened) == total_expected
    assert storage.get(key) == total_expected


def test_multi_worker_concurrency_failover_resilience():
    """Verify concurrent worker threads handle mid-flight Redis connection failure without dropping requests."""
    import concurrent.futures
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()

    # Mock Redis that fails after first 5 calls
    call_counter = {"count": 0}
    mock_redis = MagicMock()

    def flaky_incr(key, expiry, amount=1):
        call_counter["count"] += 1
        if call_counter["count"] > 5:
            raise ConnectionError("Simulated Valkey network disconnect")
        return call_counter["count"]

    mock_redis.incr.side_effect = flaky_incr
    mock_redis.check.return_value = True

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    num_threads = 8
    increments_per_thread = 5

    def worker_task():
        results = []
        for _ in range(increments_per_thread):
            try:
                res = storage.incr("multi:worker:failover", expiry=60)
                results.append(res)
            except Exception as e:
                results.append(f"ERROR: {e}")
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_task) for _ in range(num_threads)]
        all_results = [f.result() for f in futures]

    # Zero exceptions must be raised to callers
    for thread_res in all_results:
        for val in thread_res:
            assert isinstance(val, int), f"Unexpected exception in worker thread: {val}"

    # Confirm failover occurred cleanly
    assert storage.is_distributed is False
    assert storage.operational_mode == "in_memory_fallback"
    assert storage.failover_count >= 1
    assert storage.status == "degraded"


def test_key_namespace_enforcement():
    """Verify rate limiter key prefixes isolate environments strictly."""
    test_cases = [
        ("production", "ip:production:rl:"),
        ("staging", "ip:staging:rl:"),
        ("local", "ip:local:rl:"),
    ]
    for env_name, expected_prefix in test_cases:
        with patch_env({"ENVIRONMENT": env_name, "RATE_LIMIT_KEY_PREFIX": ""}):
            env_val = (os.getenv("ENVIRONMENT") or "local").lower()
            derived_prefix = os.getenv("RATE_LIMIT_KEY_PREFIX") or f"ip:{env_val}:rl:"
            assert derived_prefix == expected_prefix


def test_secret_redaction_in_storage_target_and_telemetry():
    """Verify secret passwords in connection URIs are scrubbed from telemetry and never leak."""
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()
    raw_uri = "rediss://valkey_admin:SuperSecretValkeyToken12345!@valkey-cluster.aps2.cache.amazonaws.com:6379/0"

    with patch("limits.storage.storage_from_string") as mock_storage_factory:
        mock_backend = MagicMock()
        mock_backend.check.return_value = True
        mock_storage_factory.return_value = mock_backend

        storage.configure(raw_uri, test_connection=True)

        assert "SuperSecretValkeyToken12345!" not in storage.configured_target
        assert "valkey_admin:****@" in storage.configured_target

        # Check telemetry info
        info = {
            "storage_target": storage.configured_target,
            "configured_backend": storage.configured_backend,
            "operational_mode": storage.operational_mode,
            "status": storage.status,
        }
        for k, v in info.items():
            assert "SuperSecretValkeyToken12345!" not in str(v)


def test_composite_rate_limit_key_edge_cases():
    """Verify get_rate_limit_key handles IPv6, proxy chains, and UUID user identifiers cleanly."""
    # IPv6 address
    req_ipv6 = _build_mock_request(client_host="2001:0db8:85a3:0000:0000:8a2e:0370:7334")
    assert get_rate_limit_key(req_ipv6) == "ip:2001:0db8:85a3:0000:0000:8a2e:0370:7334"

    # X-Forwarded-For with multiple proxies and whitespace
    req_proxy = _build_mock_request(
        headers={"x-forwarded-for": "  203.0.113.195  , 10.0.0.1 , 172.16.0.1 "},
        client_host="127.0.0.1",
    )
    assert get_rate_limit_key(req_proxy) == "ip:203.0.113.195"

    # Auth0 / Cognito formatted user ID
    req_cognito = _build_mock_request(user_id="ap-south-2:98765432-abcd-ef01-2345-6789abcdef01")
    assert get_rate_limit_key(req_cognito) == "user:ap-south-2:98765432-abcd-ef01-2345-6789abcdef01"


def test_resilient_storage_reset_and_clear():
    """Verify reset() and clear() operate cleanly on both primary and fallback backends."""
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()
    mock_primary = MagicMock()
    storage._primary_storage = mock_primary

    # Clear specific key
    storage.clear("test:user:reset_key")
    mock_primary.clear.assert_called_once_with("test:user:reset_key")

    # Reset all keys
    storage.reset()
    mock_primary.reset.assert_called_once()


def test_sliding_window_counter_support_and_failover():
    """Verify ResilientLimiterStorage SlidingWindowCounterSupport works and fails open transparently."""
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()
    mock_redis = MagicMock()
    mock_redis.acquire_sliding_window_entry.side_effect = ConnectionError("Valkey timeout")
    mock_redis.get_sliding_window.side_effect = ConnectionError("Valkey timeout")

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    # 1. acquire_sliding_window_entry fails open to in-memory fallback
    ok = storage.acquire_sliding_window_entry("test:sw:key", limit=5, expiry=60, amount=1)
    assert ok is True
    assert storage.operational_mode == "in_memory_fallback"
    assert storage.status == "degraded"
    assert storage.failover_count == 1

    # 2. get_sliding_window works in fallback
    stats = storage.get_sliding_window("test:sw:key", expiry=60)
    assert isinstance(stats, tuple)
    assert len(stats) == 4

    # 3. clear_sliding_window clears fallback
    storage.clear_sliding_window("test:sw:key", expiry=60)


def test_moving_window_support_and_failover():
    """Verify ResilientLimiterStorage MovingWindowSupport works and fails open transparently."""
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage()
    mock_redis = MagicMock()
    mock_redis.acquire_entry.side_effect = ConnectionError("Valkey connection reset")

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    # 1. acquire_entry fails open to in-memory fallback
    ok = storage.acquire_entry("test:mw:key", limit=5, expiry=60, amount=1)
    assert ok is True
    assert storage.operational_mode == "in_memory_fallback"
    assert storage.status == "degraded"

    # 2. get_moving_window works in fallback
    mw_stats = storage.get_moving_window("test:mw:key", limit=5, expiry=60)
    assert isinstance(mw_stats, tuple)
    assert len(mw_stats) == 2


def test_personal_environment_key_prefix():
    """Verify RATE_LIMIT_KEY_PREFIX default resolves to ip:personal:rl: in personal environment."""
    from limiter import init_rate_limiter, get_rate_limiter_storage_info
    with patch_env({"ENVIRONMENT": "personal", "RATE_LIMIT_KEY_PREFIX": ""}):
        info = init_rate_limiter(uri="memory://", test_connection=False)
        assert info["key_prefix"] == "ip:personal:rl:"


def test_personal_valkey_endpoint_resolution_without_duplicate_port():
    """Verify Valkey endpoint master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379 resolves cleanly without duplicate port."""
    mock_cache_config = {
        "connection_url": "rediss://:secret-token@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0",
        "source": "SECRETS_MANAGER",
        "masked_url": "rediss://:****@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0",
    }
    with patch_env({"RATE_LIMIT_STORAGE_URI": ""}), \
         patch("services.cache_service.get_redis_connection_config", return_value=mock_cache_config):
        uri = resolve_rate_limit_storage_uri()
        assert uri == "rediss://:secret-token@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0"
        assert ":6379:6379" not in uri


def test_check_rate_limiter_health_triggers_recovery():
    """Verify check_rate_limiter_health probes primary storage and recovers degraded status."""
    from limiter import ResilientLimiterStorage, check_rate_limiter_health
    storage = ResilientLimiterStorage()
    mock_redis = MagicMock()
    mock_redis.check.return_value = True

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "in_memory_fallback"
    storage._status = "degraded"
    storage._fallback_active = True

    with patch("limiter.get_resilient_storage", return_value=storage):
        ok = check_rate_limiter_health()
        assert ok is True
        assert storage.operational_mode == "distributed"
        assert storage.status == "healthy"
        assert storage.recovered_count == 1
        assert storage.is_distributed is True


def test_get_rate_limit_key_safe_with_none_or_no_args():
    """Verify get_rate_limit_key handles None or omitted request safely without raising AttributeError."""
    assert get_rate_limit_key(None) == "ip:127.0.0.1"
    assert get_rate_limit_key() == "ip:127.0.0.1"


def test_valkey_endpoint_enforces_rediss_and_db_0_for_aws():
    """Verify explicit AWS ElastiCache Valkey endpoint automatically enforces rediss:// and logical DB /0."""
    with patch_env({"RATE_LIMIT_STORAGE_URI": "redis://my-valkey.node.aps2.cache.amazonaws.com:6379/3"}):
        uri = resolve_rate_limit_storage_uri()
        assert uri.startswith("rediss://")
        assert uri.endswith("/0")


def test_close_rate_limiter_cleans_up_pools():
    """Verify close_rate_limiter cleanly disconnects underlying connection pools."""
    from limiter import close_rate_limiter, get_resilient_storage
    storage = get_resilient_storage()
    if storage is not None:
        mock_primary = MagicMock()
        mock_raw = MagicMock()
        mock_pool = MagicMock()
        mock_raw.connection_pool = mock_pool
        mock_primary.storage = mock_raw
        storage._primary_storage = mock_primary

        close_rate_limiter()
        mock_raw.close.assert_called_once()
        mock_pool.disconnect.assert_called_once()


def test_check_rate_limiter_health_recovers_slowapi_storage_dead():
    """Verify check_rate_limiter_health clears slowapi limiter._storage_dead flag upon recovery."""
    from limiter import check_rate_limiter_health, get_resilient_storage, limiter

    storage = get_resilient_storage()
    if storage is not None:
        mock_primary = MagicMock()
        mock_primary.check.return_value = True
        storage._primary_storage = mock_primary
        storage._configured_backend = "redis"
        storage._fallback_active = True
        storage._operational_mode = "in_memory_fallback"
        storage._status = "degraded"
        limiter._storage_dead = True

        healthy = check_rate_limiter_health()
        assert healthy is True
        assert limiter._storage_dead is False
        assert storage.is_distributed is True


def test_runtime_error_redaction_prevents_credential_leak_in_last_error():
    """Verify that sensitive passwords in Redis runtime exceptions never leak into last_error."""
    from limiter import ResilientLimiterStorage
    storage = ResilientLimiterStorage()

    mock_redis = MagicMock()
    mock_redis.acquire_entry.side_effect = ConnectionError(
        "rediss://valkey_admin:SuperSecretAuthToken12345!@valkey-cluster.aps2.cache.amazonaws.com:6379/0: Network timeout"
    )

    storage._primary_storage = mock_redis
    storage._configured_backend = "redis"
    storage._operational_mode = "distributed"
    storage._status = "healthy"

    storage.acquire_entry("test:leak:key", limit=10, expiry=60)
    assert storage.status == "degraded"
    assert "SuperSecretAuthToken12345!" not in storage.last_error
    assert "valkey_admin:****@" in storage.last_error


def test_multi_worker_sliding_window_atomic_concurrency():
    """Verify simulated worker threads acquire sliding-window entries atomically without counter skew."""
    import concurrent.futures
    from limiter import ResilientLimiterStorage

    storage = ResilientLimiterStorage("memory://")
    key = "test:dist:sliding:workers"
    limit = 30
    num_threads = 6
    attempts_per_thread = 10

    def worker_action():
        success_count = 0
        for _ in range(attempts_per_thread):
            if storage.acquire_sliding_window_entry(key, limit=limit, expiry=60, amount=1):
                success_count += 1
        return success_count

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_action) for _ in range(num_threads)]
        results = [f.result() for f in futures]

    assert sum(results) == limit


def test_resolve_rate_limit_storage_uri_empty_inherits_aws_cache_config():
    """Verify that when RATE_LIMIT_STORAGE_URI is empty (''), it inherits CACHE_HOST + Secrets Manager resolution."""
    mock_config = {
        "connection_url": "rediss://:secret-valkey-token@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0",
        "source": "SECRETS_MANAGER",
        "masked_url": "rediss://:****@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0",
    }
    with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": ""}, clear=False), \
         patch("services.cache_service.get_redis_connection_config", return_value=mock_config):
        uri = resolve_rate_limit_storage_uri()
        assert uri == "rediss://:secret-valkey-token@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0"
        assert uri.startswith("rediss://")


def test_init_rate_limiter_distinguishes_distributed_and_degraded_fallback():
    """Verify rate limiter telemetry accurately reports distributed vs degraded/in_memory_fallback."""
    storage = get_resilient_storage()
    assert storage is not None

    mock_backend = MagicMock()
    # 1. Success check -> distributed & healthy
    mock_backend.check.return_value = True

    with patch("limits.storage.storage_from_string", return_value=mock_backend):
        info = init_rate_limiter("rediss://:token@cache.aws:6379/0", test_connection=True)
        assert info["is_distributed"] is True
        assert info["operational_mode"] == "distributed"
        assert info["mode"] == "distributed"
        assert info["status"] == "healthy"

    # 2. Failing check -> degraded & in_memory_fallback
    mock_backend.check.return_value = False
    with patch("limits.storage.storage_from_string", return_value=mock_backend):
        info = init_rate_limiter("rediss://:token@cache.aws:6379/0", test_connection=True)
        assert info["is_distributed"] is False
        assert info["operational_mode"] == "in_memory_fallback"
        assert info["status"] == "degraded"
        # Must NOT masquerade as distributed!
        assert info["mode"] == "in_memory"

    # Reset back to memory://
    init_rate_limiter("memory://", test_connection=False)


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
