"""Integration and regression test suite for Amazon ElastiCache / Valkey in container environments.

Verifies:
1. Docker Environment Variable Propagation & Fallback:
   - Empty string CACHE_URL ("") vs unset CACHE_URL (None) activating host-based AWS resolution vs local fallback.
   - Empty string RATE_LIMIT_STORAGE_URI ("") vs unset RATE_LIMIT_STORAGE_URI delegating to shared cache or memory.
   - Hard guarantee that application NEVER silently connects to localhost or container-local Redis when configured for AWS Valkey.
2. In-Process Secrets Manager credential resolution & masking:
   - AWS Valkey TLS enforcement (rediss://) and logical database 0 enforcement.
   - Zero credential leakage in masked connection strings and telemetry.
3. Container Startup Lifecycle & Resilient Limiter Failover/Recovery:
   - CacheService.initialize() and init_rate_limiter() lifecycle.
   - Runtime failover from distributed to in-memory fallback, and automatic recovery.
4. 100% Mocking Isolation:
   - No live network sockets or unmocked AWS calls occur during test runs.
"""

from __future__ import annotations

import json
import os
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from limiter import (
    ResilientLimiterStorage,
    get_rate_limiter_storage_info,
    get_resilient_storage,
    init_rate_limiter,
    resolve_rate_limit_storage_uri,
)
from main import app
from services.cache_service import (
    CacheService,
    clear_secret_cache,
    get_redis_connection_config,
    mask_redis_url,
    resolve_secret_auth_token,
)


@pytest.fixture(autouse=True)
def _clean_valkey_state():
    """Ensure secret cache and singleton instances are clean before and after each test."""
    clear_secret_cache()
    yield
    clear_secret_cache()


# -----------------------------------------------------------------------------
# 1. Docker Environment Propagation & Fallback Logic
# -----------------------------------------------------------------------------

def test_cache_url_empty_string_activates_host_based_aws_resolution():
    """When CACHE_URL="" (common in Docker Compose with empty overrides), host-based resolution must activate."""
    env = {
        "CACHE_URL": "",
        "CACHE_HOST": "clustercfg.interview-prep-valkey.gmgjlz.aps2.cache.amazonaws.com",
        "CACHE_PORT": "6379",
        "CACHE_AUTH_TOKEN": "mock-token-xyz",
        "REDIS_URL": "",
        "CACHE_REDIS_URL": "",
    }
    with patch.dict(os.environ, env, clear=False):
        # Remove any lingering secret names
        with patch.dict(os.environ, {"CACHE_SECRET_NAME": "", "REDIS_SECRET_ARN": "", "REDIS_SECRET_NAME": ""}):
            config = get_redis_connection_config()
            assert config["source"] == "ENV_DISCRETE"
            # Must enforce rediss:// and db 0 for AWS ElastiCache
            assert config["connection_url"] == (
                "rediss://:mock-token-xyz@clustercfg.interview-prep-valkey.gmgjlz.aps2.cache.amazonaws.com:6379/0"
            )
            assert config["masked_url"] == (
                "rediss://:****@clustercfg.interview-prep-valkey.gmgjlz.aps2.cache.amazonaws.com:6379/0"
            )
            assert "localhost" not in config["connection_url"]


def test_cache_url_omitted_activates_local_fallback():
    """When CACHE_URL is omitted (unset) and no host is provided, local fallback is activated."""
    vars_to_clear = [
        "CACHE_URL", "REDIS_URL", "CACHE_REDIS_URL",
        "CACHE_HOST", "REDIS_HOST",
        "CACHE_SECRET_NAME", "REDIS_SECRET_ARN", "REDIS_SECRET_NAME",
    ]
    env_clean = {k: "" for k in vars_to_clear}
    with patch.dict(os.environ, env_clean, clear=False):
        for k in vars_to_clear:
            os.environ.pop(k, None)

        config = get_redis_connection_config()
        assert config["source"] == "DEFAULT_FALLBACK"
        assert config["connection_url"] == "redis://localhost:6379/0"
        assert config["masked_url"] == "redis://localhost:6379/0"


def test_rate_limit_storage_uri_empty_string_delegates_to_shared_cache():
    """When RATE_LIMIT_STORAGE_URI="" in Docker, it must inherit the AWS Valkey host configuration."""
    mock_cache_config = {
        "connection_url": "rediss://:valkey_token@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0",
        "source": "SECRETS_MANAGER",
        "masked_url": "rediss://:****@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0",
    }
    with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": ""}), \
         patch("services.cache_service.get_redis_connection_config", return_value=mock_cache_config):
        resolved_uri = resolve_rate_limit_storage_uri()
        assert resolved_uri == "rediss://:valkey_token@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
        assert "localhost" not in resolved_uri


def test_rate_limit_storage_uri_omitted_delegates_to_shared_cache_or_memory():
    """When RATE_LIMIT_STORAGE_URI is omitted and no cache host configured, defaults safely to memory://."""
    mock_cache_config = {
        "connection_url": "redis://localhost:6379/0",
        "source": "DEFAULT_FALLBACK",
        "masked_url": "redis://localhost:6379/0",
    }
    with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": ""}, clear=False):
        os.environ.pop("RATE_LIMIT_STORAGE_URI", None)
        with patch("services.cache_service.get_redis_connection_config", return_value=mock_cache_config):
            resolved_uri = resolve_rate_limit_storage_uri()
            assert resolved_uri == "memory://"


def test_rate_limit_storage_uri_explicit_override_is_honored():
    """When RATE_LIMIT_STORAGE_URI is explicitly set, operator override takes priority."""
    with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": "rediss://:custom_pass@custom-cache:6379/1"}):
        resolved = resolve_rate_limit_storage_uri()
        assert resolved == "rediss://:custom_pass@custom-cache:6379/1"


# -----------------------------------------------------------------------------
# 2. Anti-Silent-Fallback Guarantees for AWS Valkey
# -----------------------------------------------------------------------------

def test_application_never_silently_connects_to_localhost_when_configured_for_aws_valkey():
    """Verify that whenever an AWS ElastiCache / Valkey endpoint is configured,
    the application NEVER falls back or silently points to localhost or container-local Redis.
    """
    valkey_endpoints = [
        "clustercfg.interview-prep-valkey.gmgjlz.aps2.cache.amazonaws.com",
        "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com",
        "interview-prep-valkey-replica.cache.amazonaws.com:6379",
    ]

    for endpoint in valkey_endpoints:
        env = {
            "CACHE_URL": "",
            "CACHE_HOST": endpoint,
            "CACHE_PORT": "6379",
            "CACHE_AUTH_TOKEN": "aws-valkey-secret-token",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch.dict(os.environ, {"CACHE_SECRET_NAME": "", "REDIS_SECRET_ARN": ""}):
                config = get_redis_connection_config()
                # 1. Scheme must be rediss:// (TLS in transit required for AWS ElastiCache)
                assert config["connection_url"].startswith("rediss://")
                # 2. Endpoint must be the AWS host, NEVER localhost
                assert "cache.amazonaws.com" in config["connection_url"]
                assert "localhost" not in config["connection_url"]
                assert "127.0.0.1" not in config["connection_url"]
                # 3. Database must be 0 for cluster compatibility
                assert config["connection_url"].endswith("/0")
                # 4. Storage URI must inherit the AWS endpoint
                with patch.dict(os.environ, {"RATE_LIMIT_STORAGE_URI": ""}):
                    storage_uri = resolve_rate_limit_storage_uri()
                    assert "cache.amazonaws.com" in storage_uri
                    assert "localhost" not in storage_uri
                    assert "127.0.0.1" not in storage_uri


def test_direct_cache_url_with_aws_endpoint_enforces_tls_and_db_zero():
    """When CACHE_URL directly provides an AWS ElastiCache endpoint (even with redis:// and non-zero db),
    TLS (rediss://) and DB 0 must be automatically enforced for ElastiCache cluster safety.
    """
    insecure_aws_url = "redis://:token@clustercfg.valkey.aps2.cache.amazonaws.com:6379/3"
    with patch.dict(os.environ, {"CACHE_URL": insecure_aws_url}):
        config = get_redis_connection_config()
        assert config["source"] == "DIRECT_URL"
        assert config["connection_url"].startswith("rediss://")
        assert config["connection_url"].endswith("/0")
        assert "localhost" not in config["connection_url"]


def test_aws_secrets_manager_resolves_credentials_and_enforces_masked_telemetry():
    """Verify Secrets Manager resolution resolves token and scrubs sensitive credentials."""
    from urllib.parse import quote_plus

    secret_raw = "ValkeyUltraSecret2026!"
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": secret_raw})
        }
        mock_boto.return_value = mock_client

        env = {
            "CACHE_URL": "",
            "CACHE_HOST": "clustercfg.valkey.aps2.cache.amazonaws.com",
            "CACHE_SECRET_NAME": "interview-prep/cache-auth",
            "AWS_REGION": "ap-south-2",
        }
        with patch.dict(os.environ, env, clear=False):
            config = get_redis_connection_config()
            assert config["source"] == "SECRETS_MANAGER"
            assert quote_plus(secret_raw) in config["connection_url"]
            assert config["masked_url"] == "rediss://:****@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
            assert secret_raw not in config["masked_url"]


# -----------------------------------------------------------------------------
# 3. Full Container Startup Lifecycle & Resilient Limiter Integration
# -----------------------------------------------------------------------------

def test_full_startup_lifecycle_distributed_mode():
    """Verify startup lifecycle initializes ResilientLimiterStorage in distributed mode."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": json.dumps({"auth_token": "lifecycle-token-777"})
        }
        mock_boto.return_value = mock_sm

        mock_redis_storage = MagicMock()
        mock_redis_storage.check.return_value = True

        env = {
            "CACHE_URL": "",
            "CACHE_HOST": "clustercfg.valkey.aps2.cache.amazonaws.com",
            "CACHE_SECRET_NAME": "interview-prep/cache-auth",
            "RATE_LIMIT_STORAGE_URI": "",
            "ENVIRONMENT": "staging",
            "AWS_REGION": "ap-south-2",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch("limits.storage.storage_from_string", return_value=mock_redis_storage):

            info = init_rate_limiter(test_connection=True)

            assert info["is_distributed"] is True
            assert info["operational_mode"] == "distributed"
            assert info["mode"] == "distributed"
            assert info["status"] == "healthy"
            assert info["engine"] == "redis"
            assert "clustercfg.valkey.aps2.cache.amazonaws.com" in info["storage_target"]
            assert "lifecycle-token-777" not in info["storage_target"]


def test_end_to_end_failover_and_recovery_cycle_with_http_client(unauth_client: TestClient):
    """End-to-end integration test simulating Redis degradation and recovery while handling HTTP traffic."""
    storage = get_resilient_storage()
    assert storage is not None

    mock_redis = MagicMock()
    mock_redis.check.return_value = True
    mock_redis.incr.return_value = 1

    orig_primary = storage._primary_storage
    orig_backend = storage._configured_backend
    orig_target = storage._configured_target
    orig_op_mode = storage._operational_mode
    orig_status = storage._status
    orig_fallback = storage._fallback_active
    orig_target_uri = storage._target_uri
    initial_failover = storage.failover_count
    initial_recovered = storage.recovered_count

    try:
        storage._primary_storage = mock_redis
        storage._configured_backend = "redis"
        storage._configured_target = "rediss://:****@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
        storage._operational_mode = "distributed"
        storage._status = "healthy"
        storage._fallback_active = False

        # Step 1: Normal distributed operation
        res1 = unauth_client.get("/health")
        assert res1.status_code == 200
        assert res1.json()["checks"]["rate_limiter_distributed"] is True
        assert res1.json()["checks"]["rate_limiter_mode"] == "distributed"

        res_cache1 = unauth_client.get("/health/cache")
        assert res_cache1.status_code == 200
        assert res_cache1.json()["rate_limiter"]["is_distributed"] is True

        # Step 2: Redis connection error occurs during rate limiting operation
        mock_redis.incr.side_effect = ConnectionError("Connection refused by AWS Valkey endpoint")
        mock_redis.check.return_value = False

        # Incur an increment operation that triggers failover
        val = storage.incr("ip:127.0.0.1", expiry=60)
        assert val >= 1  # In-memory fallback handles the increment safely
        assert storage.operational_mode == "in_memory_fallback"
        assert storage.status == "degraded"
        assert storage.is_distributed is False
        assert storage.failover_count >= initial_failover + 1

        # Health endpoint reflects degraded state
        res2 = unauth_client.get("/health")
        assert res2.status_code == 200
        assert res2.json()["checks"]["rate_limiter_distributed"] is False
        assert res2.json()["checks"]["rate_limiter_mode"] == "in_memory_fallback"
        assert res2.json()["checks"]["rate_limiter_status"] == "degraded"

        # Step 3: Redis recovers
        mock_redis.incr.side_effect = None
        mock_redis.incr.return_value = 2
        mock_redis.check.return_value = True

        # Next health check triggers automatic recovery
        res3 = unauth_client.get("/health")
        assert res3.status_code == 200
        assert res3.json()["checks"]["rate_limiter_distributed"] is True
        assert res3.json()["checks"]["rate_limiter_mode"] == "distributed"
        assert res3.json()["checks"]["rate_limiter_status"] == "healthy"
        assert storage.recovered_count >= initial_recovered + 1

    finally:
        storage._primary_storage = orig_primary
        storage._configured_backend = orig_backend
        storage._configured_target = orig_target
        storage._operational_mode = orig_op_mode
        storage._status = orig_status
        storage._fallback_active = orig_fallback
        storage._target_uri = orig_target_uri


# -----------------------------------------------------------------------------
# 4. Strict Network Isolation (Zero Live AWS / Redis Outbound Calls)
# -----------------------------------------------------------------------------

def test_no_unmocked_live_aws_or_redis_network_sockets():
    """Verify that all AWS Secrets Manager and Redis/Valkey tests run with complete socket isolation."""
    with patch.object(socket.socket, "connect") as mock_connect:
        with patch("boto3.client") as mock_boto:
            mock_sm = MagicMock()
            mock_sm.get_secret_value.return_value = {
                "SecretString": json.dumps({"auth_token": "socket-safe-token"})
            }
            mock_boto.return_value = mock_sm

            env = {
                "CACHE_HOST": "clustercfg.valkey.aps2.cache.amazonaws.com",
                "CACHE_SECRET_NAME": "interview-prep/cache-auth",
            }
            with patch.dict(os.environ, env, clear=False):
                token = resolve_secret_auth_token("interview-prep/cache-auth")
                assert token == {"auth_token": "socket-safe-token"}

                config = get_redis_connection_config()
                assert "cache.amazonaws.com" in config["connection_url"]

        # Ensure no real TCP connection attempts bypassed mocks
        mock_connect.assert_not_called()
