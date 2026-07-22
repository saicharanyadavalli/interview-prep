"""Auth routes — validate Supabase JWT and manage user profiles."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from models.schemas import SessionRequest, UserResponse, ResolveUsernameRequest, ResolveUsernameResponse
from services.supabase_client import get_supabase_client, verify_supabase_token

router = APIRouter(prefix="/auth", tags=["auth"])


def get_current_user(authorization: str | None = Header(None)) -> dict:
    """Extract and verify the Bearer token from the Authorization header.

    Returns the user dict on success, raises 401 on failure.
    This is used as a dependency by other routes.
    """
    import os
    if os.getenv("DISABLE_AUTH") == "true":
        return {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "testuser@example.com",
            "username": "testuser",
            "name": "Test User",
            "avatar_url": "",
        }

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    user = verify_supabase_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user


def get_optional_current_user(authorization: str | None = Header(None)) -> dict | None:
    """Return current user when Authorization header is valid, else None.

    Unlike get_current_user, this never raises on missing/invalid tokens.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    return verify_supabase_token(token)


@router.post("/session", response_model=UserResponse)
def create_session(payload: SessionRequest):
    """Validate the access token and upsert the user in our users & user_profiles tables.

    The frontend calls this right after the user logs in with Google or password.
    """
    user = verify_supabase_token(payload.access_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    # Upsert user in the users and user_profiles table
    try:
        supabase = get_supabase_client()
        profile_data = {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name", ""),
            "avatar_url": user.get("avatar_url", ""),
        }
        if user.get("username"):
            profile_data["username"] = user.get("username")

        try:
            supabase.table("users").upsert(profile_data, on_conflict="id").execute()
        except Exception:
            pass

        supabase.table("user_profiles").upsert(profile_data, on_conflict="id").execute()
    except Exception:
        # If Supabase is not fully populated yet, still return user info
        pass

    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user.get("username"),
        name=user.get("name"),
        avatar_url=user.get("avatar_url"),
    )


@router.post("/resolve-username", response_model=ResolveUsernameResponse)
def resolve_username(payload: ResolveUsernameRequest):
    """Look up an email associated with a username for password login.

    Allows users to enter either their username or email to sign in.
    """
    username = payload.username.strip().lower()
    if not username:
        return ResolveUsernameResponse(exists=False, email=None)

    try:
        supabase = get_supabase_client()
        res = (
            supabase.table("user_profiles")
            .select("email")
            .ilike("username", username)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows and rows[0].get("email"):
            return ResolveUsernameResponse(exists=True, email=rows[0]["email"])
    except Exception:
        pass

    return ResolveUsernameResponse(exists=False, email=None)
