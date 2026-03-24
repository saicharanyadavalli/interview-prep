"""Profile routes — read/update editable user profile fields."""

from __future__ import annotations

import base64
import os
import re

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from models.schemas import ProfileResponse, ProfileUpdateRequest
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client

router = APIRouter(prefix="/profile", tags=["profile"])


def _configure_cloudinary() -> tuple[bool, str]:
    """Configure Cloudinary when credentials exist.

    Returns (is_configured, upload_folder).
    """
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
    folder = os.getenv("CLOUDINARY_AVATAR_FOLDER", "interview-prep/avatars").strip() or "interview-prep/avatars"

    if not cloud_name or not api_key or not api_secret:
        return False, folder

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True, folder


@router.get("/me", response_model=ProfileResponse)
def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Return profile row for current user, auto-creating one if missing."""
    supabase = get_supabase_client()

    try:
        rows = (
            supabase.table("user_profiles")
            .select("id,email,name,phone,avatar_url")
            .eq("id", current_user["id"])
            .limit(1)
            .execute()
        ).data or []

        if rows:
            row = rows[0]
            return ProfileResponse(
                id=row.get("id", current_user["id"]),
                email=row.get("email", current_user.get("email", "")),
                name=row.get("name", "") or "",
                phone=row.get("phone", "") or "",
                avatar_url=row.get("avatar_url", "") or "",
            )

        # Auto-create first profile row from auth info.
        payload = {
            "id": current_user["id"],
            "email": current_user.get("email", ""),
            "name": current_user.get("name", "") or "",
            "phone": "",
            "avatar_url": current_user.get("avatar_url", "") or "",
        }
        supabase.table("user_profiles").upsert(payload, on_conflict="id").execute()

        return ProfileResponse(**payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


@router.put("/me", response_model=ProfileResponse)
def update_my_profile(payload: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Update editable profile fields for current user."""
    supabase = get_supabase_client()

    updates = {}
    if payload.name is not None:
        updates["name"] = payload.name.strip()
    if payload.phone is not None:
        phone = payload.phone.strip()
        if phone and not re.fullmatch(r"\d{10}", phone):
            raise HTTPException(status_code=422, detail="Phone number must be exactly 10 digits.")
        updates["phone"] = phone
    if payload.avatar_url is not None:
        updates["avatar_url"] = payload.avatar_url.strip()

    if not updates:
        raise HTTPException(status_code=400, detail="No profile fields provided to update.")

    updates["id"] = current_user["id"]
    updates["email"] = current_user.get("email", "")

    try:
        supabase.table("user_profiles").upsert(updates, on_conflict="id").execute()

        row = (
            supabase.table("user_profiles")
            .select("id,email,name,phone,avatar_url")
            .eq("id", current_user["id"])
            .limit(1)
            .execute()
        ).data or []

        if not row:
            raise HTTPException(status_code=500, detail="Could not load updated profile.")

        data = row[0]
        return ProfileResponse(
            id=data.get("id", current_user["id"]),
            email=data.get("email", current_user.get("email", "")),
            name=data.get("name", "") or "",
            phone=data.get("phone", "") or "",
            avatar_url=data.get("avatar_url", "") or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc


@router.post("/avatar/upload")
async def upload_profile_avatar(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload avatar image to Cloudinary and persist secure URL in user profile."""
    if not file:
        raise HTTPException(status_code=400, detail="No file provided.")

    content_type = str(file.content_type or "")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(file_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image size must be 5MB or less.")

    is_cloudinary_configured, folder = _configure_cloudinary()

    try:
        avatar_url = ""
        storage_mode = ""

        if is_cloudinary_configured:
            result = cloudinary.uploader.upload(
                file_bytes,
                folder=f"{folder}/{current_user['id']}",
                public_id="avatar",
                overwrite=True,
                resource_type="image",
            )
            avatar_url = result.get("secure_url") or result.get("url") or ""
            storage_mode = "cloudinary"
        else:
            # Fallback for local/dev: store compact data URL directly in profile.
            encoded = base64.b64encode(file_bytes).decode("ascii")
            avatar_url = f"data:{content_type};base64,{encoded}"
            storage_mode = "inline"

        if not avatar_url:
            raise HTTPException(status_code=500, detail="Avatar storage did not return a URL.")

        supabase = get_supabase_client()
        supabase.table("user_profiles").upsert(
            {
                "id": current_user["id"],
                "email": current_user.get("email", ""),
                "avatar_url": avatar_url,
            },
            on_conflict="id",
        ).execute()

        return {"avatar_url": avatar_url, "storage": storage_mode}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cloudinary upload failed: {exc}") from exc
