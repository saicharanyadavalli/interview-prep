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
    """Mask password credentials in Redis connection strings or log messages for safe logging."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if parsed.password:
            user = parsed.username or ""
            port_part = f":{parsed.port}" if parsed.port else ""
            host_part = parsed.hostname or ""
            netloc = f"{user}:****@{host_part}{port_part}"
            return parsed._replace(netloc=netloc).geturl()
    except Exception:
        pass
    masked = re.sub(r"(://[^:]*:)([^@]+)(@)", r"\g<1>****\g<3>", url)
    return re.sub(r"(:\s*)([^@\s/:]{4,})(@[a-zA-Z0-9.-]+)", r"\g<1>****\g<3>", masked)


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


def _safe_float_env(key: str, default: float) -> float:
    """Safely extract float from environment variable, falling back gracefully on ValueError/TypeError."""
    val = os.getenv(key)
    if not val:
        return default
    try:
        return float(val.strip().strip("'\""))
    except (ValueError, TypeError):
        return default


def _safe_int_env(key: str, default: int) -> int:
    """Safely extract integer from environment variable, falling back gracefully on ValueError/TypeError."""
    val = os.getenv(key)
    if not val:
        return default
    try:
        return int(val.strip().strip("'\""))
    except (ValueError, TypeError):
        return default


# In-process cache for resolved Secrets Manager payloads: (secret_id, region) -> (payload, expiry_timestamp)
_SECRET_CACHE: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
DEFAULT_SECRET_CACHE_TTL: float = 300.0  # 5 minutes TTL


def clear_secret_cache() -> None:
    """Clear the in-process cache of Secrets Manager secrets (for tests & credential rotation)."""
    _SECRET_CACHE.clear()


def resolve_secret_auth_token(
    secret_id: str,
    region: Optional[str] = None,
    force_refresh: bool = False,
    cache_ttl: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Retrieve secret string or JSON payload from AWS Secrets Manager safely with in-process caching.

    Caches resolved secrets in-process with a configurable TTL (default 300s) to prevent
    redundant Secrets Manager API calls during cache operations and rate-limit checks.

    Handles both JSON documents (e.g. {"auth_token": "..."}) and plain-text token strings.
    Fails safely without raising exceptions or logging sensitive token values.
    """
    if not secret_id or not str(secret_id).strip():
        return None

    secret_clean = str(secret_id).strip().strip("'\"")
    arn_region = None
    if secret_clean.startswith("arn:aws:secretsmanager:"):
        arn_parts = secret_clean.split(":")
        if len(arn_parts) >= 4 and arn_parts[3]:
            arn_region = arn_parts[3]

    effective_region = (
        region
        or arn_region
        or os.getenv("CACHE_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "ap-south-2"
    ).strip().strip("'\"")

    cache_key = (secret_clean, effective_region)
    now = time.monotonic()
    try:
        ttl = cache_ttl if cache_ttl is not None else float(
            os.getenv("CACHE_SECRET_CACHE_TTL", str(DEFAULT_SECRET_CACHE_TTL))
        )
    except (ValueError, TypeError):
        ttl = DEFAULT_SECRET_CACHE_TTL

    # 1. Return in-process cached payload if still valid and refresh not forced
    if not force_refresh and cache_key in _SECRET_CACHE:
        cached_val, expiry = _SECRET_CACHE[cache_key]
        if now < expiry:
            return cached_val

    try:
        import boto3

        client = boto3.client("secretsmanager", region_name=effective_region)
        response = client.get_secret_value(SecretId=secret_clean)
        secret_str = response.get("SecretString")
        if not secret_str:
            secret_binary = response.get("SecretBinary")
            if secret_binary:
                if isinstance(secret_binary, bytes):
                    secret_str = secret_binary.decode("utf-8")
                else:
                    secret_str = str(secret_binary)
            else:
                return None

        result: dict[str, Any]
        try:
            parsed = json.loads(secret_str)
            if isinstance(parsed, dict):
                result = parsed
            else:
                result = {"auth_token": str(parsed)}
        except json.JSONDecodeError:
            result = {"auth_token": secret_str.strip()}

        _SECRET_CACHE[cache_key] = (result, now + ttl)
        return result
    except Exception as exc:
        logger.warning(
            "Could not resolve Redis secret '%s' from Secrets Manager in '%s': %s",
            secret_clean,
            effective_region,
            mask_redis_url(str(exc)),
        )
        # Resilient fallback: If cached value exists (even if expired), use it during transient outages
        if cache_key in _SECRET_CACHE:
            cached_val, _ = _SECRET_CACHE[cache_key]
            logger.info(
                "Falling back to in-process cached secret for '%s' following Secrets Manager lookup failure",
                secret_clean,
            )
            return cached_val
        return None


def get_redis_connection_config() -> dict[str, Any]:
    """Resolve Redis connection parameters from environment or AWS Secrets Manager.

    Resolution Strategy:
    1. Direct URL Override (CACHE_URL / REDIS_URL / CACHE_REDIS_URL) - used for local Docker or explicit override.
    2. Host-based resolution (CACHE_HOST / REDIS_HOST):
       - If CACHE_SECRET_NAME / REDIS_SECRET_ARN / REDIS_SECRET_NAME is provided, resolves auth_token from Secrets Manager.
       - Otherwise falls back to environment variable CACHE_AUTH_TOKEN / REDIS_PASSWORD.
       - Resolves TLS: Enforces SSL/TLS for AWS ElastiCache / Valkey endpoints (*.cache.amazonaws.com) or explicit CACHE_TLS_ENABLED / REDIS_SSL.
       - Resolves DB: CACHE_DB (enforces '0' for Valkey/ElastiCache endpoints for cluster compatibility).
    3. Standalone Secrets Manager resolution (when host is packaged inside the secret document).
    4. Localhost fallback (redis://localhost:6379/0).
    """
    # 1. Direct URL Override
    raw_direct = os.getenv("CACHE_URL") or os.getenv("REDIS_URL") or os.getenv("CACHE_REDIS_URL")
    direct_url = raw_direct.strip().strip("'\"") if raw_direct else ""

    raw_host = os.getenv("CACHE_HOST") or os.getenv("REDIS_HOST")
    host_candidate = raw_host.strip().strip("'\"") if raw_host else ""
    is_aws_host = bool(host_candidate and ".cache.amazonaws.com" in host_candidate.lower())

    if direct_url:
        # If direct_url is the generic default (redis://redis:... or redis://localhost:...)
        # but an explicit AWS ElastiCache host is configured, prefer host-based AWS resolution.
        is_generic_local_url = bool(
            re.match(r"^redis://(redis|localhost|127\.0\.0\.1)(:\d+)?(/.*)?$", direct_url.lower())
        )
        if not (is_generic_local_url and is_aws_host):
            url = direct_url
            # Enforce rediss:// and db 0 for AWS ElastiCache / Valkey endpoints
            if ".cache.amazonaws.com" in url.lower():
                if url.lower().startswith("redis://"):
                    url = "rediss://" + url[len("redis://"):]
                try:
                    parsed = urlparse(url)
                    if parsed.path != "/0":
                        url = parsed._replace(path="/0").geturl()
                except Exception:
                    pass
            return {
                "connection_url": url,
                "source": "DIRECT_URL",
                "masked_url": mask_redis_url(url),
            }

    secret_name = (
        os.getenv("CACHE_SECRET_NAME")
        or os.getenv("REDIS_SECRET_ARN")
        or os.getenv("REDIS_SECRET_NAME")
    )
    if secret_name:
        secret_name = secret_name.strip().strip("'\"")

    # 2. Host-based resolution (Primary AWS ElastiCache & Discrete Configuration)
    if host_candidate:
        host_clean = host_candidate
        if "://" in host_clean:
            host_clean = host_clean.split("://", 1)[1]
        host_clean = host_clean.rstrip("/")

        port = _safe_int_env("CACHE_PORT", _safe_int_env("REDIS_PORT", 6379))

        # If host string includes port (e.g. "endpoint.cache.amazonaws.com:6379"), extract cleanly
        if ":" in host_clean:
            h_part, p_part = host_clean.rsplit(":", 1)
            if p_part.isdigit():
                host_clean = h_part
                port = int(p_part)

        is_aws_cache = ".cache.amazonaws.com" in host_clean.lower()
        if is_aws_cache:
            # Valkey and ElastiCache Cluster require logical DB 0
            db = "0"
            ssl_enabled = True
        else:
            raw_db = (os.getenv("CACHE_DB") or "0").strip().strip("'\"")
            db = raw_db if raw_db else "0"
            raw_ssl = os.getenv("CACHE_TLS_ENABLED") or os.getenv("REDIS_SSL")
            ssl_env = raw_ssl.strip().strip("'\"") if raw_ssl else None
            if ssl_env is not None:
                ssl_enabled = ssl_env.lower() in ("true", "1", "yes")
            else:
                ssl_enabled = False

        # Token resolution: Secrets Manager prioritized, followed by discrete env var
        password = ""
        source = "ENV_DISCRETE"
        if secret_name:
            secret_data = resolve_secret_auth_token(secret_name)
            if secret_data:
                raw_pwd = (
                    secret_data.get("auth_token")
                    or secret_data.get("password")
                    or secret_data.get("token")
                    or ""
                )
                password = str(raw_pwd).strip()
                source = "SECRETS_MANAGER"
                if "port" in secret_data and not (os.getenv("CACHE_PORT") or os.getenv("REDIS_PORT")):
                    try:
                        port = int(secret_data["port"])
                    except (ValueError, TypeError):
                        pass

        if not password:
            raw_pwd = os.getenv("CACHE_AUTH_TOKEN") or os.getenv("REDIS_PASSWORD")
            password = raw_pwd.strip().strip("'\"") if raw_pwd else ""

        scheme = "rediss" if ssl_enabled else "redis"
        auth = f":{quote_plus(password)}@" if password else ""
        url = f"{scheme}://{auth}{host_clean}:{port}/{db}"
        return {
            "connection_url": url,
            "source": source,
            "masked_url": mask_redis_url(url),
        }

    # 3. Standalone Secrets Manager resolution (when host is embedded in secret)
    if secret_name:
        secret_data = resolve_secret_auth_token(secret_name)
        if secret_data:
            sec_host = (
                secret_data.get("host")
                or secret_data.get("engine_endpoint")
                or secret_data.get("hostname")
                or secret_data.get("endpoint")
            )
            if sec_host:
                sec_host = str(sec_host).strip().strip("'\"")
                if "://" in sec_host:
                    sec_host = sec_host.split("://", 1)[1]
                sec_host = sec_host.rstrip("/")
                sec_port = int(secret_data.get("port", 6379))
                if ":" in sec_host:
                    h_part, p_part = sec_host.rsplit(":", 1)
                    if p_part.isdigit():
                        sec_host = h_part
                        sec_port = int(p_part)
                raw_pwd = (
                    secret_data.get("auth_token")
                    or secret_data.get("password")
                    or secret_data.get("token")
                    or ""
                )
                sec_password = str(raw_pwd).strip()
                is_aws_cache = ".cache.amazonaws.com" in sec_host.lower()
                if is_aws_cache:
                    ssl = True
                    db = "0"
                else:
                    ssl = str(secret_data.get("ssl", "true")).lower() in ("true", "1", "yes")
                    raw_sec_db = str(secret_data.get("db", "0")).strip().strip("'\"")
                    db = raw_sec_db if raw_sec_db else "0"
                scheme = "rediss" if ssl else "redis"
                auth = f":{quote_plus(sec_password)}@" if sec_password else ""
                url = f"{scheme}://{auth}{sec_host}:{sec_port}/{db}"
                return {
                    "connection_url": url,
                    "source": "SECRETS_MANAGER",
                    "masked_url": mask_redis_url(url),
                }

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
        env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "local").lower()
        default_prefix = f"ip:{env}:cache:v1:"
        raw_prefix = os.getenv("CACHE_KEY_PREFIX")
        self._prefix: str = raw_prefix.strip().strip("'\"") if raw_prefix else default_prefix
        raw_enabled = os.getenv("CACHE_ENABLED", "true")
        self._enabled: bool = (raw_enabled.strip().strip("'\"").lower() in ("true", "1", "yes")) if raw_enabled else True
        self._connect_timeout: float = _safe_float_env("CACHE_CONNECT_TIMEOUT", _safe_float_env("REDIS_CONNECT_TIMEOUT", 2.0))
        self._socket_timeout: float = _safe_float_env("CACHE_SOCKET_TIMEOUT", _safe_float_env("REDIS_SOCKET_TIMEOUT", 2.0))
        self._health_check_interval: int = _safe_int_env("CACHE_HEALTH_CHECK_INTERVAL", 30)
        self._max_connections: int = _safe_int_env("CACHE_POOL_MAX", _safe_int_env("REDIS_POOL_MAX", 20))

    @classmethod
    def get_instance(cls) -> CacheService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for test environments)."""
        cls._instance = None
        clear_secret_cache()

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

    async def _cleanup(self) -> None:
        """Disconnect and reset client and pool resources."""
        self._is_available = False
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
        if self._pool is not None:
            try:
                await self._pool.disconnect()
            except Exception:
                pass
            self._pool = None

    async def initialize(self) -> None:
        """Initialize connection pool and ping Redis with fail-open safety.

        Guarantees that failed initialization does not retain a stale client/pool,
        allowing clean subsequent retry attempts.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        if not self._enabled:
            logger.info("CacheService is disabled via CACHE_ENABLED=false.")
            self._is_available = False
            return

        if self._client is not None and self._is_available:
            return

        # Always clean up any stale or partially initialized resources before attempting connection
        await self._cleanup()

        try:
            config = get_redis_connection_config()
            conn_url = config["connection_url"]

            self._pool = ConnectionPool.from_url(
                conn_url,
                max_connections=self._max_connections,
                socket_connect_timeout=self._connect_timeout,
                socket_timeout=self._socket_timeout,
                health_check_interval=self._health_check_interval,
                socket_keepalive=True,
                retry_on_timeout=True,
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
            # Clean up immediately on error so failed state does not prevent later retry
            await self._cleanup()
            masked_target = config.get("masked_url", "unknown") if "config" in locals() else "unresolved"
            logger.warning(
                "Failed to connect to Redis/Valkey (%s) during startup: %s (%s). Platform will operate in fail-open mode.",
                masked_target,
                type(exc).__name__,
                mask_redis_url(str(exc)),
            )

    async def close(self) -> None:
        """Gracefully close Redis client and connection pool."""
        await self._cleanup()
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
            logger.warning("Redis GET failed for key '%s': %s (failing open)", formatted_key, mask_redis_url(str(exc)))
            return None
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Unexpected error during Redis GET '%s': %s", formatted_key, mask_redis_url(str(exc)))
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
            logger.warning("Redis SET failed for key '%s': %s (skipping cache write)", formatted_key, mask_redis_url(str(exc)))
            return False
        except Exception as exc:
            self._metrics.record_error()
            logger.warning("Serialization/Redis error during SET '%s': %s", formatted_key, mask_redis_url(str(exc)))
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
            logger.warning("Redis UNLINK failed for key '%s': %s", formatted_key, mask_redis_url(str(exc)))
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
            logger.warning("Redis SCAN/UNLINK failed for pattern '%s': %s", formatted_pattern, mask_redis_url(str(exc)))
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

                # Fail-open / bypass check when cache is not running or disabled
                if not cache.is_available:
                    if req is not None:
                        req.state.cache_outcome = "BYPASS"
                    return await func(*args, **kwargs)

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

                # Fail-open / bypass check when cache is not running or disabled
                if not cache.is_available:
                    if req is not None:
                        req.state.cache_outcome = "BYPASS"
                    return func(*args, **kwargs)

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
