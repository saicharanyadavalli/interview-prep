"""User profile routes — view, edit, and upload avatar.

Persists authoritative application profile data directly to Amazon RDS PostgreSQL.
Validates input, checks username uniqueness (409 Conflict), validates avatar images
using Pillow, uploads to Amazon S3 + CloudFront CDN, and updates RDS.
"""

from __future__ import annotations

import io
import logging
import os
import re

import filetype
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from PIL import Image, UnidentifiedImageError

from limiter import limiter
from models.schemas import (
    DeleteAccountRequest,
    DeleteAccountResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    ResetProgressResponse,
    ResetProgressStats,
)
from routes.auth import get_current_user
from services import rds_client, s3_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5MB
MIN_DIMENSION = 16
MAX_DIMENSION = 4096
ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ALLOWED_PIL_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}


@router.get("/me", response_model=ProfileResponse)
@limiter.limit("60/minute")
def get_my_profile(request: Request, response: Response, current_user: dict = Depends(get_current_user)):
    """Return profile row for current user from RDS, auto-creating one if missing."""
    request.state.rate_limit_user_id = current_user.get("id")

    try:
        email = current_user.get("email", "")
        default_username = (email.split("@")[0] if email else f"user_{current_user['id'][:8]}").lower()

        row = rds_client.query(
            """
            SELECT id, email, username, name, phone, avatar_url
            FROM user_profiles
            WHERE id = %s
            LIMIT 1;
            """,
            (current_user["id"],),
            fetch="one",
        )

        if row:
            username = row.get("username") or current_user.get("username") or default_username
            # If username was missing in database, persist fallback username
            if not row.get("username"):
                rds_client.mutate(
                    "UPDATE user_profiles SET username = %s, updated_at = now() WHERE id = %s;",
                    (username, current_user["id"]),
                )

            return ProfileResponse(
                id=str(row.get("id", current_user["id"])),
                email=row.get("email", email) or email,
                username=username,
                name=row.get("name", "") or "",
                phone=row.get("phone", "") or "",
                avatar_url=row.get("avatar_url", "") or "",
            )

        # Auto-create first profile row from auth info into RDS.
        username = current_user.get("username") or default_username
        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, username, name, phone, avatar_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email,
                username = COALESCE(user_profiles.username, EXCLUDED.username),
                name = COALESCE(NULLIF(user_profiles.name, ''), EXCLUDED.name);
            """,
            (
                current_user["id"],
                email,
                username,
                current_user.get("name", "") or "",
                "",
                current_user.get("avatar_url", "") or "",
            ),
        )

        return ProfileResponse(
            id=current_user["id"],
            email=email,
            username=username,
            name=current_user.get("name", "") or "",
            phone="",
            avatar_url=current_user.get("avatar_url", "") or "",
        )
    except Exception as exc:
        logger.error("get_my_profile RDS error for user %s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve user profile.") from exc


@router.put("/me", response_model=ProfileResponse)
@limiter.limit("15/minute")
def update_my_profile(
    request: Request,
    response: Response,
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    """Update editable profile fields for current user in RDS.

    Validates field constraints and prevents username collision across users.
    """
    request.state.rate_limit_user_id = current_user.get("id")

    updates: dict[str, str] = {}

    if payload.username is not None:
        clean_user = payload.username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,50}", clean_user):
            raise HTTPException(
                status_code=422,
                detail="Username must be 3-50 characters and contain only lowercase letters, digits, or underscores.",
            )

        # Check for username uniqueness against other user accounts in RDS
        try:
            collision = rds_client.query(
                """
                SELECT id, username FROM user_profiles
                WHERE LOWER(username) = LOWER(%s) AND id != %s
                LIMIT 1;
                """,
                (clean_user, current_user["id"]),
                fetch="one",
            )
            if collision:
                raise HTTPException(
                    status_code=409,
                    detail=f"Username '{clean_user}' is already taken. Please choose another.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Username uniqueness check failed in RDS: %s", exc)
            raise HTTPException(status_code=500, detail="Failed to verify username uniqueness.") from exc

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

    try:
        set_clauses = []
        params = []
        for col, val in updates.items():
            set_clauses.append(f"{col} = %s")
            params.append(val)

        params.append(current_user["id"])
        sql = f"""
        UPDATE user_profiles
        SET {', '.join(set_clauses)}, updated_at = now()
        WHERE id = %s
        RETURNING id, email, username, name, phone, avatar_url;
        """

        rows = rds_client.mutate(sql, tuple(params), returning=True)

        if not rows:
            # If user row did not exist yet, insert it with updates
            email = current_user.get("email", "")
            username = updates.get("username") or current_user.get("username") or (email.split("@")[0] if email else f"user_{current_user['id'][:8]}")
            insert_sql = """
            INSERT INTO user_profiles (id, email, username, name, phone, avatar_url)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET username = COALESCE(EXCLUDED.username, user_profiles.username),
                name = COALESCE(EXCLUDED.name, user_profiles.name),
                phone = COALESCE(EXCLUDED.phone, user_profiles.phone),
                avatar_url = COALESCE(EXCLUDED.avatar_url, user_profiles.avatar_url),
                updated_at = now()
            RETURNING id, email, username, name, phone, avatar_url;
            """
            rows = rds_client.mutate(
                insert_sql,
                (
                    current_user["id"],
                    email,
                    username,
                    updates.get("name", ""),
                    updates.get("phone", ""),
                    updates.get("avatar_url", ""),
                ),
                returning=True,
            )

        data = rows[0]
        return ProfileResponse(
            id=str(data.get("id", current_user["id"])),
            email=data.get("email", current_user.get("email", "")),
            username=data.get("username", current_user.get("username")),
            name=data.get("name", "") or "",
            phone=data.get("phone", "") or "",
            avatar_url=data.get("avatar_url", "") or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_my_profile RDS error for user %s: %s", current_user.get("id"), exc)
        raise HTTPException(status_code=500, detail="Failed to persist profile updates.") from exc


@router.post("/avatar/upload")
@limiter.limit("3/minute")
@limiter.limit("15/hour")
async def upload_profile_avatar(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Validate, decode, upload avatar to Amazon S3 + CloudFront CDN, and persist in RDS user_profiles."""
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

    # Upload avatar to Amazon S3
    file_ext = kind.extension if kind and kind.extension else "png"
    try:
        upload_result = s3_storage_service.upload_avatar(
            user_id=current_user["id"],
            file_bytes=file_bytes,
            content_type=kind.mime,
            file_ext=file_ext,
        )
        avatar_url = upload_result.get("url") or ""
        if not avatar_url:
            raise s3_storage_service.S3StorageError("S3 storage did not return a valid URL.")
    except s3_storage_service.S3StorageError as s3_err:
        logger.error("S3 upload failed for user %s: %s", current_user.get("id"), type(s3_err).__name__)
        raise HTTPException(
            status_code=503,
            detail="External image storage service failed to upload image.",
        ) from s3_err
    except Exception as exc:
        logger.error("Unexpected error during avatar upload for user %s: %s", current_user.get("id"), type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to upload avatar.",
        ) from exc

    try:
        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, avatar_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET avatar_url = EXCLUDED.avatar_url, updated_at = now();
            """,
            (current_user["id"], current_user.get("email", ""), avatar_url),
        )
    except Exception as db_err:
        logger.error("Failed to persist avatar_url in RDS: %s", db_err)
        raise HTTPException(status_code=500, detail="Failed to persist avatar URL in database.") from db_err

    return {
        "avatar_url": avatar_url,
        "storage": "s3",
        "key": upload_result.get("key"),
        "bucket": upload_result.get("bucket"),
    }


def _run_transaction(statements: list[tuple[str, tuple | list | dict | None]]) -> list[int]:
    """Execute statements atomically, preferring rds_client.execute_transaction with fallback to mutate."""
    if hasattr(rds_client, "execute_transaction"):
        try:
            return rds_client.execute_transaction(statements)
        except Exception:
            raise
    results = []
    for sql, params in statements:
        count = rds_client.mutate(sql, params)
        results.append(count if isinstance(count, int) else 0)
    return results


def _delete_cognito_user(
    user_id: str,
    username: str | None = None,
    email: str | None = None,
) -> bool:
    """Coordinate Cognito user deletion via AdminDeleteUser.

    Resolves the authoritative Cognito username/identity from user_identities
    (e.g. provider='cognito' or provider='google'), falling back to passed username,
    email, or internal user_id.
    Uses configured COGNITO_USER_POOL_ID and COGNITO_REGION.
    Narrowly scopes error handling and handles missing/already-deleted users cleanly.
    """
    user_pool_id = (
        os.getenv("COGNITO_USER_POOL_ID")
        or os.getenv("AWS_COGNITO_USER_POOL_ID")
        or os.getenv("USER_POOL_ID")
    )
    if not user_pool_id:
        logger.debug("Cognito user pool not configured; skipping Cognito deletion.")
        return False

    # Resolve target usernames to attempt deleting from Cognito
    candidate_targets: list[str] = []

    # 1. Query user_identities for linked provider identities (e.g. cognito or google)
    try:
        identities = rds_client.query(
            """
            SELECT provider, provider_sub, email
            FROM user_identities
            WHERE user_id = %s;
            """,
            (user_id,),
            fetch="all",
        )
        if identities and isinstance(identities, list):
            for row in identities:
                sub = (row.get("provider_sub") or "").strip()
                if sub and sub not in candidate_targets:
                    candidate_targets.append(sub)
                ident_email = (row.get("email") or "").strip()
                if ident_email and ident_email not in candidate_targets:
                    candidate_targets.append(ident_email)
    except Exception as exc:
        logger.debug("Could not query user_identities for user %s: %s", user_id, exc)

    # 2. Add username and email if known
    if username and username.strip() and username.strip() not in candidate_targets:
        candidate_targets.append(username.strip())

    if email and email.strip() and email.strip() not in candidate_targets:
        candidate_targets.append(email.strip())

    # 3. Add internal user_id as final fallback
    if user_id and user_id.strip() and user_id.strip() not in candidate_targets:
        candidate_targets.append(user_id.strip())

    if not candidate_targets:
        logger.warning("No candidate identifiers found for Cognito deletion of user %s", user_id)
        return False

    region = (
        os.getenv("COGNITO_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "ap-south-2"
    ).strip()

    try:
        import boto3
        from botocore.exceptions import ClientError

        cognito = boto3.client("cognito-idp", region_name=region)
    except Exception as exc:
        logger.error("Failed to initialize boto3 cognito-idp client: %s", exc)
        return False

    deletion_succeeded = False
    for target in candidate_targets:
        try:
            cognito.admin_delete_user(
                UserPoolId=user_pool_id,
                Username=target,
            )
            logger.info("Deleted user %s from Cognito User Pool %s", target, user_pool_id)
            deletion_succeeded = True
            break
        except ClientError as ce:
            err_code = ce.response.get("Error", {}).get("Code", "")
            if err_code == "UserNotFoundException":
                logger.info("Cognito user %s not found in pool %s; trying next target if any", target, user_pool_id)
                continue
            elif err_code in ("NotAuthorizedException", "ResourceNotFoundException", "InvalidParameterException"):
                logger.warning("Cognito AdminDeleteUser client error for %s (Code: %s): %s", target, err_code, ce)
                break
            else:
                logger.warning("Cognito AdminDeleteUser unexpected ClientError for %s (Code: %s): %s", target, err_code, ce)
                break
        except Exception as exc:
            logger.warning("Unexpected error during Cognito AdminDeleteUser for %s: %s", target, exc)
            break

    return deletion_succeeded


def _delete_user_avatar_asset(user_id: str, avatar_url: str) -> bool:
    """Best-effort cleanup of user avatar in S3."""
    if not avatar_url:
        return False
    try:
        if f"avatars/{user_id}/" in avatar_url:
            key_part = "avatars/" + avatar_url.split("avatars/", 1)[1]
            return s3_storage_service.delete_asset(key_part)
    except Exception as exc:
        logger.debug("S3 avatar deletion skipped/handled gracefully: %s", exc)
    return False


@router.post("/reset-progress", response_model=ResetProgressResponse)
@limiter.limit("2/hour")
def reset_user_progress(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    """Reset question solving, learning track, and practice history progress for current user.

    Preserves user_profiles, user_comments, course_lessons, and question_bank data.
    Executes deletion transactionally in RDS.
    """
    request.state.rate_limit_user_id = current_user.get("id")
    user_id = current_user["id"]

    try:
        statements = [
            ("DELETE FROM user_progress WHERE user_id = %s;", (user_id,)),
            ("DELETE FROM learning_track_progress WHERE user_id = %s;", (user_id,)),
            ("DELETE FROM practice_history WHERE user_id = %s;", (user_id,)),
        ]
        counts = _run_transaction(statements)
        user_progress_deleted = counts[0] if len(counts) > 0 else 0
        learning_track_deleted = counts[1] if len(counts) > 1 else 0
        practice_history_deleted = counts[2] if len(counts) > 2 else 0

        logger.info(
            "Reset progress for user %s: %d user_progress, %d learning_track, %d practice_history",
            user_id,
            user_progress_deleted,
            learning_track_deleted,
            practice_history_deleted,
        )

        return ResetProgressResponse(
            success=True,
            message="Progress reset successfully",
            stats=ResetProgressStats(
                user_progress_deleted=user_progress_deleted,
                learning_track_progress_deleted=learning_track_deleted,
                practice_history_deleted=practice_history_deleted,
            ),
        )
    except Exception as exc:
        logger.error("Failed to reset progress for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to reset user progress.") from exc


@router.delete("/account", response_model=DeleteAccountResponse)
@limiter.limit("2/hour")
def delete_user_account(
    request: Request,
    response: Response,
    payload: DeleteAccountRequest,
    current_user: dict = Depends(get_current_user),
):
    """Permanently delete user account and all associated user-owned records.

    Transactionally deletes user records across RDS (user_identities, user_comments,
    user_progress, learning_track_progress, practice_history, and user_profiles).
    Coordinates Cognito user deletion/disablement.
    """
    request.state.rate_limit_user_id = current_user.get("id")
    user_id = current_user["id"]

    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Account deletion must be explicitly confirmed with confirm=true.",
        )

    # 1. Fetch profile to check avatar_url for cleanup before deleting row
    avatar_url = ""
    try:
        profile_row = rds_client.query(
            "SELECT avatar_url, username FROM user_profiles WHERE id = %s LIMIT 1;",
            (user_id,),
            fetch="one",
        )
        if profile_row:
            avatar_url = profile_row.get("avatar_url") or ""
    except Exception as exc:
        logger.warning("Could not fetch user avatar before deletion: %s", exc)

    # 2. Check if user_identities table exists in database
    identities_table_exists = False
    try:
        identities_table_exists = bool(
            rds_client.query(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'user_identities' LIMIT 1;",
                fetch="scalar",
            )
        )
    except Exception as exc:
        logger.debug("user_identities table check skipped: %s", exc)

    # 3. Coordinate Cognito user deletion / disablement (graceful partial failure handling).
    # We resolve and coordinate Cognito deletion prior to clearing user_identities records
    # so we can discover provider_sub and linked accounts.
    _delete_cognito_user(
        user_id=user_id,
        username=current_user.get("username"),
        email=current_user.get("email"),
    )

    # 4. Assemble atomic transaction statements in strict dependency order:
    # (user_identities, user_comments, user_progress, learning_track_progress, practice_history, and finally user_profiles)
    statements = []
    if identities_table_exists:
        statements.append(("DELETE FROM user_identities WHERE user_id = %s;", (user_id,)))
    statements.extend([
        ("DELETE FROM user_comments WHERE user_id = %s;", (user_id,)),
        ("DELETE FROM user_progress WHERE user_id = %s;", (user_id,)),
        ("DELETE FROM learning_track_progress WHERE user_id = %s;", (user_id,)),
        ("DELETE FROM practice_history WHERE user_id = %s;", (user_id,)),
        ("DELETE FROM user_profiles WHERE id = %s;", (user_id,)),
    ])

    try:
        _run_transaction(statements)
        logger.info("Successfully deleted all RDS records for user %s", user_id)
    except Exception as exc:
        logger.error("Failed to delete user records in RDS for %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete account data.") from exc

    # 5. Best-effort avatar cleanup in S3
    if avatar_url:
        _delete_user_avatar_asset(user_id=user_id, avatar_url=avatar_url)

    return DeleteAccountResponse(
        success=True,
        message="Account deleted successfully",
    )
