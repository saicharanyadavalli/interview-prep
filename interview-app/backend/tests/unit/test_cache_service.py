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
    mask_redis_url,
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
