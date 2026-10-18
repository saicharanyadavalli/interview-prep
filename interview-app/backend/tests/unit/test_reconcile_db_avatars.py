"""Unit tests for scripts/reconcile_db_avatars.py.

Tests:
  - Safety classifiers and external URL preservation (Google, GitHub, inline base64, empty).
  - Avatar filename extraction and S3/CloudFront URL mapping generation.
  - Manifest mapping precedence.
  - Dry-run candidate detection without database mutations.
  - Strict SQL parameterization to prevent injection vulnerabilities.
  - Multi-row transaction atomicity and commit on success.
  - Transaction rollback on database failure.
  - Safety abort for --execute without --confirm.
  - Old-to-new mapping export and rollback verification.
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
    execute_avatar_updates,
    execute_rollback,
    export_mapping_file,
    extract_avatar_filename,
    is_cloudinary_avatar,
    is_preserved_avatar,
    load_rollback_mappings,
    main,
    reconcile_avatars,
    should_migrate_avatar,
)


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
        "https://d123456abcdef8.cloudfront.net/avatars/user-1/avatar.png",
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
    """Verify mapped URL generation with CloudFront ASSET_BASE_URL."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1234567890/interview-prep/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png"
    user_id = "4a2b9687-9d7a-4286-b489-35a1f6a15db4"
    asset_base_url = "https://d123456abcdef8.cloudfront.net"

    mapped = build_mapped_avatar_url(
        old_url=old_url,
        user_id=user_id,
        asset_base_url=asset_base_url,
    )
    expected = "https://d123456abcdef8.cloudfront.net/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png"
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
    )
    expected = "https://my-custom-bucket.s3.ap-south-2.amazonaws.com/avatars/user-99/avatar.jpg"
    assert mapped == expected


def test_build_mapped_avatar_url_manifest_precedence():
    """Verify that explicit manifest mappings take highest precedence."""
    old_url = "https://res.cloudinary.com/demo/image/upload/v1/avatar.png"
    user_id = "user-abc"
    manifest_map = {
        old_url: "https://d123456abcdef8.cloudfront.net/avatars/user-abc/custom-uuid-384.png"
    }

    mapped = build_mapped_avatar_url(
        old_url=old_url,
        user_id=user_id,
        asset_base_url="https://fallback.cloudfront.net",
        manifest_mapping=manifest_map,
    )
    assert mapped == "https://d123456abcdef8.cloudfront.net/avatars/user-abc/custom-uuid-384.png"


# -----------------------------------------------------------------------------
# 3. DRY-RUN DETECTION & EXTERNAL URL PRESERVATION IN RECONCILIATION
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

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        asset_base_url="https://d123.cloudfront.net",
        client=mock_client,
    )

    assert result["mode"] == "dry-run"
    assert result["scanned"] == 2
    assert result["candidates"] == 2
    assert result["executed"] == 0
    assert len(result["mappings"]) == 2
    assert result["mappings"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert result["mappings"][0]["new_avatar_url"] == "https://d123.cloudfront.net/avatars/11111111-1111-1111-1111-111111111111/avatar.png"

    # Crucial: verify zero mutations were attempted in dry-run
    mock_client.mutate.assert_not_called()


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
        asset_base_url="https://d123.cloudfront.net",
        client=mock_client,
    )

    assert result["scanned"] == 6
    assert result["candidates"] == 1
    assert result["mappings"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert result["preserved_counts"]["google"] == 1
    assert result["preserved_counts"]["github"] == 1
    assert result["preserved_counts"]["inline_data"] == 1
    assert result["preserved_counts"]["empty"] == 2


# -----------------------------------------------------------------------------
# 4. SQL PARAMETERIZATION & IMMUTABILITY
# -----------------------------------------------------------------------------
def test_sql_parameterization_strict_usage():
    """Verify that avatar updates strictly use %s parameterized placeholders and touch only avatar_url & updated_at."""
    # Ensure SQL_UPDATE_AVATAR does not update email, username, phone, or name
    assert "email" not in SQL_UPDATE_AVATAR
    assert "username" not in SQL_UPDATE_AVATAR
    assert "name" not in SQL_UPDATE_AVATAR
    assert "phone" not in SQL_UPDATE_AVATAR
    assert "avatar_url = %s" in SQL_UPDATE_AVATAR
    assert "WHERE id = %s" in SQL_UPDATE_AVATAR

def _make_mock_client(mock_conn):
    """Helper to create a mock database client supporting both get_db_pool and get_connection."""
    client = MagicMock()
    client.get_connection.return_value.__enter__.return_value = mock_conn
    client.get_db_pool.return_value.get_connection.return_value.__enter__.return_value = mock_conn
    return client


def test_sql_parameterization_strict_usage():
    """Verify that avatar updates strictly use %s parameterized placeholders and touch only avatar_url & updated_at."""
    # Ensure SQL_UPDATE_AVATAR does not update email, username, phone, or name
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
        ("https://d123.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d123.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
    ]

    count = execute_avatar_updates(updates, client=mock_client)
    assert count == 2
    assert mock_cursor.execute.call_count == 2

    # Check that parameters are passed as tuples, not interpolated
    call1 = mock_cursor.execute.call_args_list[0]
    call2 = mock_cursor.execute.call_args_list[1]
    assert call1 == call(SQL_UPDATE_AVATAR, ("https://d123.cloudfront.net/avatars/user-1/avatar.png", "user-1"))
    assert call2 == call(SQL_UPDATE_AVATAR, ("https://d123.cloudfront.net/avatars/user-2/avatar.png", "user-2"))


# -----------------------------------------------------------------------------
# 5. TRANSACTION COMMIT & ROLLBACK ON FAILURE
# -----------------------------------------------------------------------------
def test_transaction_commit_on_success():
    """Verify that multiple updates are committed in an explicit transaction."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    mock_client = _make_mock_client(mock_conn)

    updates = [
        ("https://d123.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d123.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
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

    # First execute succeeds, second execute fails
    mock_cursor.execute.side_effect = [None, RuntimeError("Simulated RDS connection timeout")]

    mock_client = _make_mock_client(mock_conn)

    updates = [
        ("https://d123.cloudfront.net/avatars/user-1/avatar.png", "user-1"),
        ("https://d123.cloudfront.net/avatars/user-2/avatar.png", "user-2"),
    ]

    with pytest.raises(RuntimeError, match="Simulated RDS connection timeout"):
        execute_avatar_updates(updates, client=mock_client)

    # CRITICAL: commit must NEVER be called, rollback MUST be called
    mock_conn.commit.assert_not_called()
    mock_conn.rollback.assert_called_once()


# -----------------------------------------------------------------------------
# 6. SAFETY ABORT ON EXECUTE WITHOUT CONFIRM
# -----------------------------------------------------------------------------
def test_safety_abort_on_execute_without_confirm():
    """Verify reconcile_avatars raises ValueError when mode='execute' but confirm=False."""
    with pytest.raises(ValueError, match="--execute requires explicit --confirm flag"):
        reconcile_avatars(mode="execute", confirm=False)


def test_cli_main_safety_abort(capsys):
    """Verify CLI main exits with code 1 if --execute is passed without --confirm."""
    exit_code = main(["--execute"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "--confirm" in captured.out


# -----------------------------------------------------------------------------
# 7. EXPORT MAPPING & ROLLBACK VERIFICATION
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
            "new_avatar_url": "https://d123.cloudfront.net/avatars/user-uuid-1/avatar.png",
        },
        {
            "id": "user-uuid-2",
            "email": "u2@example.com",
            "username": "u2",
            "old_avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/u2/avatar.jpg",
            "new_avatar_url": "https://d123.cloudfront.net/avatars/user-uuid-2/avatar.jpg",
        },
    ]

    exported = export_mapping_file(
        filepath=mapping_file,
        mappings=mappings,
        asset_base_url="https://d123.cloudfront.net",
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
# 8. MOCKING rds_client DIRECTLY (AS REQUESTED IN SPEC)
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

    with patch("reconcile_db_avatars.rds_client") as mock_rds:
        mock_rds.query.return_value = mock_rows
        mock_rds.get_db_pool.return_value.get_connection.return_value.__enter__.return_value = mock_conn

        # Execute live update
        result = reconcile_avatars(
            mode="execute",
            confirm=True,
            asset_base_url="https://d123.cloudfront.net",
        )

        assert result["executed"] == 1
        assert result["candidates"] == 1
        mock_rds.query.assert_called_once()
        mock_cursor.execute.assert_called_once_with(
            SQL_UPDATE_AVATAR,
            ("https://d123.cloudfront.net/avatars/abc-123/avatar.png", "abc-123"),
        )
        mock_conn.commit.assert_called_once()


def test_reconcile_avatars_empty_rows():
    """Verify reconcile_avatars handles zero candidate rows gracefully."""
    mock_client = MagicMock()
    mock_client.query.return_value = []

    result = reconcile_avatars(
        mode="dry-run",
        confirm=False,
        client=mock_client,
    )
    assert result["scanned"] == 0
    assert result["candidates"] == 0
    assert result["executed"] == 0
    assert result["mappings"] == []


# -----------------------------------------------------------------------------
# 9. CLI INVOCATIONS INTEGRATION
# -----------------------------------------------------------------------------
def test_cli_main_dry_run_success():
    """Verify CLI main executes dry-run successfully."""
    with patch("reconcile_db_avatars.reconcile_avatars") as mock_rec:
        mock_rec.return_value = {"candidates": 0}
        code = main(["--dry-run", "--asset-base-url", "https://d123.cloudfront.net"])
        assert code == 0
        mock_rec.assert_called_once()
        assert mock_rec.call_args[1]["mode"] == "dry-run"
        assert mock_rec.call_args[1]["confirm"] is False


def test_cli_main_execute_confirm_success():
    """Verify CLI main executes live migration when --confirm is passed."""
    with patch("reconcile_db_avatars.reconcile_avatars") as mock_rec:
        mock_rec.return_value = {"executed": 3}
        code = main(["--execute", "--confirm"])
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

