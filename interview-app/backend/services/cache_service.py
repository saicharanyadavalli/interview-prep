"""Centralized, asynchronous-compatible Redis/Valkey caching service for FastAPI.

Provides connection pooling, TLS/ElastiCache authentication, fail-open resilience,
safe serialization (Pydantic/datetime/UUID), dual async/sync cache-aside decorators,
non-blocking SCAN invalidation, and metrics telemetry.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import re
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Set, Union
from urllib.parse import quote_plus, urlparse
from uuid import UUID

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ConnectionError, RedisError, TimeoutError

logger = logging.getLogger(__name__)

# Standard domain TTLs (seconds)
TTL_STATIC_METADATA = 86400    # 24 hours: System design configs, company lists, SQL seed tables
TTL_LEETCODE_DETAIL = 86400    # 24 hours: Problem descriptions, approaches, code solutions
TTL_CATALOG = 3600             # 1 hour: Question catalog, course lists
TTL_LEETCODE_LIST = 1800       # 30 minutes: Paginated leetcode search/filter queries
TTL_SHORT = 300                # 5 minutes: Semi-dynamic lists


def mask_redis_url(url: str) -> str:
    """Mask password credentials in Redis connection strings for safe logging."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.password:
            user = parsed.username or ""
            netloc = f"{user}:****@{parsed.hostname}:{parsed.port or 6379}"
            return parsed._replace(netloc=netloc).geturl()
    except Exception:
        pass
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", url)


class SafeCacheJSONEncoder(json.JSONEncoder):
    """JSON Encoder supporting Pydantic models, datetimes, dates, UUIDs, and sets."""

    def default(self, obj: Any) -> Any:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump()
        if hasattr(obj, "dict") and callable(obj.dict):
            return obj.dict()
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)


def serialize_data(data: Any) -> str:
    """Serialize Python objects to a JSON string using SafeCacheJSONEncoder."""
    return json.dumps(data, cls=SafeCacheJSONEncoder, separators=(",", ":"))


def deserialize_data(payload: Union[str, bytes]) -> Any:
    """Deserialize JSON string or bytes into native Python objects."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def get_redis_connection_config() -> dict[str, Any]:
    """Resolve Redis connection parameters from environment or AWS Secrets Manager.

    Priority:
    1. REDIS_URL or CACHE_URL or CACHE_REDIS_URL environment variable
    2. Discrete environment variables (CACHE_HOST/REDIS_HOST, CACHE_PORT/REDIS_PORT, etc.)
    3. AWS Secrets Manager secret (CACHE_SECRET_NAME or REDIS_SECRET_NAME)
    4. Localhost fallback
    """
    # 1. Direct URL Override
    direct_url = os.getenv("CACHE_URL") or os.getenv("REDIS_URL") or os.getenv("CACHE_REDIS_URL")
    if direct_url and direct_url.strip():
        url = direct_url.strip()
        return {
            "connection_url": url,
            "source": "DIRECT_URL",
            "masked_url": mask_redis_url(url),
        }

    # 2. Discrete environment variables
    host = os.getenv("CACHE_HOST") or os.getenv("REDIS_HOST")
    if host and host.strip():
        port = int(os.getenv("CACHE_PORT", os.getenv("REDIS_PORT", "6379")))
        password = (os.getenv("CACHE_AUTH_TOKEN") or os.getenv("REDIS_PASSWORD") or "").strip()
        ssl_enabled = (os.getenv("CACHE_TLS_ENABLED") or os.getenv("REDIS_SSL", "false")).lower() in ("true", "1", "yes")
        scheme = "rediss" if ssl_enabled else "redis"
        db = os.getenv("CACHE_DB", "0").strip()
        auth = f":{quote_plus(password)}@" if password else ""
        url = f"{scheme}://{auth}{host.strip()}:{port}/{db}"
        return {
            "connection_url": url,
            "source": "ENV_DISCRETE",
            "masked_url": mask_redis_url(url),
        }

    # 3. AWS Secrets Manager resolution
    secret_id = (
        os.getenv("CACHE_SECRET_NAME")
        or os.getenv("REDIS_SECRET_ARN")
        or os.getenv("REDIS_SECRET_NAME")
    )

    if secret_id and secret_id.strip():
        secret_id = secret_id.strip()
        arn_region = None
        if secret_id.startswith("arn:aws:secretsmanager:"):
            arn_parts = secret_id.split(":")
            if len(arn_parts) >= 4 and arn_parts[3]:
                arn_region = arn_parts[3]

        region = (
            os.getenv("AWS_REGION")
            or os.getenv("AWS_DEFAULT_REGION")
            or arn_region
            or "ap-south-2"
        ).strip()

        try:
            import boto3

            client = boto3.client("secretsmanager", region_name=region)
            response = client.get_secret_value(SecretId=secret_id)
            secret_str = response.get("SecretString")
            if secret_str:
                secret_data = json.loads(secret_str)
                host = secret_data.get("host") or secret_data.get("engine_endpoint") or "localhost"
                port = int(secret_data.get("port", 6379))
                password = secret_data.get("auth_token") or secret_data.get("password") or ""
                ssl = str(secret_data.get("ssl", "true")).lower() in ("true", "1", "yes")
                scheme = "rediss" if ssl else "redis"
                auth = f":{quote_plus(password)}@" if password else ""
                url = f"{scheme}://{auth}{host}:{port}/0"

                logger.info("Resolved Redis configuration from Secrets Manager '%s' in '%s'", secret_id, region)
                return {
                    "connection_url": url,
                    "source": "SECRETS_MANAGER",
                    "masked_url": mask_redis_url(url),
                }
        except Exception as exc:
            logger.warning(
                "Could not resolve Redis secret '%s' from Secrets Manager (%s). Defaulting to localhost fallback.",
                secret_id,
                exc,
            )

    # 4. Local Fallback
    fallback_url = "redis://localhost:6379/0"
    return {
        "connection_url": fallback_url,
        "source": "DEFAULT_FALLBACK",
        "masked_url": fallback_url,
    }


class CacheMetrics:
    """Telemetry tracker for cache hits, misses, errors, and latency."""

    def __init__(self) -> None:
        self.hits: int = 0
        self.misses: int = 0
        self.errors: int = 0
        self.total_read_time_ms: float = 0.0
        self.reads_count: int = 0

    def record_hit(self, duration_ms: float) -> None:
        self.hits += 1
        self.reads_count += 1
        self.total_read_time_ms += duration_ms

    def record_miss(self, duration_ms: float) -> None:
        self.misses += 1
        self.reads_count += 1
        self.total_read_time_ms += duration_ms

    def record_error(self) -> None:
        self.errors += 1

    def to_dict(self) -> dict[str, Any]:
        total_requests = self.hits + self.misses
        hit_ratio = round((self.hits / total_requests) * 100, 2) if total_requests > 0 else 0.0
        avg_latency = round(self.total_read_time_ms / self.reads_count, 3) if self.reads_count > 0 else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "total_requests": total_requests,
            "hit_ratio_percent": hit_ratio,
            "average_read_latency_ms": avg_latency,
        }


class CacheService:
    """Centralized, asynchronous Redis/Valkey cache manager."""

    _instance: Optional[CacheService] = None

    def __init__(self) -> None:
        self._pool: Optional[ConnectionPool] = None
        self._client: Optional[aioredis.Redis] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._is_available: bool = False
        self._metrics = CacheMetrics()
        self._prefix: str = os.getenv("CACHE_KEY_PREFIX", "ip:cache:v1:")
        self._enabled: bool = os.getenv("CACHE_ENABLED", "true").lower() in ("true", "1", "yes")
        self._connect_timeout: float = float(os.getenv("CACHE_CONNECT_TIMEOUT", os.getenv("REDIS_CONNECT_TIMEOUT", "2.0")))
        self._socket_timeout: float = float(os.getenv("CACHE_SOCKET_TIMEOUT", os.getenv("REDIS_SOCKET_TIMEOUT", "2.0")))
        self._max_connections: int = int(os.getenv("CACHE_POOL_MAX", os.getenv("REDIS_POOL_MAX", "20")))

    @classmethod
    def get_instance(cls) -> CacheService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for test environments)."""
        cls._instance = None

    @property
    def is_available(self) -> bool:
        return self._enabled and self._is_available and (self._client is not None)

    @property
    def metrics(self) -> CacheMetrics:
        return self._metrics

    def format_key(self, raw_key: str) -> str:
        """Apply canonical namespace prefix to key."""
        clean = raw_key.strip()
        if clean.startswith(self._prefix):
            return clean
        return f"{self._prefix}{clean}"

    async def initialize(self) -> None:
        """Initialize connection pool and ping Redis with fail-open safety."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        if not self._enabled:
            logger.info("CacheService is disabled via CACHE_ENABLED=false.")
            self._is_available = False
            return

        if self._client is not None:
            return

        try:
            config = get_redis_connection_config()
            conn_url = config["connection_url"]

            self._pool = ConnectionPool.from_url(
                conn_url,
                max_connections=self._max_connections,
                socket_connect_timeout=self._connect_timeout,
                socket_timeout=self._socket_timeout,
                health_check_interval=30,
                decode_responses=False,
            )
            self._client = aioredis.Redis(connection_pool=self._pool)

            # Verification ping
            await self._client.ping()
            self._is_available = True
            logger.info(
                "Redis/Valkey CacheService initialized (max_pool=%d, timeout=%.1fs) -> %s",
                self._max_connections,
                self._socket_timeout,
                config["masked_url"],
            )
        except Exception as exc:
            self._is_available = False
            self._metrics.record_error()
            logger.warning(
                "Failed to connect to Redis during startup: %s. Platform will operate in fail-open mode.",
                type(exc).__name__,
            )

    async def close(self) -> None:
        """Gracefully close Redis client and connection pool."""
        self._is_available = False
        if self._client:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if self._pool:
            try:
                await self._pool.disconnect()
            except Exception:
                pass
            self._pool = None
        logger.info("Redis/Valkey CacheService pool disconnected.")

    async def get(self, key: str) -> Optional[Any]:
        """Fetch and deserialize a key. Returns None on cache miss, failure, or timeout."""
        if not self.is_available or not self._client:
            return None

        formatted_key = self.format_key(key)
        start_time = time.perf_counter()
        try:
            raw = await self._client.get(formatted_key)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            if raw is None:
                self._metrics.record_miss(duration_ms)
                return None

            data = deserialize_data(raw)
            self._metrics.record_hit(duration_ms)
            return data
        except (RedisError, TimeoutError, ConnectionError) as exc:
            self._metrics.record_error()
            logger.warning("Redis GET failed for key '%s': %s (failing open)", formatted_key, exc)
            return None
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Unexpected error during Redis GET '%s': %s", formatted_key, exc)
            return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Serialize and store a key with an explicit TTL (seconds). Returns True on success."""
        if not self.is_available or not self._client:
            return False

        formatted_key = self.format_key(key)
        effective_ttl = ttl if ttl is not None else TTL_CATALOG
        try:
            serialized = serialize_data(value)
            await self._client.set(formatted_key, serialized, ex=effective_ttl)
            return True
        except (RedisError, TimeoutError, ConnectionError) as exc:
            self._metrics.record_error()
            logger.warning("Redis SET failed for key '%s': %s (skipping cache write)", formatted_key, exc)
            return False
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Serialization/Redis error during SET '%s': %s", formatted_key, exc)
            return False

    async def invalidate(self, key: str) -> bool:
        """Delete a single key from cache."""
        if not self.is_available or not self._client:
            return False

        formatted_key = self.format_key(key)
        try:
            await self._client.unlink(formatted_key)
            return True
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Redis UNLINK failed for key '%s': %s", formatted_key, exc)
            return False

    async def invalidate_pattern(self, pattern: str) -> int:
        """Safely delete all keys matching a pattern using non-blocking SCAN iteration."""
        if not self.is_available or not self._client:
            return 0

        formatted_pattern = self.format_key(pattern)
        deleted_count = 0
        try:
            batch: list[str] = []
            async for matched_key in self._client.scan_iter(match=formatted_pattern, count=100):
                batch.append(matched_key)
                if len(batch) >= 100:
                    await self._client.unlink(*batch)
                    deleted_count += len(batch)
                    batch = []

            if batch:
                await self._client.unlink(*batch)
                deleted_count += len(batch)

            logger.info("Invalidated %d keys matching pattern '%s'", deleted_count, formatted_pattern)
            return deleted_count
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Redis SCAN/UNLINK failed for pattern '%s': %s", formatted_pattern, exc)
            return deleted_count

    async def ping(self) -> bool:
        """Health probe returning True if Redis responds to PING."""
        if not self._enabled:
            return False
        if not self._client:
            return False
        try:
            res = await self._client.ping()
            return bool(res)
        except Exception:
            return False


def get_cache_service() -> CacheService:
    """Dependency injection / module getter for CacheService."""
    return CacheService.get_instance()


def _extract_request(*args: Any, **kwargs: Any) -> Optional[Any]:
    """Helper to locate FastAPI/Starlette Request in endpoint args/kwargs."""
    for arg in args:
        if hasattr(arg, "state") and hasattr(arg, "headers"):
            return arg
    for v in kwargs.values():
        if hasattr(v, "state") and hasattr(v, "headers"):
            return v
    return None


def cache_aside(
    key_builder: Callable[..., str],
    ttl: int = TTL_CATALOG,
    condition: Optional[Callable[..., bool]] = None,
):
    """Decorator implementing fail-open cache-aside for both async and sync endpoints/services.

    Parameters:
    - key_builder: Callable receiving the wrapped function's (*args, **kwargs) returning the cache key.
    - ttl: Time-to-live in seconds.
    - condition: Optional callable returning True if the result should be cached, False to bypass.
    """
    def decorator(func: Callable):
        is_async = asyncio.iscoroutinefunction(func)

        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                req = _extract_request(*args, **kwargs)
                cache = get_cache_service()

                # Evaluate skip condition (e.g. bypass if user_id is present)
                if condition and not condition(*args, **kwargs):
                    if req is not None:
                        req.state.cache_outcome = "BYPASS"
                    return await func(*args, **kwargs)

                cache_key = key_builder(*args, **kwargs)
                cached_val = await cache.get(cache_key)
                if cached_val is not None:
                    if req is not None:
                        req.state.cache_outcome = "HIT"
                    return cached_val

                if req is not None:
                    req.state.cache_outcome = "MISS"

                result = await func(*args, **kwargs)
                if result is not None and cache.is_available:
                    try:
                        asyncio.create_task(cache.set(cache_key, result, ttl=ttl))
                    except Exception:
                        pass
                return result

            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                req = _extract_request(*args, **kwargs)
                cache = get_cache_service()

                if condition and not condition(*args, **kwargs):
                    if req is not None:
                        req.state.cache_outcome = "BYPASS"
                    return func(*args, **kwargs)

                cache_key = key_builder(*args, **kwargs)

                cached_val = None
                if cache.is_available:
                    try:
                        loop = getattr(cache, "_loop", None)
                        if loop is not None and loop.is_running():
                            future = asyncio.run_coroutine_threadsafe(cache.get(cache_key), loop)
                            cached_val = future.result(timeout=cache._connect_timeout)
                        else:
                            cached_val = asyncio.run(cache.get(cache_key))
                    except Exception:
                        cached_val = None

                if cached_val is not None:
                    if req is not None:
                        req.state.cache_outcome = "HIT"
                    return cached_val

                if req is not None:
                    req.state.cache_outcome = "MISS"

                result = func(*args, **kwargs)
                if result is not None and cache.is_available:
                    try:
                        loop = getattr(cache, "_loop", None)
                        if loop is not None and loop.is_running():
                            asyncio.run_coroutine_threadsafe(cache.set(cache_key, result, ttl=ttl), loop)
                        else:
                            asyncio.run(cache.set(cache_key, result, ttl=ttl))
                    except Exception:
                        pass
                return result

            return sync_wrapper

    return decorator
