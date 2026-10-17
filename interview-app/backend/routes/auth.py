"""Auth routes — validate Supabase JWT and synchronize user profiles in RDS.

Supabase Auth continues handling email/password sign-up, sign-in, session tokens,
and JWT issuance. The backend validates the Supabase token and synchronizes the
authoritative user record in Amazon RDS PostgreSQL user_profiles.
"""

from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from limiter import limiter

from models.schemas import SessionRequest, UserResponse, ResolveUsernameRequest, ResolveUsernameResponse
from services.supabase_client import verify_supabase_token
from services import rds_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _ensure_user_in_rds(user: dict) -> None:
    """Ensure authenticated user exists in RDS user_profiles table."""
    try:
        user_id = str(user.get("id", "")).strip()
        if not user_id:
            return

        existing = rds_client.query(
            "SELECT id FROM user_profiles WHERE id = %s LIMIT 1",
            (user_id,),
            fetch="one",
        )
        if existing:
            return

        email = str(user.get("email", "")).strip()
        base_username = (
            str(user.get("username", "")).strip()
            or (email.split("@")[0] if email else f"user_{user_id[:8]}")
        ).lower()

        # Check if the proposed username is already taken by another user
        username = base_username
        taken = rds_client.query(
            "SELECT id FROM user_profiles WHERE LOWER(username) = %s LIMIT 1",
            (username,),
            fetch="one",
        )
        if taken:
            username = f"{base_username}_{user_id[:6]}".lower()

        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, username, name, avatar_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email;
            """,
            (
                user_id,
                email,
                username,
                user.get("name", "") or "",
                user.get("avatar_url", "") or "",
            ),
        )
    except Exception as exc:
        logger.warning("Could not auto-sync user %s into RDS: %s", user.get("id"), exc)


def get_current_user(authorization: str | None = Header(None)) -> dict:
    """Extract and verify the Bearer token from the Authorization header.

    Validates against Supabase Auth, ensures the user profile exists in RDS,
    and returns the authenticated user dictionary. Raises 401 on failure.
    """
    if os.getenv("DISABLE_AUTH") == "true":
        logger.warning("DISABLE_AUTH is enabled — all requests bypass authentication. DO NOT use in production.")
        mock_user = {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "testuser@example.com",
            "username": "testuser",
            "name": "Test User",
            "avatar_url": "",
        }
        _ensure_user_in_rds(mock_user)
        return mock_user

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    user = verify_supabase_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    _ensure_user_in_rds(user)
    return user


def get_optional_current_user(authorization: str | None = Header(None)) -> dict | None:
    """Return current user when Authorization header is valid, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    user = verify_supabase_token(token)
    if user:
        _ensure_user_in_rds(user)
    return user


@router.post("/session", response_model=UserResponse)
@limiter.limit("5000/minute")
def create_session(request: Request, response: Response, payload: SessionRequest):
    """Validate Supabase token and synchronize user into RDS user_profiles table."""
    user = verify_supabase_token(payload.access_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    email = user.get("email", "")
    username = user.get("username") or (email.split("@")[0] if email else f"user_{user['id'][:8]}").lower()

    try:
        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, username, name, avatar_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email,
                username = COALESCE(user_profiles.username, EXCLUDED.username),
                name = COALESCE(NULLIF(user_profiles.name, ''), EXCLUDED.name),
                avatar_url = COALESCE(NULLIF(user_profiles.avatar_url, ''), EXCLUDED.avatar_url),
                updated_at = now();
            """,
            (
                user["id"],
                email,
                username,
                user.get("name", "") or "",
                user.get("avatar_url", "") or "",
            ),
        )

        # Retrieve authoritative profile from RDS
        db_user = rds_client.query(
            "SELECT id, email, username, name, avatar_url FROM user_profiles WHERE id = %s LIMIT 1;",
            (user["id"],),
            fetch="one",
        )
        if db_user:
            return UserResponse(
                id=str(db_user["id"]),
                email=db_user["email"],
                username=db_user.get("username"),
                name=db_user.get("name"),
                avatar_url=db_user.get("avatar_url"),
            )
    except Exception as exc:
        logger.warning("Session RDS user sync error for user %s: %s", user.get("id"), exc)

    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user.get("username"),
        name=user.get("name"),
        avatar_url=user.get("avatar_url"),
    )


@router.post("/resolve-username", response_model=ResolveUsernameResponse)
@limiter.limit("60/minute")
def resolve_username(request: Request, response: Response, payload: ResolveUsernameRequest):
    """Look up the email associated with a username directly from RDS user_profiles."""
    try:
        clean = payload.username.strip().lower()
        row = rds_client.query(
            "SELECT email FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
            (clean,),
            fetch="one",
        )
        if row and row.get("email"):
            return ResolveUsernameResponse(email=row["email"], exists=True)
    except Exception as exc:
        logger.warning("Error resolving username %s in RDS: %s", payload.username, exc)
    return ResolveUsernameResponse(email=None, exists=False)


@router.get("/check-username")
@limiter.limit("120/minute")
def check_username_availability(request: Request, response: Response, username: str = Query(..., min_length=3, max_length=50)):
    """Check if a username is available in RDS user_profiles (for live client-side validation)."""
    try:
        clean = username.strip().lower()
        row = rds_client.query(
            "SELECT id FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
            (clean,),
            fetch="one",
        )
        return {"available": row is None, "username": clean}
    except Exception as exc:
        logger.warning("Error checking username availability for %s: %s", username, exc)
        return {"available": False, "username": username, "error": "Database check failed"}
