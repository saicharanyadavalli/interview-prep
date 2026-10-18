"""Unit tests for s3_storage_service."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from services import s3_storage_service
from services.s3_storage_service import (
    DEFAULT_S3_BUCKET,
    DEFAULT_S3_REGION,
    S3StorageError,
    delete_asset,
    get_asset_base_url,
    get_s3_bucket,
    get_s3_client,
    get_s3_region,
    reset_s3_client,
    upload_avatar,
)


@pytest.fixture(autouse=True)
def clean_s3_env():
    """Ensure clean S3 environment variables and reset client cache for every test."""
    reset_s3_client()
    old_env = {
        "S3_ASSETS_BUCKET": os.environ.get("S3_ASSETS_BUCKET"),
        "S3_ASSETS_REGION": os.environ.get("S3_ASSETS_REGION"),
        "AWS_REGION": os.environ.get("AWS_REGION"),
        "ASSET_BASE_URL": os.environ.get("ASSET_BASE_URL"),
    }
    # Clear test env vars
    for k in old_env:
        if k in os.environ:
            del os.environ[k]

    yield

    reset_s3_client()
    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]


def test_defaults_when_env_unset():
    """Verify default bucket, region, and S3 fallback base URL."""
    assert get_s3_bucket() == DEFAULT_S3_BUCKET
    assert get_s3_region() == DEFAULT_S3_REGION
    expected_base = f"https://{DEFAULT_S3_BUCKET}.s3.{DEFAULT_S3_REGION}.amazonaws.com"
    assert get_asset_base_url() == expected_base


def test_custom_environment_configuration():
    """Verify custom bucket, region, and CloudFront asset base URL from environment."""
    os.environ["S3_ASSETS_BUCKET"] = "custom-test-bucket"
    os.environ["S3_ASSETS_REGION"] = "us-east-1"
    os.environ["ASSET_BASE_URL"] = "https://d123456abcdef8.cloudfront.net/"

    assert get_s3_bucket() == "custom-test-bucket"
    assert get_s3_region() == "us-east-1"
    # Trailing slash should be stripped
    assert get_asset_base_url() == "https://d123456abcdef8.cloudfront.net"


def test_get_s3_client_caching_and_reset():
    """Verify get_s3_client caches the client instance and reset_s3_client clears it."""
    with patch("boto3.client") as mock_boto:
        mock_instance_1 = MagicMock()
        mock_instance_2 = MagicMock()
        mock_boto.side_effect = [mock_instance_1, mock_instance_2]

        c1 = get_s3_client()
        c2 = get_s3_client()
        assert c1 is c2
        assert mock_boto.call_count == 1

        reset_s3_client()
        c3 = get_s3_client()
        assert c3 is mock_instance_2
        assert mock_boto.call_count == 2


def test_upload_avatar_success_with_cloudfront_url():
    """Verify upload_avatar puts object to S3 with safe key and returns CloudFront URL."""
    os.environ["ASSET_BASE_URL"] = "https://d123456abcdef8.cloudfront.net"
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        res = upload_avatar(
            user_id="user-12345",
            file_bytes=b"\x89PNG\r\n\x1a\nfake-png-data",
            content_type="image/png",
            file_ext="png",
        )

        assert mock_s3.put_object.call_count == 1
        call_kwargs = mock_s3.put_object.call_args[1]
        assert call_kwargs["Bucket"] == DEFAULT_S3_BUCKET
        assert call_kwargs["ContentType"] == "image/png"
        assert call_kwargs["Body"] == b"\x89PNG\r\n\x1a\nfake-png-data"
        assert call_kwargs["Metadata"] == {"user_id": "user-12345"}

        key = call_kwargs["Key"]
        assert key.startswith("avatars/user-12345/")
        assert key.endswith(".png")

        assert res["bucket"] == DEFAULT_S3_BUCKET
        assert res["key"] == key
        assert res["url"] == f"https://d123456abcdef8.cloudfront.net/{key}"


def test_upload_avatar_extension_normalization_and_leading_dot():
    """Verify upload_avatar strips leading dots and cleans extension."""
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        res = upload_avatar(
            user_id="user-xyz",
            file_bytes=b"dummy-data",
            content_type="image/jpeg",
            file_ext=".JPEG",
        )
        key = res["key"]
        assert key.startswith("avatars/user-xyz/")
        assert key.endswith(".jpeg")
        assert not key.endswith("..jpeg")


def test_upload_avatar_empty_ext_derives_from_mimetype():
    """Verify upload_avatar derives extension from content_type if file_ext is empty."""
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        res = upload_avatar(
            user_id="user-abc",
            file_bytes=b"dummy-webp-data",
            content_type="image/webp",
            file_ext="",
        )
        assert res["key"].endswith(".webp")


def test_upload_avatar_user_id_sanitization_prevents_directory_traversal():
    """Verify user_id path traversal characters are sanitized out."""
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        res = upload_avatar(
            user_id="../../etc/passwd",
            file_bytes=b"data",
            content_type="image/png",
            file_ext="png",
        )
        # Slashes and dots stripped: 'etcpasswd'
        assert ".." not in res["key"]
        assert res["key"].startswith("avatars/etcpasswd/")


def test_upload_avatar_empty_inputs_raise_value_error():
    """Verify empty user_id or empty file_bytes raises ValueError."""
    with pytest.raises(ValueError, match="user_id"):
        upload_avatar(user_id="", file_bytes=b"data", content_type="image/png")

    with pytest.raises(ValueError, match="file_bytes"):
        upload_avatar(user_id="user-123", file_bytes=b"", content_type="image/png")


def test_upload_avatar_s3_client_error_raises_s3_storage_error():
    """Verify ClientError from boto3 is wrapped in S3StorageError without leaking secrets."""
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied to S3 bucket"}},
        "PutObject",
    )

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        with pytest.raises(S3StorageError, match="Failed to upload asset to S3"):
            upload_avatar(
                user_id="user-fail",
                file_bytes=b"bytes",
                content_type="image/png",
            )


def test_upload_avatar_s3_botocore_error_raises_s3_storage_error():
    """Verify BotoCoreError from boto3 is wrapped in S3StorageError."""
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = BotoCoreError()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        with pytest.raises(S3StorageError, match="Failed to upload asset to S3"):
            upload_avatar(
                user_id="user-fail2",
                file_bytes=b"bytes",
                content_type="image/png",
            )


def test_delete_asset_success():
    """Verify delete_asset calls delete_object on S3 client and returns True."""
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        success = delete_asset("avatars/user-123/uuid-456.png")
        assert success is True
        mock_s3.delete_object.assert_called_once_with(
            Bucket=DEFAULT_S3_BUCKET,
            Key="avatars/user-123/uuid-456.png",
        )


def test_delete_asset_invalid_key_returns_false():
    """Verify delete_asset rejects empty, leading slash, or traversal keys."""
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        assert delete_asset("") is False
        assert delete_asset("   ") is False
        assert delete_asset("/avatars/user/1.png") is False
        assert delete_asset("avatars/../../secret.png") is False
        assert mock_s3.delete_object.call_count == 0


def test_delete_asset_handles_s3_error_gracefully():
    """Verify delete_asset catches ClientError and returns False."""
    mock_s3 = MagicMock()
    mock_s3.delete_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchBucket", "Message": "The specified bucket does not exist"}},
        "DeleteObject",
    )

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        success = delete_asset("avatars/user-123/pic.png")
        assert success is False
