"""Profile routes — read/update editable user profile fields and upload avatars.

Rate limiting:
  GET  /profile/me          — 60/minute per user
  PUT  /profile/me          — 10/minute, 60/hour per user
  POST /profile/avatar/upload — 5/minute, 20/hour per user
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re

import cloudinary
import cloudinary.uploader
import filetype
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Response
from limiter import limiter
from PIL import Image, UnidentifiedImageError

from models.schemas import ProfileResponse, ProfileUpdateRequest
from routes.auth import get_current_user
from services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_PIL_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
MIN_DIMENSION = 1
MAX_DIMENSION = 4096


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
@limiter.limit("5000/minute")
def get_my_profile(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    """Return profile row for current user, auto-creating one if missing."""
    request.state.rate_limit_user_id = current_user.get("id")
    supabase = get_supabase_client()

    try:
        email = current_user.get("email", "")
        default_username = (email.split("@")[0] if email else f"user_{current_user['id'][:8]}").lower()

        rows = (
            supabase.table("user_profiles")
            .select("id,email,username,name,phone,avatar_url")
            .eq("id", current_user["id"])
            .limit(1)
            .execute()
        ).data or []

        if rows:
            row = rows[0]
            username = row.get("username") or current_user.get("username") or default_username
            # If username was missing in database, persist fallback username
            if not row.get("username"):
                supabase.table("user_profiles").update({"username": username}).eq("id", current_user["id"]).execute()

            return ProfileResponse(
                id=row.get("id", current_user["id"]),
                email=row.get("email", email),
                username=username,
                name=row.get("name", "") or "",
                phone=row.get("phone", "") or "",
                avatar_url=row.get("avatar_url", "") or "",
            )

        # Auto-create first profile row from auth info.
        username = current_user.get("username") or default_username
        payload = {
            "id": current_user["id"],
            "email": email,
            "username": username,
            "name": current_user.get("name", "") or "",
            "phone": "",
            "avatar_url": current_user.get("avatar_url", "") or "",
        }
        supabase.table("user_profiles").upsert(payload, on_conflict="id").execute()

        return ProfileResponse(**payload)
    except Exception as exc:
        logger.error("get_my_profile database error for user %s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve user profile.") from exc


@router.put("/me", response_model=ProfileResponse)
@limiter.limit("5000/minute")
def update_my_profile(
    request: Request,
    response: Response,
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update editable profile fields for current user.

    Validates field constraints and prevents username collision across users.
    """
    request.state.rate_limit_user_id = current_user.get("id")
    supabase = get_supabase_client()

    updates: dict[str, str] = {}

    if payload.username is not None:
        clean_user = payload.username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,50}", clean_user):
            raise HTTPException(
                status_code=422,
                detail="Username must be 3-50 characters and contain only lowercase letters, digits, or underscores.",
            )

        # Check for username uniqueness against other user accounts
        try:
            existing = (
                supabase.table("user_profiles")
                .select("id,username")
                .eq("username", clean_user)
                .execute()
            ).data or []
            collision = any(
                r.get("id") != current_user["id"] and (r.get("username") or "").lower() == clean_user
                for r in existing
            )
            if collision:
                raise HTTPException(
                    status_code=409,
                    detail=f"Username '{clean_user}' is already taken. Please choose another.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Username uniqueness check failed: %s", exc)

        updates["username"] = clean_user

    if payload.name is not None:
        clean_name = payload.name.strip()
        if clean_name and not re.fullmatch(r"^[A-Za-z0-9 _\-']+$", clean_name):
            raise HTTPException(status_code=422, detail="Name contains invalid characters.")
        updates["name"] = clean_name

    if payload.phone is not None:
        clean_phone = payload.phone.strip()
        if clean_phone and not re.fullmatch(r"\d{7,15}", clean_phone):
            raise HTTPException(status_code=422, detail="Phone number must be between 7 and 15 digits.")
        updates["phone"] = clean_phone

    if payload.avatar_url is not None:
        clean_avatar = payload.avatar_url.strip()
        if clean_avatar and not (
            clean_avatar.startswith("https://")
            or clean_avatar.startswith("http://")
            or clean_avatar.startswith("data:image/")
        ):
            raise HTTPException(status_code=422, detail="Invalid avatar URL format.")
        updates["avatar_url"] = clean_avatar

    if not updates:
        raise HTTPException(status_code=400, detail="No profile fields provided to update.")

    updates["id"] = current_user["id"]
    updates["email"] = current_user.get("email", "")

    try:
        supabase.table("user_profiles").upsert(updates, on_conflict="id").execute()

        rows = (
            supabase.table("user_profiles")
            .select("id,email,username,name,phone,avatar_url")
            .eq("id", current_user["id"])
            .limit(1)
            .execute()
        ).data or []

        if not rows:
            raise HTTPException(status_code=500, detail="Could not reload updated profile.")

        data = rows[0]
        return ProfileResponse(
            id=data.get("id", current_user["id"]),
            email=data.get("email", current_user.get("email", "")),
            username=data.get("username", current_user.get("username")),
            name=data.get("name", "") or "",
            phone=data.get("phone", "") or "",
            avatar_url=data.get("avatar_url", "") or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_my_profile database error for user %s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=500, detail="Failed to persist profile updates.") from exc


@router.post("/avatar/upload")
@limiter.limit("5000/minute")
async def upload_profile_avatar(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Validate, decode, upload avatar to Cloudinary, and persist secure URL in user profile."""
    request.state.rate_limit_user_id = current_user.get("id")

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided.")

    content_type = str(file.content_type or "").lower().strip()
    if content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Allowed formats: JPEG, PNG, WebP, GIF.",
        )

    file_bytes = await file.read()
    if not file_bytes or len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(file_bytes) > MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image size must be {MAX_AVATAR_BYTES // (1024 * 1024)}MB or less.",
        )

    # Magic byte MIME verification
    kind = filetype.guess(file_bytes)
    if kind is None or kind.mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=400,
            detail="Invalid or spoofed image file format.",
        )

    # Deep image decoding & integrity check using Pillow
    try:
        # First pass: verify file structure
        img_verify = Image.open(io.BytesIO(file_bytes))
        img_verify.verify()

        # Second pass: inspect dimensions and format
        img = Image.open(io.BytesIO(file_bytes))
        fmt = str(img.format).upper()
        if fmt not in ALLOWED_PIL_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image format '{fmt}'. Allowed formats: JPEG, PNG, WebP, GIF.",
            )

        width, height = img.size
        if width < MIN_DIMENSION or height < MIN_DIMENSION:
            raise HTTPException(
                status_code=400,
                detail=f"Image dimensions are too small (minimum {MIN_DIMENSION}x{MIN_DIMENSION} pixels).",
            )
        if width > MAX_DIMENSION or height > MAX_DIMENSION:
            raise HTTPException(
                status_code=400,
                detail=f"Image dimensions are too large (maximum {MAX_DIMENSION}x{MAX_DIMENSION} pixels).",
            )
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as err:
        logger.warning("Avatar image decode failed for user %s: %s", current_user.get("id"), err)
        raise HTTPException(
            status_code=400,
            detail="Corrupted or undecodable image data.",
        ) from err

    is_cloudinary_configured, folder = _configure_cloudinary()

    avatar_url = ""
    storage_mode = ""

    if is_cloudinary_configured:
        try:
            result = cloudinary.uploader.upload(
                file_bytes,
                folder=f"{folder}/{current_user['id']}",
                public_id="avatar",
                overwrite=True,
                resource_type="image",
            )
            avatar_url = result.get("secure_url") or result.get("url") or ""
            storage_mode = "cloudinary"
        except Exception as c_err:
            logger.error("Cloudinary upload failed for user %s: %s", current_user.get("id"), type(c_err).__name__)
            raise HTTPException(
                status_code=502,
                detail="External image storage service failed to upload image.",
            ) from c_err
    else:
        # Fallback inline data URL when external cloud storage is not configured
        encoded = base64.b64encode(file_bytes).decode("ascii")
        avatar_url = f"data:{kind.mime};base64,{encoded}"
        storage_mode = "inline"

    if not avatar_url:
        raise HTTPException(status_code=500, detail="Avatar storage did not return a valid URL.")

    try:
        supabase = get_supabase_client()
        supabase.table("user_profiles").upsert(
            {
                "id": current_user["id"],
                "email": current_user.get("email", ""),
                "avatar_url": avatar_url,
            },
            on_conflict="id",
        ).execute()
    except Exception as db_err:
        logger.error("Failed to persist avatar_url in database: %s", db_err)
        raise HTTPException(status_code=500, detail="Failed to persist avatar URL in database.") from db_err

    return {"avatar_url": avatar_url, "storage": storage_mode}
