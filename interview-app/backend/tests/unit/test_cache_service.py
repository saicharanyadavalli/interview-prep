"""Unit tests for services.cache_service verifying caching, serialization, and fail-open resilience."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel
from redis.exceptions import ConnectionError, TimeoutError

from services.cache_service import (
    CacheService,
    SafeCacheJSONEncoder,
    cache_aside,
    deserialize_data,
    get_cache_service,
    get_redis_connection_config,
    mask_redis_url,
    resolve_secret_auth_token,
    serialize_data,
)


class SampleModel(BaseModel):
    id: int
    name: str


def test_mask_redis_url():
    assert mask_redis_url("redis://:mysecret@localhost:6379/0") == "redis://:****@localhost:6379/0"
    assert mask_redis_url("rediss://user:secret123@elasticache.aws:6379/0") == "rediss://user:****@elasticache.aws:6379/0"
    assert mask_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
    assert mask_redis_url("") == ""


def test_safe_serialization_pydantic_datetime_uuid():
    sample_uuid = uuid4()
    now = datetime.now(timezone.utc)
    data = {
        "model": SampleModel(id=1, name="Graph"),
        "created_at": now,
        "uuid": sample_uuid,
        "tags": {"dfs", "bfs"},
    }
    serialized = serialize_data(data)
    assert "Graph" in serialized
    assert str(sample_uuid) in serialized

    deserialized = deserialize_data(serialized)
    assert deserialized["model"]["id"] == 1
    assert deserialized["model"]["name"] == "Graph"
    assert set(deserialized["tags"]) == {"dfs", "bfs"}


@pytest.mark.asyncio
async def test_cache_service_fail_open_on_timeout():
    """Verify that when Redis times out, get() logs a warning and returns None without raising."""
    service = CacheService()
    service._is_available = True
    service._enabled = True

    mock_client = AsyncMock()
    mock_client.get.side_effect = TimeoutError("Connection to Redis timed out")
    service._client = mock_client

    result = await service.get("test:key")
    assert result is None
    assert service.metrics.errors == 1


@pytest.mark.asyncio
async def test_cache_service_hit_and_miss_metrics():
    service = CacheService()
    service._is_available = True
    service._enabled = True

    mock_client = AsyncMock()
    mock_client.get.side_effect = [None, b'{"status": "ok"}']
    service._client = mock_client

    miss_res = await service.get("miss_key")
    assert miss_res is None
    assert service.metrics.misses == 1

    hit_res = await service.get("hit_key")
    assert hit_res == {"status": "ok"}
    assert service.metrics.hits == 1
    assert service.metrics.to_dict()["hit_ratio_percent"] == 50.0


@pytest.mark.asyncio
async def test_cache_aside_decorator_async():
    mock_db_call = AsyncMock(return_value={"problem": "Two Sum", "difficulty": "Easy"})
    cache_svc = get_cache_service()
    cache_svc._is_available = True
    cache_svc._enabled = True

    mock_client = AsyncMock()
    mock_client.get.return_value = None  # Miss
    mock_client.set = AsyncMock()
    cache_svc._client = mock_client

    @cache_aside(key_builder=lambda qnum: f"leetcode:problem:{qnum}", ttl=60)
    async def fetch_problem(qnum: int):
        return await mock_db_call(qnum)

    # 1. First execution: Misses cache, calls underlying function, writes to cache
    res1 = await fetch_problem(1)
    assert res1["problem"] == "Two Sum"
    assert mock_db_call.call_count == 1

    # 2. Simulate subsequent cache hit
    mock_client.get.return_value = b'{"problem": "Two Sum", "difficulty": "Easy"}'
    res2 = await fetch_problem(1)
    assert res2["problem"] == "Two Sum"
    assert mock_db_call.call_count == 1  # DB not called second time!


@pytest.mark.asyncio
async def test_invalidate_pattern_uses_scan_iter():
    """Verify invalidate_pattern uses non-blocking scan_iter rather than KEYS."""
    service = CacheService()
    service._is_available = True
    service._enabled = True

    mock_client = AsyncMock()

    async def fake_scan_iter(match, count):
        yield "ip:cache:v1:leetcode:problem:1"
        yield "ip:cache:v1:leetcode:problem:2"

    mock_client.scan_iter = fake_scan_iter
    mock_client.unlink = AsyncMock()
    service._client = mock_client

    count = await service.invalidate_pattern("leetcode:problem:*")
    assert count == 2
    mock_client.unlink.assert_called_once_with(
        "ip:cache:v1:leetcode:problem:1",
        "ip:cache:v1:leetcode:problem:2",
    )


def test_resolve_secret_auth_token_json_success():
    """Verify Secrets Manager JSON parsing extracts auth_token."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"engine": "valkey", "username": "default", "auth_token": "secret-xyz-token"}'
        }
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res is not None
        assert res.get("auth_token") == "secret-xyz-token"
        mock_sm.get_secret_value.assert_called_once_with(SecretId="interview-prep/elasticache/auth-personal")


def test_resolve_secret_auth_token_plain_string():
    """Verify Secrets Manager plain-text token fallback."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": "raw-plain-token-999"}
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res is not None
        assert res.get("auth_token") == "raw-plain-token-999"


def test_resolve_secret_auth_token_failure_handled_gracefully():
    """Verify Secrets Manager lookup exceptions are caught without raising."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = Exception("AccessDeniedException: User is not authorized")
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res is None


def test_get_redis_connection_config_direct_url_precedence():
    """Verify explicit CACHE_URL overrides host and secret configuration."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "redis://custom-cache:6379/0",
            "CACHE_HOST": "aws.cache.internal",
            "CACHE_SECRET_NAME": "secret-name",
        },
        clear=False,
    ):
        config = get_redis_connection_config()
        assert config["source"] == "DIRECT_URL"
        assert config["connection_url"] == "redis://custom-cache:6379/0"


def test_get_redis_connection_config_host_and_secrets_manager():
    """Verify CACHE_HOST combined with CACHE_SECRET_NAME extracts token and detects TLS."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_HOST": "interview-prep-cache.xxxxxx.0001.aps2.cache.amazonaws.com",
            "CACHE_SECRET_NAME": "interview-prep/elasticache/auth-personal",
            "CACHE_PORT": "6379",
            "CACHE_DB": "0",
        },
        clear=False,
    ), patch(
        "services.cache_service.resolve_secret_auth_token",
        return_value={"auth_token": "resolved-secret-pwd"},
    ):
        config = get_redis_connection_config()
        assert config["source"] == "SECRETS_MANAGER"
        assert "rediss://:resolved-secret-pwd@interview-prep-cache" in config["connection_url"]
        assert config["connection_url"].endswith(":6379/0")
        assert "rediss://:****@interview-prep-cache" in config["masked_url"]


def test_get_redis_connection_config_local_docker_without_aws():
    """Verify local discrete host configuration operates without Secrets Manager or TLS."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_SECRET_NAME": "",
            "REDIS_SECRET_ARN": "",
            "REDIS_SECRET_NAME": "",
            "CACHE_HOST": "redis",
            "CACHE_PORT": "6379",
            "CACHE_TLS_ENABLED": "false",
        },
        clear=False,
    ):
        config = get_redis_connection_config()
        assert config["source"] == "ENV_DISCRETE"
        assert config["connection_url"] == "redis://redis:6379/0"


@pytest.mark.asyncio
async def test_failed_connection_reinitialization_does_not_retain_stale_client():
    """Verify that when initial ping fails, _client and _pool are cleaned up so later retry succeeds."""
    CacheService.reset_instance()
    service = CacheService.get_instance()
    service._enabled = True

    # 1. First initialization attempt fails on ping
    mock_failing_client = AsyncMock()
    mock_failing_client.ping.side_effect = ConnectionError("Could not connect to Redis")

    with patch("redis.asyncio.connection.ConnectionPool.from_url"), \
         patch("redis.asyncio.Redis", return_value=mock_failing_client):
        await service.initialize()
        assert service.is_available is False
        assert service._client is None
        assert service._pool is None

    # 2. Second initialization attempt succeeds
    mock_working_client = AsyncMock()
    mock_working_client.ping.return_value = True

    with patch("redis.asyncio.connection.ConnectionPool.from_url"), \
         patch("redis.asyncio.Redis", return_value=mock_working_client):
        await service.initialize()
        assert service.is_available is True
        assert service._client is not None
    CacheService.reset_instance()


@pytest.mark.asyncio
async def test_cache_aside_bypasses_when_cache_unavailable():
    """Verify that when cache is unavailable, outcome is BYPASS and underlying function runs directly."""
    service = get_cache_service()
    service._is_available = False

    mock_db = AsyncMock(return_value={"data": "fresh_from_db"})
    mock_request = MagicMock()
    mock_request.state = MagicMock()

    @cache_aside(key_builder=lambda req: "test:key")
    async def get_resource(req):
        return await mock_db()

    result = await get_resource(mock_request)
    assert result == {"data": "fresh_from_db"}
    assert mock_request.state.cache_outcome == "BYPASS"
    assert mock_db.call_count == 1


def test_environment_scoped_key_prefix():
    """Verify format_key scopes default prefix with environment name."""
    with patch.dict("os.environ", {"ENVIRONMENT": "staging", "CACHE_KEY_PREFIX": ""}, clear=False):
        svc = CacheService()
        key = svc.format_key("sample:item")
        assert key == "ip:staging:cache:v1:sample:item"
        assert svc.format_key(key) == key  # Idempotent formatting
