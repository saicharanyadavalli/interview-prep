"""Centralised rate-limiter configuration.

Strategy Design
---------------
SlowAPI wraps limits.storage backends.
In local development / single worker, in-process memory:// or local Redis may be used.
In production with multiple Uvicorn workers, RATE_LIMIT_STORAGE_URI points to
Amazon ElastiCache for Valkey / Redis (e.g. rediss://:... or redis://:...) to provide
atomic, shared sliding-window counters across all worker processes.

Key design principles:
- Safe module import: No AWS network or Secrets Manager calls occur during import.
- Resilient storage proxy: SlowAPI is initialized with a resilient storage backend
  that begins in local memory and connects to Redis during application startup.
- Fail-open resilience: Redis connection or runtime errors fall back to in-memory counters
  without raising 500 errors.
- Observability: Telemetry accurately distinguishes configured target, operational mode,
  and in-memory fallback state.
- Recovery: Supports connection retries after transient startup or runtime outages.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from typing import Any, Optional

from fastapi import Request
import limits.storage
from limits.storage import MovingWindowSupport, SlidingWindowCounterSupport, Storage
from slowapi import Limiter
from slowapi.util import get_remote_address

from services.cache_service import mask_redis_url

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")
_ENV = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "local").lower()
_KEY_PREFIX = os.getenv("RATE_LIMIT_KEY_PREFIX") or f"ip:{_ENV}:rl:"
_STRATEGY = os.getenv("RATE_LIMIT_STRATEGY") or os.getenv("STRATEGY") or "moving-window"


def _sanitize_error_message(msg: str) -> str:
    """Mask credentials in error messages to prevent leakage in telemetry and logs."""
    if not msg:
        return ""
    # Mask any user:password@ or :password@ in connection strings within error messages
    return re.sub(r"([a-zA-Z0-9]+://)([^:]*):([^@]+)@", r"\g<1>\g<2>:****@", msg)


# ---------------------------------------------------------------------------
# Resilient Rate Limiter Storage Implementation
# ---------------------------------------------------------------------------

class ResilientLimiterStorage(
    Storage,
    MovingWindowSupport,
    SlidingWindowCounterSupport,
):
    """Resilient, observable storage proxy for SlowAPI rate limiting.

    Supports atomic distributed counters in Amazon ElastiCache (Valkey / Redis)
    while providing zero network calls at import time, seamless fail-open fallback
    to local memory on startup or runtime Redis errors, and observable automatic
    recovery when the connection is restored.
    """

    STORAGE_SCHEME = ["resilient"]

    def __init__(self, uri: str | None = None, **options: float | str | bool):
        super().__init__(uri, **options)
        self._fallback_storage = limits.storage.MemoryStorage()
        self._primary_storage: Optional[Storage] = None
        self._configured_target: str = "memory://"
        self._configured_backend: str = "memory"
        self._operational_mode: str = "in_memory"
        self._status: str = "healthy"
        self._target_uri: Optional[str] = None
        self._fallback_active: bool = False
        self._failover_count: int = 0
        self._recovered_count: int = 0
        self._last_error: Optional[str] = None
        self._lock = threading.Lock()

        # If an explicit non-empty Redis URI is provided, configure it lazily without import-time network calls
        if uri is not None:
            explicit = uri.strip()
        else:
            explicit = os.getenv("RATE_LIMIT_STORAGE_URI", "").strip()
        if explicit and not explicit.startswith("memory://") and not explicit.startswith("resilient://"):
            self.configure(explicit, test_connection=False)

    @property
    def base_exceptions(self) -> type[Exception] | tuple[type[Exception], ...]:
        return (Exception,)

    @property
    def configured_target(self) -> str:
        return self._configured_target

    @property
    def configured_backend(self) -> str:
        return self._configured_backend

    @property
    def operational_mode(self) -> str:
        if self._operational_mode == "uninitialized":
            return "uninitialized"
        if self._configured_backend == "memory":
            return "in_memory"
        if self._fallback_active or self._primary_storage is None:
            return "in_memory_fallback"
        return "distributed"

    @property
    def is_distributed(self) -> bool:
        return (
            self._configured_backend == "redis"
            and self._primary_storage is not None
            and not self._fallback_active
        )

    @property
    def status(self) -> str:
        if self._operational_mode == "uninitialized":
            return "uninitialized"
        if self._fallback_active or (self._configured_backend == "redis" and self._primary_storage is None):
            return "degraded"
        return "healthy"

    @property
    def failover_count(self) -> int:
        return self._failover_count

    @property
    def recovered_count(self) -> int:
        return self._recovered_count

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def _failover(self, op: str, exc: Exception) -> None:
        clean_exc = _sanitize_error_message(str(exc))
        with self._lock:
            if not self._fallback_active:
                self._fallback_active = True
                self._failover_count += 1
                self._operational_mode = "in_memory_fallback"
                self._status = "degraded"
                self._last_error = f"Runtime Redis {op} error: {clean_exc}"
        logger.warning(
            "Rate limiter Redis failure on %s (%s); falling back to in-memory counters.",
            op,
            clean_exc,
        )

    def configure(self, uri: str, test_connection: bool = True) -> bool:
        """Configure storage backend with a resolved URI."""
        with self._lock:
            uri_clean = (uri or "").strip()
            if not uri_clean or uri_clean.startswith("memory://"):
                self._configured_target = "memory://"
                self._configured_backend = "memory"
                self._operational_mode = "in_memory"
                self._status = "healthy"
                self._primary_storage = self._fallback_storage
                self._fallback_active = False
                self._target_uri = "memory://"
                logger.info("Rate limiter storage configured for in-memory operation.")
                return True

            self._configured_target = mask_redis_url(uri_clean)
            self._configured_backend = "redis"
            self._target_uri = uri_clean

            try:
                storage = limits.storage.storage_from_string(uri_clean)
                if test_connection:
                    healthy = storage.check()
                    if healthy:
                        was_fallback = self._fallback_active
                        old_primary = self._primary_storage
                        self._primary_storage = storage
                        self._operational_mode = "distributed"
                        self._status = "healthy"
                        self._fallback_active = False
                        self._last_error = None
                        if was_fallback:
                            self._recovered_count += 1
                        if old_primary is not None and old_primary is not self._fallback_storage:
                            self._cleanup_backend(old_primary)
                        logger.info(
                            "Rate limiter successfully connected to distributed cache (%s)",
                            self._configured_target,
                        )
                        return True
                    else:
                        self._primary_storage = None
                        self._operational_mode = "in_memory_fallback"
                        self._status = "degraded"
                        self._fallback_active = True
                        self._last_error = "Connection check failed on initialization: ping returned False"
                        logger.warning(
                            "Rate limiter could not verify connection to %s. Operating in in-memory fallback.",
                            self._configured_target,
                        )
                        return False
                else:
                    was_fallback = self._fallback_active
                    old_primary = self._primary_storage
                    self._primary_storage = storage
                    self._operational_mode = "distributed"
                    self._status = "healthy"
                    self._fallback_active = False
                    self._last_error = None
                    if was_fallback:
                        self._recovered_count += 1
                    if old_primary is not None and old_primary is not self._fallback_storage:
                        self._cleanup_backend(old_primary)
                    return True
            except Exception as exc:
                clean_exc = _sanitize_error_message(str(exc))
                self._primary_storage = None
                self._operational_mode = "in_memory_fallback"
                self._status = "degraded"
                self._fallback_active = True
                self._last_error = f"Storage initialization error: {clean_exc}"
                logger.warning(
                    "Rate limiter failed to initialize Redis storage (%s): %s. Operating in in-memory fallback.",
                    self._configured_target,
                    clean_exc,
                )
                return False

    def retry_connection(self) -> bool:
        """Attempt to re-establish primary storage connection using the configured URI."""
        if self._configured_backend == "redis" and self._target_uri:
            return self.configure(self._target_uri, test_connection=True)
        return False

    def incr(self, key: str, expiry: int, amount: int = 1) -> int:
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.incr(key, expiry, amount)
            except Exception as exc:
                self._failover("incr", exc)
                return self._fallback_storage.incr(key, expiry, amount)

        return self._fallback_storage.incr(key, expiry, amount)

    def get(self, key: str) -> int:
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.get(key)
            except Exception as exc:
                self._failover("get", exc)
                return self._fallback_storage.get(key)

        return self._fallback_storage.get(key)

    def get_expiry(self, key: str) -> float:
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.get_expiry(key)
            except Exception as exc:
                self._failover("get_expiry", exc)
                return self._fallback_storage.get_expiry(key)

        return self._fallback_storage.get_expiry(key)

    @staticmethod
    def _cleanup_backend(backend: Optional[Storage]) -> None:
        """Safely close raw storage and disconnect connection pools to prevent socket leaks."""
        if backend is None:
            return
        raw_storage = getattr(backend, "storage", None)
        if raw_storage and hasattr(raw_storage, "close"):
            try:
                raw_storage.close()
            except Exception:
                pass
        elif hasattr(backend, "close"):
            try:
                backend.close()
            except Exception:
                pass
        pool = getattr(raw_storage, "connection_pool", None) or getattr(backend, "connection_pool", None)
        if pool and hasattr(pool, "disconnect"):
            try:
                pool.disconnect()
            except Exception:
                pass

    def check(self) -> bool:
        """Check health of rate limiter storage, recovering from fallback if Redis is restored."""
        if self._configured_backend == "redis":
            if self._primary_storage is not None:
                try:
                    is_healthy = self._primary_storage.check()
                    if is_healthy:
                        if self._fallback_active:
                            with self._lock:
                                self._fallback_active = False
                                self._recovered_count += 1
                                self._operational_mode = "distributed"
                                self._status = "healthy"
                                self._last_error = None
                            logger.info("Rate limiter Redis storage recovered; resuming distributed mode.")
                        return True
                    else:
                        with self._lock:
                            if not self._fallback_active:
                                self._fallback_active = True
                                self._failover_count += 1
                                self._operational_mode = "in_memory_fallback"
                                self._status = "degraded"
                            self._last_error = "Health check failed: Redis ping returned False"
                        return False
                except Exception as exc:
                    clean_exc = _sanitize_error_message(str(exc))
                    with self._lock:
                        if not self._fallback_active:
                            self._fallback_active = True
                            self._failover_count += 1
                            self._operational_mode = "in_memory_fallback"
                            self._status = "degraded"
                        self._last_error = f"Check failed: {clean_exc}"
                    return False
            elif self._target_uri:
                return self.retry_connection()
            return False

        return True

    def reset(self) -> int | None:
        if self._primary_storage is not None:
            try:
                self._primary_storage.reset()
            except Exception:
                pass
        return self._fallback_storage.reset()

    def clear(self, key: str) -> None:
        if self._primary_storage is not None:
            try:
                self._primary_storage.clear(key)
            except Exception:
                pass
        self._fallback_storage.clear(key)

    # ── Sliding Window Counter Support (limits.storage.SlidingWindowCounterSupport) ──

    def acquire_sliding_window_entry(
        self, key: str, limit: int, expiry: int, amount: int = 1
    ) -> bool:
        """Acquire an entry using sliding window counter strategy."""
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.acquire_sliding_window_entry(key, limit, expiry, amount=amount)
            except Exception as exc:
                self._failover("acquire_sliding_window_entry", exc)
                return self._fallback_storage.acquire_sliding_window_entry(key, limit, expiry, amount=amount)

        return self._fallback_storage.acquire_sliding_window_entry(key, limit, expiry, amount=amount)

    def get_sliding_window(
        self, key: str, expiry: int
    ) -> tuple[int, float, int, float]:
        """Return sliding window counter stats (previous count/ttl, current count/ttl)."""
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.get_sliding_window(key, expiry)
            except Exception as exc:
                self._failover("get_sliding_window", exc)
                return self._fallback_storage.get_sliding_window(key, expiry)

        return self._fallback_storage.get_sliding_window(key, expiry)

    def clear_sliding_window(self, key: str, expiry: int) -> None:
        """Clear both current and previous sliding window keys."""
        if self._primary_storage is not None:
            try:
                self._primary_storage.clear_sliding_window(key, expiry)
            except Exception:
                pass
        self._fallback_storage.clear_sliding_window(key, expiry)

    # ── Moving Window Support (limits.storage.MovingWindowSupport) ──

    def acquire_entry(
        self, key: str, limit: int, expiry: int, amount: int = 1
    ) -> bool:
        """Acquire entry in moving window."""
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.acquire_entry(key, limit, expiry, amount=amount)
            except Exception as exc:
                self._failover("acquire_entry", exc)
                return self._fallback_storage.acquire_entry(key, limit, expiry, amount=amount)

        return self._fallback_storage.acquire_entry(key, limit, expiry, amount=amount)

    def get_moving_window(
        self, key: str, limit: int, expiry: int
    ) -> tuple[float, int]:
        """Return starting point and number of entries in moving window."""
        primary = self._primary_storage
        if primary is not None and not self._fallback_active:
            try:
                return primary.get_moving_window(key, limit, expiry)
            except Exception as exc:
                self._failover("get_moving_window", exc)
                return self._fallback_storage.get_moving_window(key, limit, expiry)

        return self._fallback_storage.get_moving_window(key, limit, expiry)

    def close(self) -> None:
        if self._primary_storage is not None:
            self._cleanup_backend(self._primary_storage)


# ---------------------------------------------------------------------------
# Storage backend resolution & lifecycle helpers
# ---------------------------------------------------------------------------

def resolve_rate_limit_storage_uri() -> str:
    """Resolve storage URI for SlowAPI limits engine.

    Priority:
    1. RATE_LIMIT_STORAGE_URI: Explicit operator override (e.g. 'memory://' or 'redis://...')
    2. Shared Cache Resolution: Inherits the exact same Redis/Valkey endpoint, TLS,
       and Secrets Manager authentication token resolved by get_redis_connection_config().
    3. memory:// fallback if no Redis endpoint is explicitly configured or on resolution error.
    """
    explicit = os.getenv("RATE_LIMIT_STORAGE_URI")
    if explicit and explicit.strip():
        url = explicit.strip()
        url = re.sub(r":(\d+):\1", r":\1", url)
        # Enforce rediss:// and logical db 0 for AWS ElastiCache / Valkey endpoints
        if ".cache.amazonaws.com" in url.lower():
            if url.lower().startswith("redis://"):
                url = "rediss://" + url[len("redis://"):]
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                if parsed.path not in ("", "/0"):
                    url = parsed._replace(path="/0").geturl()
            except Exception:
                pass
        return url

    try:
        from services.cache_service import get_redis_connection_config

        config = get_redis_connection_config()
        if config.get("source") != "DEFAULT_FALLBACK":
            url = config["connection_url"]
            return re.sub(r":(\d+):\1", r":\1", url)
    except Exception as exc:
        logger.warning(
            "Could not resolve shared Redis config for rate limiter (%s). Defaulting to memory://",
            exc,
        )

    return "memory://"


def get_resilient_storage() -> Optional[ResilientLimiterStorage]:
    """Retrieve the ResilientLimiterStorage instance from limiter._storage if available."""
    storage = getattr(limiter, "_storage", None)
    if isinstance(storage, ResilientLimiterStorage):
        return storage
    return None


def check_rate_limiter_health() -> bool:
    """Perform health check on rate limiter storage and recover from fallback if possible."""
    storage = get_resilient_storage()
    if storage is not None:
        healthy = storage.check()
        if healthy and getattr(limiter, "_storage_dead", False):
            limiter._storage_dead = False
            if hasattr(limiter, "_Limiter__check_backend_count"):
                setattr(limiter, "_Limiter__check_backend_count", 0)
        return healthy
    return True


def init_rate_limiter(uri: Optional[str] = None, test_connection: bool = True) -> dict[str, Any]:
    """Initialize or update rate limiter storage with Redis/Valkey or memory backend.

    Called during application lifespan startup when environment variables, network connectivity,
    and AWS IAM / Secrets Manager services are available.
    """
    global _KEY_PREFIX
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "local").lower()
    _KEY_PREFIX = os.getenv("RATE_LIMIT_KEY_PREFIX") or f"ip:{env}:rl:"
    if hasattr(limiter, "_key_prefix"):
        limiter._key_prefix = _KEY_PREFIX

    target_uri = uri if uri is not None else resolve_rate_limit_storage_uri()
    storage = get_resilient_storage()
    if storage is not None:
        storage.configure(target_uri, test_connection=test_connection)
    return get_rate_limiter_storage_info()


def close_rate_limiter() -> None:
    """Cleanly close connection pools associated with the rate limiter."""
    storage = get_resilient_storage()
    if storage is not None:
        storage.close()


def get_rate_limiter_storage_info() -> dict[str, Any]:
    """Return observable telemetry regarding effective rate-limiting storage target and mode."""
    storage = getattr(limiter, "_storage", None)
    strategy = getattr(limiter, "_strategy", _STRATEGY) or _STRATEGY
    effective_prefix = getattr(limiter, "_key_prefix", _KEY_PREFIX) or _KEY_PREFIX

    if isinstance(storage, ResilientLimiterStorage):
        is_dist = storage.is_distributed
        op_mode = storage.operational_mode
        return {
            "storage_target": storage.configured_target,
            "configured_backend": storage.configured_backend,
            "operational_mode": op_mode,
            "mode": "distributed" if is_dist else "in_memory",
            "engine": "redis" if is_dist else "memory",
            "strategy": strategy,
            "is_distributed": is_dist,
            "status": storage.status,
            "key_prefix": effective_prefix,
            "failover_count": storage.failover_count,
            "recovered_count": storage.recovered_count,
            "last_error": storage.last_error,
        }

    if isinstance(storage, limits.storage.MemoryStorage):
        return {
            "storage_target": "memory://",
            "configured_backend": "memory",
            "operational_mode": "in_memory",
            "mode": "in_memory",
            "engine": "memory",
            "strategy": strategy,
            "is_distributed": False,
            "status": "healthy",
            "key_prefix": effective_prefix,
            "failover_count": 0,
            "recovered_count": 0,
            "last_error": None,
        }

    return {
        "storage_target": "unknown",
        "configured_backend": "unknown",
        "operational_mode": "unknown",
        "mode": "unknown",
        "engine": "unknown",
        "strategy": strategy,
        "is_distributed": False,
        "status": "uninitialized",
        "key_prefix": effective_prefix,
        "failover_count": 0,
        "recovered_count": 0,
        "last_error": None,
    }


# ---------------------------------------------------------------------------
# Composite key function (IP + user-id)
# ---------------------------------------------------------------------------

def get_client_ip(request: Optional[Request] = None) -> str:
    """Extract client IP address for rate limiting, safely handling reverse proxies.

    Priority:
    1. X-Real-IP: Set authoritatively by Nginx ($remote_addr) which strips/overwrites
       untrusted client-supplied values.
    2. X-Forwarded-For: Leftmost client IP from forwarded proxy chain if present.
    3. request.client.host (via slowapi get_remote_address) as baseline fallback.
    """
    if request is None:
        return "127.0.0.1"

    headers = getattr(request, "headers", None) or {}
    x_real_ip = headers.get("x-real-ip") if hasattr(headers, "get") else None
    if x_real_ip:
        clean_ip = x_real_ip.strip()
        if clean_ip:
            return clean_ip

    x_forwarded_for = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if x_forwarded_for:
        ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
        if ips:
            return ips[0]

    return get_remote_address(request)


def get_rate_limit_key(request: Optional[Request] = None) -> str:
    """Return a rate-limit key that is user-scoped when authenticated,
    otherwise IP-scoped.

    Priority:
    1. Resolved user_id injected by auth middleware (if present on request state)
    2. Remote IP address (fallback for anonymous requests)
    """
    if request is None:
        return "ip:127.0.0.1"

    state = getattr(request, "state", None)
    user_id: Any = getattr(state, "rate_limit_user_id", None) if state is not None else None
    if user_id is not None:
        user_id_str = str(user_id).strip()
        if user_id_str:
            return f"user:{user_id_str}"

    return f"ip:{get_client_ip(request)}"


# ---------------------------------------------------------------------------
# Limiter instance
# ---------------------------------------------------------------------------

# Always use 'resilient://' so SlowAPI uses the resilient, observable storage wrapper.
_INIT_STORAGE_URI = "resilient://"

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[_DEFAULT_LIMIT],  # Configurable default limit per minute
    headers_enabled=False,            # Disabled on 200 responses to prevent Starlette Response requirement on sync routes
    strategy=_STRATEGY,               # Moving-window sliding counter across shared Redis/Valkey cluster
    storage_uri=_INIT_STORAGE_URI,
    key_prefix=_KEY_PREFIX,
    in_memory_fallback_enabled=True,  # Automatically falls back to in-memory counters if storage check fails
    swallow_errors=True,              # Fails open on storage network exceptions rather than failing requests with 500
)
