"""Centralised rate-limiter configuration.

Strategy Design
---------------
SlowAPI wraps limits.storage backends.
In local development / single worker, in-process memory:// or local Redis may be used.
In production with multiple Uvicorn workers, RATE_LIMIT_STORAGE_URI points to
Amazon ElastiCache for Valkey / Redis (e.g. rediss://:... or redis://:...) to provide
atomic, shared sliding-window counters across all worker processes.

Key functions
~~~~~~~~~~~~~
- get_client_ip       : Extract client IP safely handling Nginx X-Real-IP and X-Forwarded-For.
- get_rate_limit_key  : Composite key = user-id (if authenticated) | IP
                        This binds anonymous traffic by IP and authenticated
                        traffic by user UUID, so a user cannot evade a limit
                        simply by switching IPs.
- limiter             : Limiter instance used by @limiter.limit() decorators.
"""

from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


# ---------------------------------------------------------------------------
# Storage backend resolution
# ---------------------------------------------------------------------------
def resolve_rate_limit_storage_uri() -> str:
    """Resolve storage URI for SlowAPI limits engine.

    Priority:
    1. RATE_LIMIT_STORAGE_URI (explicit configuration, e.g. standalone redis db 1)
    2. CACHE_URL / REDIS_URL (shared cache endpoint, retains DB 0 for Valkey/ElastiCache cluster compatibility)
    3. CACHE_HOST / REDIS_HOST
    4. memory:// fallback
    """
    explicit = os.getenv("RATE_LIMIT_STORAGE_URI")
    if explicit and explicit.strip():
        return explicit.strip()

    redis_url = os.getenv("CACHE_URL") or os.getenv("REDIS_URL")
    if redis_url and redis_url.strip():
        return redis_url.strip()

    host = os.getenv("CACHE_HOST") or os.getenv("REDIS_HOST")
    if host and host.strip():
        port = int(os.getenv("CACHE_PORT", os.getenv("REDIS_PORT", "6379")))
        password = (os.getenv("CACHE_AUTH_TOKEN") or os.getenv("REDIS_PASSWORD") or "").strip()
        ssl = (os.getenv("CACHE_TLS_ENABLED") or os.getenv("REDIS_SSL", "false")).lower() in ("true", "1", "yes")
        scheme = "rediss" if ssl else "redis"
        auth = f":{password}@" if password else ""
        return f"{scheme}://{auth}{host.strip()}:{port}/0"

    return "memory://"


_STORAGE_URI = resolve_rate_limit_storage_uri()
_DEFAULT_LIMIT = os.getenv("RATE_LIMIT_DEFAULT", "120/minute")


# ---------------------------------------------------------------------------
# Composite key function (IP + user-id)
# ---------------------------------------------------------------------------

def get_client_ip(request: Request) -> str:
    """Extract client IP address for rate limiting, safely handling reverse proxies.

    Priority:
    1. X-Real-IP: Set authoritatively by Nginx ($remote_addr) which strips/overwrites
       untrusted client-supplied values.
    2. X-Forwarded-For: Leftmost client IP from forwarded proxy chain if present.
    3. request.client.host (via slowapi get_remote_address) as baseline fallback.
    """
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        clean_ip = x_real_ip.strip()
        if clean_ip:
            return clean_ip

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
        if ips:
            return ips[0]

    return get_remote_address(request)


def get_rate_limit_key(request: Request) -> str:
    """Return a rate-limit key that is user-scoped when authenticated,
    otherwise IP-scoped.

    Priority:
    1. Resolved user_id injected by auth middleware (if present on request state)
    2. Remote IP address (fallback for anonymous requests)
    """
    user_id: str | None = getattr(request.state, "rate_limit_user_id", None)
    if user_id:
        return f"user:{user_id}"

    return f"ip:{get_client_ip(request)}"


# ---------------------------------------------------------------------------
# Limiter instance
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[_DEFAULT_LIMIT],  # Configurable default limit per minute
    headers_enabled=False,            # Disabled on 200 responses to prevent Starlette Response requirement on sync routes
    storage_uri=_STORAGE_URI,
)
