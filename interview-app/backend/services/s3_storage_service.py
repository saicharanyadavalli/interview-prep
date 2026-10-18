"""Amazon S3 + CloudFront asset storage service.

Manages asset persistence (avatars, system design assets) using Amazon S3
and delivery via Amazon CloudFront CDN.
Uses the default AWS credential provider chain (IAM instance role on EC2).
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

DEFAULT_S3_BUCKET = "interview-prep-assets-808431466075-ap-south-2"
DEFAULT_S3_REGION = "ap-south-2"

FORBIDDEN_BASE_URL_PATTERNS = [
    r"d123456abcdef8",
    r"<distribution[-_]id>",
    r"<.*?>",
    r"placeholder",
]

_s3_client: Optional[Any] = None


class S3StorageError(Exception):
    """Raised when an S3 storage operation fails."""
    pass


def is_production_or_staging() -> bool:
    """Return True if running in production or staging environment."""
    env = (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("ENV")
        or ""
    ).lower().strip()
    return env in ("production", "prod", "staging")


def is_test_mode() -> bool:
    """Return True if running in explicit test mode."""
    if is_production_or_staging():
        return False
    return (
        os.getenv("TESTING") == "1"
        or os.getenv("TESTING", "").lower() in ("true", "yes")
        or (os.getenv("ENV") or "").lower() == "test"
        or (os.getenv("ENVIRONMENT") or "").lower() == "test"
        or (os.getenv("APP_ENV") or "").lower() == "test"
    )


def validate_asset_base_url(url: str) -> str:
    """Validate asset base delivery URL format, protocol, and check against fictitious placeholders."""
    clean_url = str(url or "").strip().rstrip("/")
    if not clean_url:
        raise S3StorageError("ASSET_BASE_URL cannot be empty.")
    if not clean_url.startswith("https://"):
        raise S3StorageError(f"ASSET_BASE_URL must use HTTPS protocol: '{clean_url}'")
    for pattern in FORBIDDEN_BASE_URL_PATTERNS:
        if re.search(pattern, clean_url, re.IGNORECASE):
            raise S3StorageError(
                f"ASSET_BASE_URL contains invalid placeholder or fictitious domain: '{clean_url}'"
            )
    return clean_url


def validate_s3_bucket(bucket: str) -> str:
    """Validate S3 bucket name format and prevent placeholders."""
    clean_bucket = str(bucket or "").strip()
    if not clean_bucket:
        raise S3StorageError("S3 bucket name cannot be empty.")
    if "<" in clean_bucket or ">" in clean_bucket or "placeholder" in clean_bucket.lower():
        raise S3StorageError(f"S3 bucket name contains placeholder: '{clean_bucket}'")
    if not re.match(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$", clean_bucket):
        raise S3StorageError(f"Invalid S3 bucket name syntax: '{clean_bucket}'")
    return clean_bucket


def get_s3_bucket() -> str:
    """Return the configured S3 bucket name from environment.

    In production/staging, requires S3_ASSETS_BUCKET to be set and valid.
    In development/testing, falls back to DEFAULT_S3_BUCKET if unset.
    """
    raw_bucket = os.getenv("S3_ASSETS_BUCKET")
    if is_production_or_staging():
        if not raw_bucket or not raw_bucket.strip():
            raise S3StorageError(
                "S3_ASSETS_BUCKET environment variable is required in production/staging and cannot be empty."
            )
        return validate_s3_bucket(raw_bucket.strip())

    bucket = (raw_bucket or DEFAULT_S3_BUCKET).strip()
    return validate_s3_bucket(bucket)


def get_s3_region() -> str:
    """Return the configured S3 region from environment."""
    return (
        os.getenv("S3_ASSETS_REGION")
        or os.getenv("AWS_REGION")
        or DEFAULT_S3_REGION
    ).strip()


def get_asset_base_url() -> str:
    """Return the CDN/storage base delivery URL.

    Prefers ASSET_BASE_URL (CloudFront distribution domain).
    Must be HTTPS and must not be a fictitious placeholder.

    Direct S3 regional fallback is strictly forbidden in production and staging
    (and outside explicit test mode) because private S3 buckets protected by OAC
    will return 403 Forbidden to end users.

    Fallback to regional S3 or mock URL is permitted ONLY when an explicit test flag
    is set (TESTING=1 or ENV=test).
    """
    custom_base = (os.getenv("ASSET_BASE_URL") or "").strip().rstrip("/")
    if custom_base:
        return validate_asset_base_url(custom_base)

    if is_production_or_staging():
        raise S3StorageError(
            "ASSET_BASE_URL environment variable is required in production/staging. "
            "Direct regional S3 fallback is forbidden for private buckets protected by OAC."
        )

    if not is_test_mode():
        raise S3StorageError(
            "ASSET_BASE_URL must be configured. "
            "Direct regional S3 fallback is disabled to prevent 403 Forbidden errors with private OAC-protected buckets. "
            "Set ASSET_BASE_URL or run in test mode (TESTING=1 or ENV=test)."
        )

    bucket = get_s3_bucket()
    region = get_s3_region()
    return f"https://{bucket}.s3.{region}.amazonaws.com"


def get_s3_client():
    """Initialize or return cached boto3 S3 client using default credential provider chain."""
    global _s3_client
    if _s3_client is None:
        region = get_s3_region()
        _s3_client = boto3.client("s3", region_name=region)
    return _s3_client


def reset_s3_client() -> None:
    """Reset cached client (useful for unit testing)."""
    global _s3_client
    _s3_client = None


def upload_avatar(
    user_id: str,
    file_bytes: bytes,
    content_type: str,
    file_ext: str = "png",
) -> Dict[str, str]:
    """Upload a user avatar image to S3.

    Generates a secure key hierarchy:
        avatars/{user_id}/{uuid4()}.{ext}

    Never utilizes client-provided filenames to prevent traversal attacks.

    Args:
        user_id: User identifier (UUID or alphanumeric string).
        file_bytes: Decoded binary image data.
        content_type: Validated MIME type (e.g. 'image/png').
        file_ext: File extension (e.g. 'png', 'jpg'). Leading dots stripped.

    Returns:
        Dict with keys 'url', 'key', 'bucket'.

    Raises:
        ValueError: If user_id or file_bytes is empty or invalid.
        S3StorageError: If S3 put_object fails.
    """
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        raise ValueError("user_id cannot be empty")

    clean_user_id = re.sub(r"[^a-zA-Z0-9_\-]", "", clean_user_id)
    if not clean_user_id:
        raise ValueError("user_id contains no valid characters")

    if not file_bytes or len(file_bytes) == 0:
        raise ValueError("file_bytes cannot be empty")

    clean_ext = file_ext.lstrip(".").lower().strip()
    clean_ext = re.sub(r"[^a-z0-9]", "", clean_ext)
    if not clean_ext:
        mime_map = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        clean_ext = mime_map.get(content_type.lower(), "png")

    file_uuid = str(uuid.uuid4())
    key = f"avatars/{clean_user_id}/{file_uuid}.{clean_ext}"
    bucket = get_s3_bucket()
    base_url = get_asset_base_url()

    try:
        client = get_s3_client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            Metadata={
                "user_id": clean_user_id,
            },
        )
        url = f"{base_url}/{key}"
        logger.info("Successfully uploaded avatar to S3 key=%s bucket=%s", key, bucket)
        return {
            "url": url,
            "key": key,
            "bucket": bucket,
        }
    except (ClientError, BotoCoreError) as err:
        logger.error(
            "S3 put_object failed for user_id=%s bucket=%s key=%s error=%s",
            clean_user_id,
            bucket,
            key,
            type(err).__name__,
        )
        raise S3StorageError(f"Failed to upload asset to S3: {err}") from err
    except Exception as exc:
        logger.error(
            "Unexpected error uploading avatar for user_id=%s: %s",
            clean_user_id,
            type(exc).__name__,
        )
        raise S3StorageError(f"Unexpected error during avatar upload: {exc}") from exc


def delete_asset(key: str) -> bool:
    """Delete an asset from the S3 assets bucket.

    Args:
        key: The S3 object key (e.g. 'avatars/{user_id}/{uuid}.png').

    Returns:
        True if deletion succeeded, False otherwise.
    """
    clean_key = str(key or "").strip()
    if not clean_key or clean_key.startswith("/") or ".." in clean_key:
        logger.warning("Attempted to delete asset with invalid key: %s", clean_key)
        return False

    try:
        bucket = get_s3_bucket()
        client = get_s3_client()
        client.delete_object(Bucket=bucket, Key=clean_key)
        logger.info("Successfully deleted S3 asset key=%s bucket=%s", clean_key, bucket)
        return True
    except (ClientError, BotoCoreError, S3StorageError) as err:
        logger.error(
            "S3 delete_object failed for bucket=%s key=%s error=%s",
            bucket,
            clean_key,
            type(err).__name__,
        )
        return False
    except Exception as exc:
        logger.error(
            "Unexpected error deleting S3 asset key=%s: %s",
            clean_key,
            type(exc).__name__,
        )
        return False
