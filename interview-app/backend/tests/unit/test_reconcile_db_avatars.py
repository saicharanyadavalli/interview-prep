"""Unit tests for scripts/reconcile_db_avatars.py.

Tests:
  - Safety classifiers and external URL preservation (Google, GitHub, inline base64, empty).
  - Avatar filename extraction and S3/CloudFront URL mapping generation.
  - ASSET_BASE_URL validation and rejection of placeholder hostnames.
  - S3 destination object existence verification gate (unverified not eligible vs. verified eligible).
  - Dry-run candidate detection and explicit 8-metric breakdown.
  - Manifest mapping precedence and verification.
  - Strict SQL parameterization to prevent injection vulnerabilities.
  - Multi-row transaction atomicity and commit on success.
  - Transaction rollback on database failure.
  - Safety abort for --execute without --confirm.
  - Old-to-new mapping export and rollback verification (skipping un-migrated items).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

import sys
backend_dir = Path(__file__).resolve().parent.parent.parent
scripts_dir = backend_dir.parent / "scripts"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from reconcile_db_avatars import (
    SQL_UPDATE_AVATAR,
    build_mapped_avatar_url,
    check_s3_destination_exists,
    execute_avatar_updates,
    execute_rollback,
    export_mapping_file,
    extract_avatar_filename,
    is_cloudinary_avatar,
    is_preserved_avatar,
    load_rollback_mappings,
    load_verified_manifest_entries,
    main,
    reconcile_avatars,
    should_migrate_avatar,
    validate_asset_base_url,
)


def _make_mock_client(mock_conn):
    """Helper to create a mock database client supporting both get_db_pool and get_connection."""
    client = MagicMock()
    client.get_connection.return_value.__enter__.return_value = mock_conn
    client.get_db_pool.return_value.get_connection.return_value.__enter__.return_value = mock_conn
    return client


# -----------------------------------------------------------------------------
# 1. SAFETY CLASSIFIERS & EXTERNAL URL PRESERVATION
# -----------------------------------------------------------------------------
def test_is_preserved_avatar_empty_and_null():
    """Verify empty, whitespace, and None avatar URLs are classified as preserved."""
    assert is_preserved_avatar(None) is True
    assert is_preserved_avatar("") is True
    assert is_preserved_avatar("   ") is True


def test_is_preserved_avatar_google():
    """Verify Google user content avatars are strictly preserved."""
    google_urls = [
        "https://lh3.googleusercontent.com/a/ACg8ocISomeHash123",
        "https://lh4.googleusercontent.com/ogw/AF2bZcjExample",
        "http://sub.googleusercontent.com/avatar.jpg",
    ]
    for url in google_urls:
        assert is_preserved_avatar(url) is True
        assert should_migrate_avatar(url) is False


def test_is_preserved_avatar_github():
    """Verify GitHub user content avatars are strictly preserved."""
    github_urls = [
        "https://avatars.githubusercontent.com/u/12345678?v=4",
        "https://githubusercontent.com/u/87654321",
    ]
    for url in github_urls:
        assert is_preserved_avatar(url) is True
        assert should_migrate_avatar(url) is False


def test_is_preserved_avatar_inline_base64():
    """Verify inline data URIs (base64) are strictly preserved."""
    data_urls = [
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
        "data:image/webp;base64,UklGRg==",
    ]
    for url in data_urls:
        assert is_preserved_avatar(url) is True
        assert should_migrate_avatar(url) is False


def test_is_cloudinary_avatar_detection():
    """Verify Cloudinary URLs are correctly detected."""
    cloudinary_urls = [
        "https://res.cloudinary.com/interview-prep/image/upload/v12345/interview-prep/avatars/user-1/avatar.png",
        "http://res.cloudinary.com/cloud/image/upload/avatar.jpg",
        "https://cloudinary.com/images/user123.webp",
    ]
    for url in cloudinary_urls:
        assert is_cloudinary_avatar(url) is True
        assert is_preserved_avatar(url) is False
        assert should_migrate_avatar(url) is True


def test_should_migrate_avatar_strict_guardrail():
    """Verify that an already migrated S3 or CloudFront avatar is not re-migrated."""
    s3_urls = [
        "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-1/avatar.png",
        "https://interview-prep-assets-808431466075-ap-south-2.s3.ap-south-2.amazonaws.com/avatars/user-1/avatar.png",
    ]
    for url in s3_urls:
        assert is_cloudinary_avatar(url) is False
        assert should_migrate_avatar(url) is False


# -----------------------------------------------------------------------------
# 2. FILENAME EXTRACTION & URL MAPPING GENERATION
# -----------------------------------------------------------------------------
def test_extract_avatar_filename():
    """Verify filename and extension extraction across various URL forms."""
    assert extract_avatar_filename("https://res.cloudinary.com/cloud/image/upload/v1/avatars/u1/avatar.png") == "avatar.png"
    assert extract_avatar_filename("https://res.cloudinary.com/cloud/image/upload/v1/avatars/u1/profile.jpeg") == "profile.jpeg"
    assert extract_avatar_filename("https://res.cloudinary.com/cloud/image/upload/v1/avatars/u1/photo.webp?v=123#anchor") == "photo.webp"
    # No extension falls back to .png
    assert extract_avatar_filename("https://res.cloudinary.com/cloud/image/upload/v1/avatars/u1/avatar") == "avatar.png"
    assert extract_avatar_filename("") == "avatar.png"


def test_build_mapped_avatar_url_cloudfront():
    """Verify mapped URL generation with valid CloudFront ASSET_BASE_URL."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1234567890/interview-prep/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png"
    user_id = "4a2b9687-9d7a-4286-b489-35a1f6a15db4"
    asset_base_url = "https://d3xxxxxxxxxxxx.cloudfront.net"

    mapped = build_mapped_avatar_url(
        old_url=old_url,
        user_id=user_id,
        asset_base_url=asset_base_url,
    )
    expected = "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png"
    assert mapped == expected


def test_build_mapped_avatar_url_s3_fallback():
    """Verify mapped URL generation fallback to direct S3 origin."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1234567890/interview-prep/avatars/user-99/avatar.jpg"
    user_id = "user-99"

    mapped = build_mapped_avatar_url(
        old_url=old_url,
        user_id=user_id,
        asset_base_url="",  # No CloudFront base URL
        s3_bucket="my-custom-bucket",
        s3_region="ap-south-2",
        allow_s3_fallback=True,
    )
    expected = "https://my-custom-bucket.s3.ap-south-2.amazonaws.com/avatars/user-99/avatar.jpg"
    assert mapped == expected


def test_build_mapped_avatar_url_manifest_precedence():
    """Verify that explicit manifest mappings take highest precedence."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/avatar.png"
    user_id = "user-abc"
    manifest_map = {
        old_url: "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-abc/custom-uuid-384.png"
    }

    mapped = build_mapped_avatar_url(
        old_url=old_url,
        user_id=user_id,
        asset_base_url="https://d3fallback.cloudfront.net",
        manifest_mapping=manifest_map,
    )
    assert mapped == "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-abc/custom-uuid-384.png"


# -----------------------------------------------------------------------------
# 3. ASSET_BASE_URL VALIDATION & REJECTION OF PLACEHOLDER HOSTNAMES
# -----------------------------------------------------------------------------
def test_validate_asset_base_url_rejects_placeholders():
    """Verify that validate_asset_base_url strictly rejects known placeholders."""
    placeholders = [
        "https://d123456abcdef8.cloudfront.net",
        "https://d123456abcdef8.cloudfront.net/",
        "https://<distribution-id>.cloudfront.net",
        "https://<distribution_id>.cloudfront.net",
        "https://your-distribution-id.cloudfront.net",
        "https://example.com/assets",
        "https://placeholder.cloudfront.net",
    ]
    for url in placeholders:
        with pytest.raises(ValueError, match="forbidden placeholder pattern"):
            validate_asset_base_url(url)


def test_validate_asset_base_url_rejects_empty_and_non_https():
    """Verify validate_asset_base_url rejects empty string, None, and non-HTTPS URLs."""
    with pytest.raises(ValueError, match="ASSET_BASE_URL is required"):
        validate_asset_base_url(None)
    with pytest.raises(ValueError, match="ASSET_BASE_URL is required"):
        validate_asset_base_url("")
    with pytest.raises(ValueError, match="ASSET_BASE_URL is required"):
        validate_asset_base_url("   ")
    with pytest.raises(ValueError, match="must use HTTPS protocol"):
        validate_asset_base_url("http://d3xxxxxxxxxxxx.cloudfront.net")


def test_validate_asset_base_url_accepts_valid_cloudfront():
    """Verify valid CloudFront or custom CDN domains are accepted."""
    valid_urls = [
        "https://d3xxxxxxxxxxxx.cloudfront.net",
        "https://d39j2k0l1m2n3o.cloudfront.net/",
        "https://assets.interviewprep.com",
    ]
    for url in valid_urls:
        clean = validate_asset_base_url(url)
        assert clean.startswith("https://")
        assert not clean.endswith("/")


# -----------------------------------------------------------------------------
# 4. S3 OBJECT DESTINATION VERIFICATION GATE
# -----------------------------------------------------------------------------
def test_unverified_s3_object_not_marked_eligible():
    """Verify that a Cloudinary candidate whose S3 object does not exist is NOT marked eligible."""
    mock_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "user1@example.com",
            "username": "user1",
            "avatar_url": "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/11111111-1111-1111-1111-111111111111/avatar.png",
        }
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = Exception("NoSuchKey: The specified key does not exist.")

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    assert result["candidates"] == 1
    assert result["verified_destinations"] == 0
    assert result["missing_destinations"] == 1
    assert result["eligible"] == 0
    assert result["unchanged"] == 1
    assert len(result["eligible_mappings"]) == 0
    assert result["mappings"][0]["status"] == "missing_destination"
    assert result["mappings"][0]["destination_verified"] is False
    assert result["breakdown"]["missing_destinations"] == 1
    assert result["breakdown"]["eligible_for_change"] == 0
    assert result["breakdown"]["must_remain_unchanged"] == 1


def test_unverified_s3_object_not_mutated_on_execute():
    """Verify that unverified S3 objects are NEVER mutated in RDS even with --execute --confirm."""
    mock_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "user1@example.com",
            "username": "user1",
            "avatar_url": "https://res.cloudinary.com/demo/image/upload/v1/avatars/u1/avatar.png",
        }
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = Exception("NoSuchKey")

    result = reconcile_avatars(
        mode="execute",
        confirm=True,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    assert result["candidates"] == 1
    assert result["eligible"] == 0
    assert result["executed"] == 0
    mock_cursor.execute.assert_not_called()


def test_verified_s3_object_marked_eligible_and_mutated():
    """Verify that an avatar whose S3 destination object exists is marked eligible and mutated on execute."""
    mock_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "user1@example.com",
            "username": "user1",
            "avatar_url": "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/11111111-1111-1111-1111-111111111111/avatar.png",
        }
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 4096}

    result = reconcile_avatars(
        mode="execute",
        confirm=True,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    assert result["candidates"] == 1
    assert result["verified_destinations"] == 1
    assert result["missing_destinations"] == 0
    assert result["eligible"] == 1
    assert result["executed"] == 1
    assert result["mappings"][0]["status"] == "eligible"
    assert result["mappings"][0]["destination_verified"] is True
    assert mock_cursor.execute.call_count == 1
    mock_conn.commit.assert_called_once()


def test_manifest_verified_s3_object_marked_eligible(tmp_path):
    """Verify that an avatar verified via manifest entry is marked eligible without S3 client."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/u1/avatar.png"
    manifest_file = tmp_path / "migration-manifest.json"
    manifest_file.write_text(json.dumps([
        {
            "original_url": old_url,
            "s3_key": "avatars/u1/avatar.png",
            "cloudfront_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/u1/avatar.png",
            "status": "verified",
        }
    ]), encoding="utf-8")

    mock_rows = [
        {
            "id": "u1",
            "email": "u1@test.com",
            "username": "u1",
            "avatar_url": old_url,
        }
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        manifest_path=str(manifest_file),
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=None,
    )

    assert result["candidates"] == 1
    assert result["verified_destinations"] == 1
    assert result["eligible"] == 1
    assert result["mappings"][0]["status"] == "eligible"


def test_manifest_unavailable_source(tmp_path):
    """Verify that an avatar marked failed/unavailable in manifest is counted and not eligible."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/avatars/u-fail/avatar.png"
    manifest_file = tmp_path / "manifest_failed.json"
    manifest_file.write_text(json.dumps([
        {
            "original_url": old_url,
            "status": "failed",
        }
    ]), encoding="utf-8")

    mock_rows = [
        {
            "id": "u-fail",
            "email": "fail@test.com",
            "avatar_url": old_url,
        }
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    result = reconcile_avatars(
        mode="dry-run",
        manifest_path=str(manifest_file),
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
    )

    assert result["candidates"] == 1
    assert result["unavailable_sources"] == 1
    assert result["eligible"] == 0
    assert result["mappings"][0]["status"] == "unavailable_source"


# -----------------------------------------------------------------------------
# 5. DRY-RUN DETECTION & 8-METRIC BREAKDOWN
# -----------------------------------------------------------------------------
def test_reconcile_avatars_dry_run_candidate_detection():
    """Verify dry-run mode identifies Cloudinary candidates without modifying database."""
    mock_rows = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "user1@example.com",
            "username": "user1",
            "name": "User One",
            "phone": "",
            "avatar_url": "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/11111111-1111-1111-1111-111111111111/avatar.png",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "email": "user2@example.com",
            "username": "user2",
            "name": "User Two",
            "phone": "",
            "avatar_url": "https://res.cloudinary.com/demo/image/upload/v2/interview-prep/avatars/22222222-2222-2222-2222-222222222222/avatar.jpg",
        },
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 1024}

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    assert result["mode"] == "dry-run"
    assert result["scanned"] == 2
    assert result["candidates"] == 2
    assert result["verified_destinations"] == 2
    assert result["eligible"] == 2
    assert result["executed"] == 0
    assert len(result["mappings"]) == 2
    assert result["mappings"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert result["mappings"][0]["new_avatar_url"] == "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/11111111-1111-1111-1111-111111111111/avatar.png"


def test_reconcile_avatars_preserves_external_and_data_urls():
    """Verify Google, GitHub, inline base64, and empty avatars are preserved and not migrated."""
    mixed_rows = [
        # 1. Cloudinary (migratable)
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "email": "c@test.com",
            "avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/avatars/11111111-1111-1111-1111-111111111111/avatar.png",
        },
        # 2. Google OAuth avatar
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "email": "g@google.com",
            "avatar_url": "https://lh3.googleusercontent.com/a/ACg8ocISomeUserPhoto",
        },
        # 3. GitHub OAuth avatar
        {
            "id": "33333333-3333-3333-3333-333333333333",
            "email": "gh@github.com",
            "avatar_url": "https://avatars.githubusercontent.com/u/98765432?v=4",
        },
        # 4. Inline Base64 Data URL
        {
            "id": "44444444-4444-4444-4444-444444444444",
            "email": "inline@test.com",
            "avatar_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCA==",
        },
        # 5. Empty string
        {
            "id": "55555555-5555-5555-5555-555555555555",
            "email": "empty@test.com",
            "avatar_url": "",
        },
        # 6. Null / None
        {
            "id": "66666666-6666-6666-6666-666666666666",
            "email": "none@test.com",
            "avatar_url": None,
        },
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mixed_rows

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
    )

    assert result["scanned"] == 6
    assert result["candidates"] == 1
    assert result["mappings"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert result["preserved_counts"]["google"] == 1
    assert result["preserved_counts"]["github"] == 1
    assert result["preserved_counts"]["inline_data"] == 1
    assert result["preserved_counts"]["empty"] == 2


def test_dry_run_explicit_breakdown_metrics():
    """Verify that dry-run provides the complete 8-metric breakdown requested in spec."""
    mock_rows = [
        # 1. Verified Cloudinary candidate
        {"id": "u1", "email": "u1@test.com", "avatar_url": "https://res.cloudinary.com/demo/u1.png"},
        # 2. Missing S3 destination Cloudinary candidate
        {"id": "u2", "email": "u2@test.com", "avatar_url": "https://res.cloudinary.com/demo/u2.png"},
        # 3. Preserved Google avatar
        {"id": "u3", "email": "u3@test.com", "avatar_url": "https://lh3.googleusercontent.com/photo3"},
        # 4. Preserved GitHub avatar
        {"id": "u4", "email": "u4@test.com", "avatar_url": "https://avatars.githubusercontent.com/u/4"},
        # 5. Preserved Inline Data URI
        {"id": "u5", "email": "u5@test.com", "avatar_url": "data:image/png;base64,iVBORw0KGgo="},
        # 6. Preserved Empty avatar
        {"id": "u6", "email": "u6@test.com", "avatar_url": ""},
        # 7. Invalid mapping (empty user ID)
        {"id": "", "email": "u7@test.com", "avatar_url": "https://res.cloudinary.com/demo/u7.png"},
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    def mock_head_object(Bucket, Key):
        if "u1" in Key:
            return {"ContentLength": 1024}
        raise Exception("404 Not Found")

    mock_s3.head_object.side_effect = mock_head_object

    result = reconcile_avatars(
        mode="dry-run",
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    b = result["breakdown"]
    assert b["profiles_scanned"] == 7
    assert b["cloudinary_candidates"] == 3
    assert b["verified_destinations"] == 1
    assert b["missing_destinations"] == 1
    assert b["unavailable_sources"] == 0
    assert b["invalid_mappings"] == 1
    assert b["eligible_for_change"] == 1
    assert b["must_remain_unchanged"] == 6

    # Invariant: eligible + unchanged == scanned
    assert b["eligible_for_change"] + b["must_remain_unchanged"] == b["profiles_scanned"]


# -----------------------------------------------------------------------------
# 6. SQL PARAMETERIZATION & IMMUTABILITY
# -----------------------------------------------------------------------------
def test_sql_parameterization_strict_usage():
    """Verify that avatar updates strictly use %s parameterized placeholders and touch only avatar_url & updated_at."""
    assert "email" not in SQL_UPDATE_AVATAR
    assert "username" not in SQL_UPDATE_AVATAR
    assert "name" not in SQL_UPDATE_AVATAR
    assert "phone" not in SQL_UPDATE_AVATAR
    assert "avatar_url = %s" in SQL_UPDATE_AVATAR
    assert "WHERE id = %s" in SQL_UPDATE_AVATAR

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)

    updates = [
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
    ]

    count = execute_avatar_updates(updates, client=mock_client)
    assert count == 2
    assert mock_cursor.execute.call_count == 2

    call1 = mock_cursor.execute.call_args_list[0]
    call2 = mock_cursor.execute.call_args_list[1]
    assert call1 == call(SQL_UPDATE_AVATAR, ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-1/avatar.png", "user-1"))
    assert call2 == call(SQL_UPDATE_AVATAR, ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-2/avatar.png", "user-2"))


# -----------------------------------------------------------------------------
# 7. TRANSACTION COMMIT & ROLLBACK ON FAILURE
# -----------------------------------------------------------------------------
def test_transaction_commit_on_success():
    """Verify that multiple updates are committed in an explicit transaction."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)

    updates = [
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
    ]

    count = execute_avatar_updates(updates, client=mock_client)
    assert count == 2
    mock_conn.commit.assert_called_once()
    mock_conn.rollback.assert_not_called()


def test_transaction_rollback_on_failure():
    """Verify that any database exception during batch update triggers conn.rollback()."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_cursor.execute.side_effect = [None, RuntimeError("Simulated RDS connection timeout")]

    mock_client = _make_mock_client(mock_conn)

    updates = [
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
    ]

    with pytest.raises(RuntimeError, match="Simulated RDS connection timeout"):
        execute_avatar_updates(updates, client=mock_client)

    mock_conn.commit.assert_not_called()
    mock_conn.rollback.assert_called_once()


# -----------------------------------------------------------------------------
# 8. SAFETY ABORT ON EXECUTE WITHOUT CONFIRM
# -----------------------------------------------------------------------------
def test_safety_abort_on_execute_without_confirm():
    """Verify reconcile_avatars raises ValueError when mode='execute' but confirm=False."""
    with pytest.raises(ValueError, match="--execute requires explicit --confirm flag"):
        reconcile_avatars(mode="execute", confirm=False, asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net")


def test_cli_main_safety_abort(capsys):
    """Verify CLI main exits with code 1 if --execute is passed without --confirm."""
    exit_code = main(["--execute", "--asset-base-url", "https://d3xxxxxxxxxxxx.cloudfront.net"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "--confirm" in captured.out


# -----------------------------------------------------------------------------
# 9. EXPORT MAPPING & ROLLBACK VERIFICATION
# -----------------------------------------------------------------------------
def test_export_mapping_and_rollback_flow(tmp_path):
    """Verify exporting mapping to JSON and performing transactional rollback."""
    mapping_file = tmp_path / "rollback_mapping.json"
    mappings = [
        {
            "id": "user-uuid-1",
            "email": "u1@example.com",
            "username": "u1",
            "old_avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/u1/avatar.png",
            "new_avatar_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-uuid-1/avatar.png",
            "status": "eligible",
        },
        {
            "id": "user-uuid-2",
            "email": "u2@example.com",
            "username": "u2",
            "old_avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/u2/avatar.jpg",
            "new_avatar_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/user-uuid-2/avatar.jpg",
            "status": "eligible",
        },
    ]

    exported = export_mapping_file(
        filepath=mapping_file,
        mappings=mappings,
        eligible_mappings=mappings,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
    )
    assert exported.is_file()

    loaded = load_rollback_mappings(mapping_file)
    assert len(loaded) == 2
    assert loaded[0]["id"] == "user-uuid-1"
    assert loaded[0]["old_avatar_url"] == "https://res.cloudinary.com/cloud/image/upload/v1/u1/avatar.png"

    # Rollback dry-run (confirm=False)
    dry_rollback = execute_rollback(mapping_file, confirm=False)
    assert dry_rollback["total_records"] == 2
    assert dry_rollback["executed"] is False
    assert dry_rollback["restored"] == 0

    # Live rollback with mock client
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)

    live_rollback = execute_rollback(mapping_file, confirm=True, client=mock_client)
    assert live_rollback["executed"] is True
    assert live_rollback["restored"] == 2
    assert mock_cursor.execute.call_count == 2
    mock_conn.commit.assert_called_once()


def test_rollback_skips_unverified_missing_destination(tmp_path):
    """Verify load_rollback_mappings excludes missing_destination / un-migrated items."""
    mapping_file = tmp_path / "mapping.json"
    mapping_file.write_text(json.dumps({
        "mappings": [
            {
                "id": "u1",
                "old_avatar_url": "https://res.cloudinary.com/u1.png",
                "status": "eligible",
            },
            {
                "id": "u2",
                "old_avatar_url": "https://res.cloudinary.com/u2.png",
                "status": "missing_destination",
            },
            {
                "id": "u3",
                "old_avatar_url": "https://res.cloudinary.com/u3.png",
                "status": "invalid_mapping",
            },
        ]
    }), encoding="utf-8")

    loaded = load_rollback_mappings(mapping_file)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "u1"
    assert loaded[0]["old_avatar_url"] == "https://res.cloudinary.com/u1.png"


def test_rollback_failure_triggers_rollback(tmp_path):
    """Verify database failure during rollback rolls back transaction."""
    mapping_file = tmp_path / "rollback.json"
    mapping_file.write_text(json.dumps({
        "mappings": [
            {"id": "u1", "old_avatar_url": "https://res.cloudinary.com/u1.png"}
        ]
    }), encoding="utf-8")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_cursor.execute.side_effect = RuntimeError("Deadlock on user_profiles")

    mock_client = _make_mock_client(mock_conn)

    with pytest.raises(RuntimeError, match="Deadlock on user_profiles"):
        execute_rollback(mapping_file, confirm=True, client=mock_client)

    mock_conn.commit.assert_not_called()
    mock_conn.rollback.assert_called_once()


def test_rollback_missing_file_raises():
    """Verify load_rollback_mappings raises FileNotFoundError if file is absent."""
    with pytest.raises(FileNotFoundError):
        load_rollback_mappings("non_existent_file_xyz_123.json")


def test_rollback_invalid_schema_raises(tmp_path):
    """Verify load_rollback_mappings raises ValueError on invalid schema."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps({"mappings": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="expected list of mappings"):
        load_rollback_mappings(bad_file)

    bad_item_file = tmp_path / "bad_item.json"
    bad_item_file.write_text(json.dumps({"mappings": [{"id": ""}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing required 'id' or 'old_avatar_url'"):
        load_rollback_mappings(bad_item_file)


# -----------------------------------------------------------------------------
# 10. MOCKING rds_client DIRECTLY
# -----------------------------------------------------------------------------
def test_reconcile_avatars_mocking_rds_client_directly():
    """Verify reconcile_avatars works when rds_client module is patched directly."""
    mock_rows = [
        {
            "id": "abc-123",
            "email": "agent5@test.com",
            "avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/interview-prep/avatars/abc-123/avatar.png",
        }
    ]

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 512}

    with patch("reconcile_db_avatars.rds_client") as mock_rds:
        mock_rds.query.return_value = mock_rows
        mock_rds.get_db_pool.return_value.get_connection.return_value.__enter__.return_value = mock_conn

        # Execute live update
        result = reconcile_avatars(
            mode="execute",
            confirm=True,
            asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
            s3_client=mock_s3,
        )

        assert result["executed"] == 1
        assert result["candidates"] == 1
        assert result["verified_destinations"] == 1
        mock_rds.query.assert_called_once()
        mock_cursor.execute.assert_called_once_with(
            SQL_UPDATE_AVATAR,
            ("https://d3xxxxxxxxxxxx.cloudfront.net/avatars/abc-123/avatar.png", "abc-123"),
        )
        mock_conn.commit.assert_called_once()


def test_reconcile_avatars_empty_rows():
    """Verify reconcile_avatars handles zero candidate rows gracefully."""
    mock_client = MagicMock()
    mock_client.query.return_value = []

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
    )
    assert result["scanned"] == 0
    assert result["candidates"] == 0
    assert result["executed"] == 0
    assert result["mappings"] == []


# -----------------------------------------------------------------------------
# 11. CLI INVOCATIONS INTEGRATION
# -----------------------------------------------------------------------------
def test_cli_main_dry_run_success():
    """Verify CLI main executes dry-run successfully."""
    with patch("reconcile_db_avatars.reconcile_avatars") as mock_rec:
        mock_rec.return_value = {"candidates": 0}
        code = main(["--dry-run", "--asset-base-url", "https://d3xxxxxxxxxxxx.cloudfront.net"])
        assert code == 0
        mock_rec.assert_called_once()
        assert mock_rec.call_args[1]["mode"] == "dry-run"
        assert mock_rec.call_args[1]["confirm"] is False


def test_cli_main_execute_confirm_success():
    """Verify CLI main executes live migration when --confirm is passed."""
    with patch("reconcile_db_avatars.reconcile_avatars") as mock_rec:
        mock_rec.return_value = {"executed": 3}
        code = main(["--execute", "--confirm", "--asset-base-url", "https://d3xxxxxxxxxxxx.cloudfront.net"])
        assert code == 0
        mock_rec.assert_called_once()
        assert mock_rec.call_args[1]["mode"] == "execute"
        assert mock_rec.call_args[1]["confirm"] is True


def test_cli_main_rollback_invocation(tmp_path):
    """Verify CLI main handles rollback subcommand."""
    rollback_file = tmp_path / "rollback.json"
    rollback_file.write_text(json.dumps({
        "mappings": [{"id": "u1", "old_avatar_url": "https://res.cloudinary.com/u1.png"}]
    }), encoding="utf-8")

    with patch("reconcile_db_avatars.execute_rollback") as mock_rb:
        mock_rb.return_value = {"executed": True, "restored": 1}
        code = main(["--rollback", str(rollback_file), "--confirm"])
        assert code == 0
        mock_rb.assert_called_once_with(
            filepath=str(rollback_file),
            confirm=True,
        )


# -----------------------------------------------------------------------------
# 12. REGRESSION TESTS: STALE MANIFEST & S3 VERIFICATION PRECEDENCE
# -----------------------------------------------------------------------------
def test_stale_manifest_status_overridden_by_s3_head_object_failure(tmp_path):
    """Verify that a stale manifest entry with status='verified' does NOT override S3 HeadObject failure."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/u1/avatar.png"
    manifest_file = tmp_path / "stale_manifest.json"
    manifest_file.write_text(json.dumps([
        {
            "original_url": old_url,
            "s3_key": "avatars/u1/avatar.png",
            "cloudfront_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/u1/avatar.png",
            "status": "verified",
            "sha256": "fakehash123",
            "byte_count": 1024,
        }
    ]), encoding="utf-8")

    mock_rows = [
        {
            "id": "u1",
            "email": "u1@test.com",
            "username": "u1",
            "avatar_url": old_url,
        }
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    mock_s3 = MagicMock()
    # Live S3 check fails because object is absent in the actual S3 bucket
    mock_s3.head_object.side_effect = Exception("NoSuchKey: The specified key does not exist.")

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        manifest_path=str(manifest_file),
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=mock_s3,
    )

    # S3 verification took precedence: object is missing in S3, so it is NOT eligible!
    assert result["candidates"] == 1
    assert result["verified_destinations"] == 0
    assert result["missing_destinations"] == 1
    assert result["eligible"] == 0
    assert result["mappings"][0]["status"] == "missing_destination"
    assert result["mappings"][0]["destination_verified"] is False
    assert result["mappings"][0]["eligible"] is False


def test_manifest_unverified_uploaded_status_rejected_without_s3_client(tmp_path):
    """Verify that a manifest entry with status='uploaded' or 'pending' is NOT treated as verified."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/interview-prep/avatars/u2/avatar.png"
    manifest_file = tmp_path / "unverified_manifest.json"
    manifest_file.write_text(json.dumps([
        {
            "original_url": old_url,
            "s3_key": "avatars/u2/avatar.png",
            "cloudfront_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/u2/avatar.png",
            "status": "uploaded",  # Not verified!
        }
    ]), encoding="utf-8")

    mock_rows = [
        {
            "id": "u2",
            "email": "u2@test.com",
            "username": "u2",
            "avatar_url": old_url,
        }
    ]

    mock_client = MagicMock()
    mock_client.query.return_value = mock_rows

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        manifest_path=str(manifest_file),
        asset_base_url="https://d3xxxxxxxxxxxx.cloudfront.net",
        client=mock_client,
        s3_client=None,
    )

    assert result["candidates"] == 1
    assert result["verified_destinations"] == 0
    assert result["missing_destinations"] == 1
    assert result["eligible"] == 0
    assert result["mappings"][0]["status"] == "missing_destination"


def test_personal_environment_default_bucket_configuration():
    """Verify default bucket and region constants reflect personal environment."""
    from reconcile_db_avatars import DEFAULT_S3_BUCKET, DEFAULT_S3_REGION
    assert "personal" in DEFAULT_S3_BUCKET
    assert "808431466075" in DEFAULT_S3_BUCKET
    assert DEFAULT_S3_REGION == "ap-south-2"
