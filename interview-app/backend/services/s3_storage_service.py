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

_s3_client: Optional[Any] = None


class S3StorageError(Exception):
    """Raised when an S3 storage operation fails."""
    pass


def get_s3_bucket() -> str:
    """Return the configured S3 bucket name from environment."""
    return (os.getenv("S3_ASSETS_BUCKET") or DEFAULT_S3_BUCKET).strip()


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
    Falls back to direct S3 regional endpoint: https://{bucket}.s3.{region}.amazonaws.com
    """
    custom_base = (os.getenv("ASSET_BASE_URL") or "").strip().rstrip("/")
    if custom_base:
        return custom_base

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

    bucket = get_s3_bucket()
    try:
        client = get_s3_client()
        client.delete_object(Bucket=bucket, Key=clean_key)
        logger.info("Successfully deleted S3 asset key=%s bucket=%s", clean_key, bucket)
        return True
    except (ClientError, BotoCoreError) as err:
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
