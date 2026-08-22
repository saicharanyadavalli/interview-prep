"""Centralised rate-limiter configuration.

Strategy Design
---------------
slowapi wraps limits.storage backends. We use an in-process (memory)
storage suitable for single-process deployments (Docker, single Uvicorn
worker). For multi-worker / distributed setups, swap RATE_LIMIT_STORAGE_URI
to a Redis URI (redis://…) and the same code works without any other changes.

Key functions
~~~~~~~~~~~~~
- get_rate_limit_key  : composite key = user-id (if authenticated) | IP
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
# Storage backend
# ---------------------------------------------------------------------------
# Default: in-memory (single-process).  Set RATE_LIMIT_STORAGE_URI=redis://…
# in production for multi-worker / distributed rate-limiting.
_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


# ---------------------------------------------------------------------------
# Composite key function (IP + user-id)
# ---------------------------------------------------------------------------

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

    return f"ip:{get_remote_address(request)}"


# ---------------------------------------------------------------------------
# Limiter instance
# ---------------------------------------------------------------------------

limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=["5000/minute"],  # generous limit: 5000 requests per minute
    headers_enabled=True,           # emit X-RateLimit-* headers
    storage_uri=_STORAGE_URI,
)
