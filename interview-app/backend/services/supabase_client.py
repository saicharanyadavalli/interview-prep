"""Supabase client wrapper. Reads credentials from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client using the service-role key.

    Used strictly for Supabase Auth administration and user token verification.
    Application data is authoritatively stored in Amazon RDS PostgreSQL.
    """
    url = os.getenv("SUPABASE_URL", "").strip().strip('"').strip("'")
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip().strip('"').strip("'")
    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment. "
            "Check your .env file."
        )
    return create_client(url, key)


def verify_supabase_token(access_token: str) -> dict | None:
    """Verify a Supabase JWT and return the user dict, or None on failure.

    Uses the Supabase auth.get_user() method which validates the token
    against the Supabase Auth server.
    """
    if os.getenv("DISABLE_AUTH") == "true":
        import logging
        logging.getLogger(__name__).warning("DISABLE_AUTH is enabled — all requests bypass authentication. DO NOT use in production.")
        return {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "testuser@example.com",
            "name": "Test User",
            "avatar_url": "",
        }

    try:
        client = get_supabase_client()
        response = client.auth.get_user(access_token)
        if response and response.user:
            metadata = response.user.user_metadata or {}
            return {
                "id": response.user.id,
                "email": response.user.email or "",
                "username": metadata.get("username", "") or "",
                "name": metadata.get("full_name", "") or metadata.get("name", "") or "",
                "avatar_url": metadata.get("avatar_url", "") or "",
            }
    except Exception:
        pass
    return None


def authenticate_user_credentials(email: str, password: str) -> dict | None:
    """Authenticate user with email and password via Supabase Auth without service-role bypass.

    Returns dict with access_token, refresh_token, and user info on success,
    or None if credentials are invalid or auth fails.
    """
    if os.getenv("DISABLE_AUTH") == "true":
        env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
        if env not in ("production", "prod"):
            return {
                "access_token": "mock-test-access-token-12345",
                "refresh_token": "mock-test-refresh-token-12345",
                "user": {
                    "id": "12345678-1234-1234-1234-123456789012",
                    "email": email,
                    "username": email.split("@")[0],
                    "name": "Test User",
                    "avatar_url": "",
                },
            }

    try:
        url = os.getenv("SUPABASE_URL", "").strip().strip('"').strip("'")
        anon_key = (
            os.getenv("SUPABASE_ANON_KEY")
            or os.getenv("NEXT_PUBLIC_SUPABASE_ANON_KEY")
            or os.getenv("SUPABASE_SERVICE_KEY", "")
        ).strip().strip('"').strip("'")

        if not url or not anon_key:
            return None

        client = create_client(url, anon_key)
        response = client.auth.sign_in_with_password({"email": email, "password": password})
        if response and response.session and response.user:
            metadata = response.user.user_metadata or {}
            return {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user": {
                    "id": response.user.id,
                    "email": response.user.email or email,
                    "username": metadata.get("username", "") or "",
                    "name": metadata.get("full_name", "") or metadata.get("name", "") or "",
                    "avatar_url": metadata.get("avatar_url", "") or "",
                },
            }
    except Exception:
        pass
    return None
