"""Supabase client wrapper. Reads credentials from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached Supabase client using the service-role key.

    The service-role key bypasses Row Level Security so the backend can
    read/write data on behalf of any authenticated user.  The anon key is
    used on the frontend instead.
    """
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
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
    try:
        client = get_supabase_client()
        response = client.auth.get_user(access_token)
        if response and response.user:
            return {
                "id": response.user.id,
                "email": response.user.email or "",
                "name": (
                    response.user.user_metadata.get("full_name", "")
                    if response.user.user_metadata
                    else ""
                ),
                "avatar_url": (
                    response.user.user_metadata.get("avatar_url", "")
                    if response.user.user_metadata
                    else ""
                ),
            }
    except Exception:
        pass
    return None
