"""Rate-limit auth middleware.

Injects `request.state.rate_limit_user_id` so the limiter key function
can use the real user UUID/token identifier instead of relying solely on IP
when the request carries a Bearer token.
Uses Amazon Cognito authentication for token verification.
"""

from __future__ import annotations

import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from services.cognito_auth import verify_cognito_token

# Backward-compatibility alias for legacy tests patching verify_supabase_token
try:
    from services.supabase_client import verify_supabase_token
except ImportError:
    verify_supabase_token = verify_cognito_token


class RateLimitAuthMiddleware(BaseHTTPMiddleware):
    """Extract user_id from Bearer token using Amazon Cognito and store it on request.state."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        user_id: str | None = None

        auth_header: str = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            if token:
                if os.getenv("DISABLE_AUTH") == "true":
                    # In test/dev mode with auth disabled, use token string directly as key identifier
                    user_id = token
                else:
                    try:
                        claims = verify_cognito_token(token)
                        if claims:
                            user_id = str(claims.get("sub") or claims.get("id") or "")
                    except Exception:  # noqa: BLE001
                        pass

                    # Fallback for legacy tests patching verify_supabase_token
                    if not user_id and verify_supabase_token:
                        try:
                            legacy_user = verify_supabase_token(token)
                            if legacy_user and legacy_user.get("id"):
                                user_id = str(legacy_user["id"])
                        except Exception:  # noqa: BLE001
                            pass  # fallback to IP

        request.state.rate_limit_user_id = user_id
        return await call_next(request)
