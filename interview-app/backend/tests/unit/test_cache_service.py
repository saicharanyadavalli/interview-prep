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
    clear_secret_cache,
    deserialize_data,
    get_cache_service,
    get_redis_connection_config,
    mask_redis_url,
    resolve_secret_auth_token,
    serialize_data,
)


@pytest.fixture(autouse=True)
def _reset_secret_cache():
    """Reset secret cache and singleton instances between tests to ensure test isolation."""
    clear_secret_cache()
    yield
    clear_secret_cache()


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


def test_mask_redis_url_comprehensive():
    """Verify mask_redis_url scrubs credentials across varied URL schemas and formats."""
    assert mask_redis_url("redis://:mysecret@localhost:6379/0") == "redis://:****@localhost:6379/0"
    assert mask_redis_url("rediss://valkey_user:token%40123@aws-cache:6379/0") == "rediss://valkey_user:****@aws-cache:6379/0"
    assert mask_redis_url("redis://plain-host:6379/0") == "redis://plain-host:6379/0"
    assert mask_redis_url("") == ""
    assert mask_redis_url(None) == ""


def test_get_redis_connection_config_embedded_secret_host():
    """Verify standalone Secrets Manager resolution when host is embedded in secret dictionary."""
    mock_secret_payload = {
        "host": "clustercfg.valkey-cache.aps2.cache.amazonaws.com",
        "port": 6379,
        "auth_token": "secret-auth-token-999",
        "ssl": "true",
    }
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_HOST": "",
            "REDIS_HOST": "",
            "CACHE_SECRET_NAME": "interview-prep/valkey/credentials",
        },
        clear=False,
    ), patch(
        "services.cache_service.resolve_secret_auth_token",
        return_value=mock_secret_payload,
    ):
        config = get_redis_connection_config()
        assert config["source"] == "SECRETS_MANAGER"
        assert "rediss://:secret-auth-token-999@clustercfg.valkey-cache" in config["connection_url"]
        assert config["connection_url"].endswith(":6379/0")
        assert "rediss://:****@clustercfg.valkey-cache" in config["masked_url"]


def test_resolve_secret_auth_token_extracts_arn_region():
    """Verify Secrets Manager ARN correctly extracts region name for boto3 client."""
    arn = "arn:aws:secretsmanager:ap-south-2:123456789012:secret:interview-prep/cache-token-abc"
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": '{"auth_token": "arn-token-123"}'}
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token(arn)
        assert res == {"auth_token": "arn-token-123"}
        mock_boto.assert_called_once_with("secretsmanager", region_name="ap-south-2")


@pytest.mark.asyncio
async def test_cache_service_set_fail_open_on_error():
    """Verify set() handles Redis connection/timeout errors gracefully without raising."""
    service = CacheService()
    service._is_available = True
    service._enabled = True

    mock_client = AsyncMock()
    mock_client.set.side_effect = TimeoutError("Write operation timed out")
    service._client = mock_client

    ok = await service.set("test:fail_set", {"data": "value"}, ttl=60)
    assert ok is False
    assert service.metrics.errors == 1


@pytest.mark.asyncio
async def test_cache_service_invalidate_single_key():
    """Verify invalidate() deletes single key with canonical prefix and handles failure."""
    service = CacheService()
    service._is_available = True
    service._enabled = True

    mock_client = AsyncMock()
    service._client = mock_client

    # 1. Success
    mock_client.unlink.return_value = 1
    ok = await service.invalidate("questions:detail:42")
    assert ok is True
    formatted = service.format_key("questions:detail:42")
    mock_client.unlink.assert_called_with(formatted)

    # 2. Failure handles gracefully
    mock_client.unlink.side_effect = Exception("Unlink failed")
    fail_ok = await service.invalidate("questions:detail:42")
    assert fail_ok is False
    assert service.metrics.errors >= 1


@pytest.mark.asyncio
async def test_cache_service_ping_scenarios():
    """Verify ping() reflects live client state and disabled flag."""
    service = CacheService()

    # Disabled
    service._enabled = False
    assert await service.ping() is False

    # Enabled but no client
    service._enabled = True
    service._client = None
    assert await service.ping() is False

    # Enabled with responsive client
    mock_client = AsyncMock()
    mock_client.ping.return_value = True
    service._client = mock_client
    assert await service.ping() is True

    # Enabled but client throws
    mock_client.ping.side_effect = ConnectionError("Connection refused")
    assert await service.ping() is False


def test_cache_aside_decorator_sync_function():
    """Verify cache_aside decorator transparently supports synchronous functions."""
    cache_svc = get_cache_service()
    cache_svc._is_available = True
    cache_svc._enabled = True

    mock_client = AsyncMock()
    mock_client.get.return_value = None  # Miss
    mock_client.set = AsyncMock()
    cache_svc._client = mock_client

    mock_db_sync = MagicMock(return_value={"catalog": ["sys-1", "sys-2"]})

    @cache_aside(key_builder=lambda cat: f"sync:catalog:{cat}", ttl=120)
    def fetch_catalog_sync(cat: str):
        return mock_db_sync(cat)

    # 1. First execution: Cache miss -> invokes function -> writes cache
    res1 = fetch_catalog_sync("system-design")
    assert res1 == {"catalog": ["sys-1", "sys-2"]}
    assert mock_db_sync.call_count == 1

    # 2. Subsequent execution: Cache hit -> returns cached value without calling sync function
    mock_client.get.return_value = b'{"catalog": ["sys-1", "sys-2"]}'
    res2 = fetch_catalog_sync("system-design")
    assert res2 == {"catalog": ["sys-1", "sys-2"]}
    assert mock_db_sync.call_count == 1  # Not called again!


@pytest.mark.asyncio
async def test_cache_aside_condition_bypass():
    """Verify condition callable can conditionally bypass caching."""
    cache_svc = get_cache_service()
    cache_svc._is_available = True
    cache_svc._enabled = True

    mock_client = AsyncMock()
    mock_client.get.return_value = b'{"cached": "data"}'
    cache_svc._client = mock_client

    mock_func = AsyncMock(return_value={"cached": "fresh_data"})

    # Condition: Only cache if user_id is None (anonymous)
    @cache_aside(
        key_builder=lambda user_id, req=None: f"profile:{user_id}",
        condition=lambda user_id, req=None: user_id is None,
    )
    async def get_profile(user_id: str | None, req: Any = None):
        return await mock_func(user_id)

    # When user_id is provided, condition returns False -> bypass cache completely
    mock_req = MagicMock()
    mock_req.state = MagicMock()
    mock_req.headers = {}
    res = await get_profile("user-123", req=mock_req)
    assert res == {"cached": "fresh_data"}
    assert mock_req.state.cache_outcome == "BYPASS"
    assert mock_func.call_count == 1


def test_key_namespace_enforcement_across_environments():
    """Verify keys are strictly scoped by environment to prevent cross-environment cache contamination."""
    test_cases = [
        ("production", "ip:production:cache:v1:"),
        ("prod", "ip:prod:cache:v1:"),
        ("staging", "ip:staging:cache:v1:"),
        ("local", "ip:local:cache:v1:"),
    ]
    for env_name, expected_prefix in test_cases:
        with patch.dict("os.environ", {"ENVIRONMENT": env_name, "CACHE_KEY_PREFIX": ""}, clear=False):
            svc = CacheService()
            assert svc._prefix == expected_prefix
            key = svc.format_key("question:42")
            assert key == f"{expected_prefix}question:42"
            # Idempotence: formatting again does not duplicate prefix
            assert svc.format_key(key) == key


def test_resolve_secret_auth_token_in_process_caching():
    """Verify in-process caching ensures Secrets Manager API is not queried on every call."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"auth_token": "cached-valkey-secret"}'
        }
        mock_boto.return_value = mock_sm

        # 1. First call: Hits Secrets Manager
        res1 = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res1 == {"auth_token": "cached-valkey-secret"}
        assert mock_sm.get_secret_value.call_count == 1

        # 2. Second call: Hits in-process memory cache without calling Secrets Manager
        res2 = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res2 == {"auth_token": "cached-valkey-secret"}
        assert mock_sm.get_secret_value.call_count == 1

        # 3. Third call with force_refresh=True: Bypasses cache and queries Secrets Manager
        res3 = resolve_secret_auth_token(
            "interview-prep/elasticache/auth-personal",
            "ap-south-2",
            force_refresh=True,
        )
        assert res3 == {"auth_token": "cached-valkey-secret"}
        assert mock_sm.get_secret_value.call_count == 2


def test_resolve_secret_auth_token_stale_fallback_on_refresh_failure():
    """Verify that if Secrets Manager fails during a refresh, previously cached secret is used."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"auth_token": "initial-good-token"}'
        }
        mock_boto.return_value = mock_sm

        # 1. Populate cache
        res1 = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res1 == {"auth_token": "initial-good-token"}

        # 2. Subsequent call encounters Secrets Manager exception -> falls back to stale cache
        mock_sm.get_secret_value.side_effect = Exception("ThrottlingException: Rate exceeded")
        res2 = resolve_secret_auth_token(
            "interview-prep/elasticache/auth-personal",
            "ap-south-2",
            force_refresh=True,
        )
        assert res2 == {"auth_token": "initial-good-token"}


def test_resolve_secret_auth_token_secret_binary():
    """Verify SecretBinary decoding support when SecretString is omitted."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretBinary": b'{"auth_token": "binary-decoded-token"}'
        }
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token("interview-prep/elasticache/auth-personal", "ap-south-2")
        assert res == {"auth_token": "binary-decoded-token"}


def test_get_redis_connection_config_endpoint_with_port():
    """Verify that CACHE_HOST ending in :6379 splits host and port cleanly without double port."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_HOST": "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379",
            "CACHE_SECRET_NAME": "",
            "CACHE_AUTH_TOKEN": "mytoken",
        },
        clear=False,
    ):
        config = get_redis_connection_config()
        # Should NOT have :6379:6379
        assert ":6379:6379" not in config["connection_url"]
        assert "rediss://:mytoken@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0" == config["connection_url"]
        assert "rediss://:****@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0" == config["masked_url"]


def test_get_redis_connection_config_aws_tls_and_db0_enforcement():
    """Verify *.cache.amazonaws.com endpoints strictly enforce rediss:// and logical DB 0."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_HOST": "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com",
            "CACHE_TLS_ENABLED": "false",  # Attempt to disable TLS on AWS endpoint
            "CACHE_DB": "3",  # Attempt to set non-zero DB
            "CACHE_AUTH_TOKEN": "authtoken",
            "CACHE_PORT": "6379",
        },
        clear=False,
    ):
        config = get_redis_connection_config()
        # Must enforce rediss:// despite CACHE_TLS_ENABLED=false
        assert config["connection_url"].startswith("rediss://")
        # Must enforce logical DB /0 despite CACHE_DB=3
        assert config["connection_url"].endswith("/0")


def test_get_redis_connection_config_direct_url_aws_tls_and_db0_enforcement():
    """Verify direct redis:// URL for *.cache.amazonaws.com is automatically upgraded to rediss:// and DB 0."""
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "redis://:token@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/2",
        },
        clear=False,
    ):
        config = get_redis_connection_config()
        assert config["source"] == "DIRECT_URL"
        assert config["connection_url"].startswith("rediss://")
        assert config["connection_url"].endswith("/0")
        assert config["masked_url"] == "rediss://:****@master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379/0"


def test_resolve_secret_auth_token_ttl_caching_and_expiry():
    """Verify TTL caching: 1st call retrieves from boto3, 2nd call within TTL uses cache, call after TTL expiry refreshes."""
    with patch("boto3.client") as mock_boto, patch("time.monotonic") as mock_time:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = [
            {"SecretString": '{"auth_token": "token-generation-1"}'},
            {"SecretString": '{"auth_token": "token-generation-2"}'},
        ]
        mock_boto.return_value = mock_sm

        # 1. First call at t=100.0 (default TTL=300s -> expires at 400.0)
        mock_time.return_value = 100.0
        res1 = resolve_secret_auth_token("interview-prep/cache/token", "ap-south-2")
        assert res1 == {"auth_token": "token-generation-1"}
        assert mock_sm.get_secret_value.call_count == 1

        # 2. Second call within TTL at t=250.0 (< 400.0) -> served from in-process cache
        mock_time.return_value = 250.0
        res2 = resolve_secret_auth_token("interview-prep/cache/token", "ap-south-2")
        assert res2 == {"auth_token": "token-generation-1"}
        assert mock_sm.get_secret_value.call_count == 1  # No additional Secrets Manager call

        # 3. Third call after TTL expiry at t=450.0 (> 400.0) -> refreshes from Secrets Manager
        mock_time.return_value = 450.0
        res3 = resolve_secret_auth_token("interview-prep/cache/token", "ap-south-2")
        assert res3 == {"auth_token": "token-generation-2"}
        assert mock_sm.get_secret_value.call_count == 2


def test_resolve_secret_auth_token_custom_ttl_via_env():
    """Verify configurable TTL via CACHE_SECRET_CACHE_TTL environment variable."""
    with patch.dict("os.environ", {"CACHE_SECRET_CACHE_TTL": "60"}, clear=False), \
         patch("boto3.client") as mock_boto, \
         patch("time.monotonic") as mock_time:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.side_effect = [
            {"SecretString": '{"auth_token": "token-v1"}'},
            {"SecretString": '{"auth_token": "token-v2"}'},
        ]
        mock_boto.return_value = mock_sm

        # At t=10.0, expires at t=70.0
        mock_time.return_value = 10.0
        res1 = resolve_secret_auth_token("interview-prep/cache/ttl-test", "ap-south-2")
        assert res1 == {"auth_token": "token-v1"}
        assert mock_sm.get_secret_value.call_count == 1

        # At t=50.0 (< 70.0) -> cache hit
        mock_time.return_value = 50.0
        res2 = resolve_secret_auth_token("interview-prep/cache/ttl-test", "ap-south-2")
        assert res2 == {"auth_token": "token-v1"}
        assert mock_sm.get_secret_value.call_count == 1

        # At t=75.0 (> 70.0) -> cache expired, refreshed
        mock_time.return_value = 75.0
        res3 = resolve_secret_auth_token("interview-prep/cache/ttl-test", "ap-south-2")
        assert res3 == {"auth_token": "token-v2"}
        assert mock_sm.get_secret_value.call_count == 2


def test_resolve_secret_auth_token_stale_fallback_on_expired_lookup_failure():
    """Verify that when TTL expires and Secrets Manager lookup fails, stale cached secret is preserved."""
    with patch("boto3.client") as mock_boto, patch("time.monotonic") as mock_time:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": '{"auth_token": "stale-fallback-token"}'}
        mock_boto.return_value = mock_sm

        # 1. Initial retrieval at t=100.0 (expires at 400.0)
        mock_time.return_value = 100.0
        res1 = resolve_secret_auth_token("interview-prep/cache/resilience", "ap-south-2")
        assert res1 == {"auth_token": "stale-fallback-token"}

        # 2. Advance time past TTL to t=500.0; Secrets Manager throws outage exception
        mock_time.return_value = 500.0
        mock_sm.get_secret_value.side_effect = Exception("InternalServerError: Service unavailable")
        res2 = resolve_secret_auth_token("interview-prep/cache/resilience", "ap-south-2")

        # Stale cached secret is returned rather than None or an exception
        assert res2 == {"auth_token": "stale-fallback-token"}


def test_resolve_secret_auth_token_empty_and_whitespace_inputs():
    """Verify empty, whitespace, or None secret IDs safely return None without querying AWS."""
    with patch("boto3.client") as mock_boto:
        assert resolve_secret_auth_token("") is None
        assert resolve_secret_auth_token("   ") is None
        assert resolve_secret_auth_token(None) is None
        mock_boto.assert_not_called()


def test_secret_formats_auth_token_password_and_token_keys():
    """Verify get_redis_connection_config handles JSON payloads with auth_token, password, or token keys."""
    keys_and_values = [
        ({"auth_token": "val-auth-tok"}, "val-auth-tok"),
        ({"password": "val-password"}, "val-password"),
        ({"token": "val-token"}, "val-token"),
    ]

    for payload, expected_pwd in keys_and_values:
        with patch.dict(
            "os.environ",
            {
                "CACHE_URL": "",
                "REDIS_URL": "",
                "CACHE_REDIS_URL": "",
                "CACHE_HOST": "valkey-node.aps2.cache.amazonaws.com",
                "CACHE_SECRET_NAME": "secret/test/keys",
                "CACHE_AUTH_TOKEN": "",
            },
            clear=False,
        ), patch(
            "services.cache_service.resolve_secret_auth_token",
            return_value=payload,
        ):
            config = get_redis_connection_config()
            assert config["source"] == "SECRETS_MANAGER"
            assert f"rediss://:{expected_pwd}@" in config["connection_url"]
            assert "rediss://:****@" in config["masked_url"]


def test_secret_formats_embedded_host_port_ssl_custom():
    """Verify standalone Secrets Manager resolution with custom non-AWS host, port, ssl, db, and token."""
    payload = {
        "host": "redis-cluster.internal",
        "port": 6380,
        "ssl": "false",
        "token": "cluster-secret-tok",
        "db": "2",
    }
    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
            "CACHE_HOST": "",
            "REDIS_HOST": "",
            "CACHE_SECRET_NAME": "internal/redis/creds",
        },
        clear=False,
    ), patch(
        "services.cache_service.resolve_secret_auth_token",
        return_value=payload,
    ):
        config = get_redis_connection_config()
        assert config["source"] == "SECRETS_MANAGER"
        assert config["connection_url"] == "redis://:cluster-secret-tok@redis-cluster.internal:6380/2"
        assert config["masked_url"] == "redis://:****@redis-cluster.internal:6380/2"


def test_secret_formats_secret_binary_plain_text():
    """Verify SecretBinary containing plain-text bytes is decoded and wrapped into auth_token."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretBinary": b"plain-binary-auth-token-12345"
        }
        mock_boto.return_value = mock_sm

        res = resolve_secret_auth_token("interview-prep/cache/binary-plain", "ap-south-2")
        assert res == {"auth_token": "plain-binary-auth-token-12345"}


def test_aws_secrets_manager_authentication_ec2_role_standard_chain():
    """Verify boto3 client relies on standard credential chain (IMDSv2) without hardcoded credentials."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": '{"auth_token": "test"}'}
        mock_boto.return_value = mock_sm

        resolve_secret_auth_token("interview-prep/auth-token", "ap-south-2")

        # Verify boto3.client is called only with service name and region_name, no keys or tokens
        mock_boto.assert_called_once_with("secretsmanager", region_name="ap-south-2")
        kwargs = mock_boto.call_args.kwargs
        assert "aws_access_key_id" not in kwargs
        assert "aws_secret_access_key" not in kwargs
        assert "aws_session_token" not in kwargs


def test_region_resolution_precedence():
    """Verify region resolution priority: explicit arg > ARN region > AWS_REGION > AWS_DEFAULT_REGION > ap-south-2."""
    with patch("boto3.client") as mock_boto:
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {"SecretString": '{"auth_token": "test"}'}
        mock_boto.return_value = mock_sm

        # 1. Explicit argument overrides everything
        with patch.dict("os.environ", {"AWS_REGION": "us-east-1"}, clear=False):
            resolve_secret_auth_token("test-secret", region="eu-central-1")
            mock_boto.assert_called_with("secretsmanager", region_name="eu-central-1")

        mock_boto.reset_mock()
        # 2. ARN extracts region when region argument is omitted, even if AWS_REGION is set
        arn = "arn:aws:secretsmanager:ap-south-2:123456789012:secret:cache-token"
        with patch.dict("os.environ", {"AWS_REGION": "us-east-1"}, clear=False):
            resolve_secret_auth_token(arn)
            mock_boto.assert_called_with("secretsmanager", region_name="ap-south-2")

        mock_boto.reset_mock()
        # 3. AWS_REGION environment variable
        with patch.dict("os.environ", {"AWS_REGION": "us-west-2", "AWS_DEFAULT_REGION": "us-east-1"}, clear=False):
            resolve_secret_auth_token("test-secret-env")
            mock_boto.assert_called_with("secretsmanager", region_name="us-west-2")

        mock_boto.reset_mock()
        # 4. AWS_DEFAULT_REGION fallback
        with patch.dict("os.environ", {"AWS_REGION": "", "AWS_DEFAULT_REGION": "sa-east-1"}, clear=False):
            resolve_secret_auth_token("test-secret-env-default")
            mock_boto.assert_called_with("secretsmanager", region_name="sa-east-1")

        mock_boto.reset_mock()
        # 5. Default fallback to ap-south-2
        with patch.dict("os.environ", {"AWS_REGION": "", "AWS_DEFAULT_REGION": ""}, clear=False):
            resolve_secret_auth_token("test-secret-default")
            mock_boto.assert_called_with("secretsmanager", region_name="ap-south-2")


@pytest.mark.asyncio
async def test_connection_pool_default_parameters():
    """Verify default connection pool parameters: timeouts, keepalive, retry, health check."""
    service = CacheService()
    service._enabled = True

    mock_pool_cls = MagicMock()
    mock_client = AsyncMock()
    mock_client.ping.return_value = True

    with patch.dict(
        "os.environ",
        {
            "CACHE_URL": "redis://localhost:6379/0",
            "CACHE_CONNECT_TIMEOUT": "2.0",
            "CACHE_SOCKET_TIMEOUT": "2.0",
            "CACHE_HEALTH_CHECK_INTERVAL": "30",
        },
        clear=False,
    ), patch(
        "redis.asyncio.connection.ConnectionPool.from_url",
        return_value=mock_pool_cls,
    ) as mock_pool_from_url, patch(
        "redis.asyncio.Redis",
        return_value=mock_client,
    ):
        await service.initialize()
        mock_pool_from_url.assert_called_once_with(
            "redis://localhost:6379/0",
            max_connections=20,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
            health_check_interval=30,
            socket_keepalive=True,
            retry_on_timeout=True,
            decode_responses=False,
        )


@pytest.mark.asyncio
async def test_initialize_logs_do_not_leak_passwords(caplog):
    """Verify that when initialize() encounters connection errors containing passwords, logs remain masked."""
    import logging

    service = CacheService()
    service._enabled = True

    raw_password = "super-confidential-valkey-auth-token-999"
    failing_client = AsyncMock()
    failing_client.ping.side_effect = ConnectionError(
        f"Connection refused to rediss://:{raw_password}@clustercfg.valkey.aps2.cache.amazonaws.com:6379/0"
    )

    with caplog.at_level(logging.WARNING), \
         patch.dict(
             "os.environ",
             {
                 "CACHE_URL": "",
                 "REDIS_URL": "",
                 "CACHE_REDIS_URL": "",
                 "CACHE_HOST": "clustercfg.valkey.aps2.cache.amazonaws.com",
                 "CACHE_AUTH_TOKEN": raw_password,
             },
             clear=False,
         ), \
         patch("redis.asyncio.connection.ConnectionPool.from_url"), \
         patch("redis.asyncio.Redis", return_value=failing_client):
        await service.initialize()
        assert service.is_available is False

        # Raw password must NEVER appear in caplog
        assert raw_password not in caplog.text
        # Masked password must appear instead
        assert ":****@" in caplog.text
