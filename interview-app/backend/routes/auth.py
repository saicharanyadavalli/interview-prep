"""Auth routes — validate Supabase JWT and manage user profiles."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from models.schemas import SessionRequest, UserResponse
from services.supabase_client import get_supabase_client, verify_supabase_token

router = APIRouter(prefix="/auth", tags=["auth"])


def get_current_user(authorization: str = Header(...)) -> dict:
    """Extract and verify the Bearer token from the Authorization header.

    Returns the user dict on success, raises 401 on failure.
    This is used as a dependency by other routes.
    """
    if not authorization.startswith("Bearer "):
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
    """Validate the access token and upsert the user in our users table.

    The frontend calls this right after the user logs in with Google.
    """
    user = verify_supabase_token(payload.access_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    # Upsert user in the users table
    try:
        supabase = get_supabase_client()
        supabase.table("users").upsert(
            {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name", ""),
                "avatar_url": user.get("avatar_url", ""),
            },
            on_conflict="id",
        ).execute()

        supabase.table("user_profiles").upsert(
            {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name", ""),
                "avatar_url": user.get("avatar_url", ""),
            },
            on_conflict="id",
        ).execute()
    except Exception:
        # If Supabase is not set up yet, still return the user info
        pass

    return UserResponse(
        id=user["id"],
        email=user["email"],
        name=user.get("name"),
        avatar_url=user.get("avatar_url"),
    )
