"""Unit tests for Cloudinary to S3 + CloudFront migration utility (scripts/migrate_cloudinary_to_s3.py).

Verifies:
- URL parsing, Cloudinary canonical ID generation, and S3 key generation rules.
- Manifest schema validation, load/save, and incremental update resumability.
- Safe inventory scanning with directory and file exclusions.
- Download and S3 upload logic with retries, hashing, and mock boto3 client.
- Verification logic via S3 HeadObject and optional CloudFront edge verification.
- HTML rewriting safety rules (ONLY verified assets rewritten, all structure/attributes preserved).
- Reconciliation audit report and exit codes.
- CLI argument parsing and flags.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys

# Ensure scripts directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
scripts_dir = backend_dir.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from migrate_cloudinary_to_s3 import (
    ManifestEntry,
    build_or_update_manifest,
    download_asset,
    execute_inventory,
    execute_reconcile,
    execute_rewrite,
    execute_upload,
    execute_verify,
    generate_canonical_id,
    generate_s3_key,
    guess_content_type,
    load_manifest,
    main,
    parse_cloudinary_url,
    save_manifest,
    scan_repository_for_urls,
    upload_to_s3,
    verify_cloudfront_object,
    verify_s3_object,
)


# ==============================================================================
# 1. URL Parsing & Key Generation Tests
# ==============================================================================


def test_parse_cloudinary_url_standard_system_design_lesson():
    """Verify parsing a standard system design lesson Cloudinary URL."""
    url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887006/"
        "interview-assistant/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    parsed = parse_cloudinary_url(
        url,
        bucket="interview-prep-assets-808431466075-ap-south-2",
        region="ap-south-2",
        cloudfront_base="https://d123456abcdef8.cloudfront.net",
    )

    assert parsed is not None
    assert parsed["original_url"] == url
    assert parsed["source_cloud"] == "asdf12235464"
    assert parsed["canonical_id"] == "interview-assistant/system-design/02/figure-1-1-WCFZBBLA"
    assert parsed["s3_key"] == "system-design/02/figure-1-1-WCFZBBLA.png"
    assert (
        parsed["s3_url"]
        == "https://interview-prep-assets-808431466075-ap-south-2.s3.ap-south-2.amazonaws.com/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    assert (
        parsed["cloudfront_url"]
        == "https://d123456abcdef8.cloudfront.net/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    assert parsed["content_type"] == "image/png"
    assert parsed["byte_count"] == 0
    assert parsed["sha256"] == ""
    assert parsed["status"] == "pending"
    assert parsed["error"] is None


def test_parse_cloudinary_url_svg_and_webp_content_types():
    """Verify correct MIME detection for SVG and WebP assets."""
    svg_url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887031/"
        "interview-assistant/system-design/02/figure-1-5-TJLQVE5N.svg"
    )
    webp_url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887029/"
        "interview-assistant/system-design/02/figure-1-4-2EGRRANZ.webp"
    )

    parsed_svg = parse_cloudinary_url(svg_url)
    assert parsed_svg is not None
    assert parsed_svg["content_type"] == "image/svg+xml"
    assert parsed_svg["s3_key"].endswith(".svg")

    parsed_webp = parse_cloudinary_url(webp_url)
    assert parsed_webp is not None
    assert parsed_webp["content_type"] == "image/webp"
    assert parsed_webp["s3_key"].endswith(".webp")


def test_parse_cloudinary_url_without_version_tag():
    """Verify URLs without version tag (v\\d+/) parse correctly."""
    url = "https://res.cloudinary.com/asdf12235464/image/upload/interview-assistant/system-design/05/diagram.png"
    parsed = parse_cloudinary_url(url)
    assert parsed is not None
    assert parsed["s3_key"] == "system-design/05/diagram.png"
    assert parsed["canonical_id"] == "interview-assistant/system-design/05/diagram"


def test_parse_cloudinary_url_with_transformations():
    """Verify URLs with image transformations parse cleanly."""
    url = "https://res.cloudinary.com/asdf12235464/image/upload/c_scale,w_500/v123456/interview-assistant/system-design/03/chart.jpg"
    parsed = parse_cloudinary_url(url)
    assert parsed is not None
    assert parsed["s3_key"] == "system-design/03/chart.jpg"


def test_parse_cloudinary_url_avatars_and_other_static():
    """Verify avatar and generic static path mappings."""
    avatar_url = "https://res.cloudinary.com/asdf12235464/image/upload/v1/interview-assistant/avatars/user123/profile.png"
    parsed_avatar = parse_cloudinary_url(avatar_url)
    assert parsed_avatar is not None
    assert parsed_avatar["s3_key"] == "avatars/user123/profile.png"

    general_url = "https://res.cloudinary.com/asdf12235464/image/upload/v1/interview-assistant/marketing/banner.jpg"
    parsed_general = parse_cloudinary_url(general_url)
    assert parsed_general is not None
    assert parsed_general["s3_key"] == "static/marketing/banner.jpg"


def test_parse_cloudinary_url_invalid():
    """Verify non-Cloudinary or malformed URLs return None."""
    assert parse_cloudinary_url("https://example.com/image.png") is None
    assert parse_cloudinary_url("not-a-url") is None
    assert parse_cloudinary_url("") is None


def test_generate_canonical_id():
    """Verify stripping of extensions and query parameters for canonical IDs."""
    assert generate_canonical_id("interview-assistant/system-design/02/fig.png") == "interview-assistant/system-design/02/fig"
    assert generate_canonical_id("interview-assistant/system-design/02/fig.png?v=123") == "interview-assistant/system-design/02/fig"
    assert generate_canonical_id("avatars/u1/pic") == "avatars/u1/pic"


def test_generate_s3_key():
    """Verify contract naming conventions for S3 keys."""
    assert generate_s3_key("interview-assistant/system-design/02/fig.png") == "system-design/02/fig.png"
    assert generate_s3_key("interview-assistant/avatars/u1/pic.png") == "avatars/u1/pic.png"
    assert generate_s3_key("interview-assistant/branding/logo.svg") == "static/branding/logo.svg"
    assert generate_s3_key("system-design/05/fig.png") == "system-design/05/fig.png"
    assert generate_s3_key("custom/asset.png") == "static/custom/asset.png"


def test_guess_content_type():
    """Verify MIME type fallback and resolution."""
    assert guess_content_type("test.png") == "image/png"
    assert guess_content_type("test.svg") == "image/svg+xml"
    assert guess_content_type("test.webp") == "image/webp"
    assert guess_content_type("test.unknown_ext") == "application/octet-stream"


# ==============================================================================
# 2. Manifest Schema & Serialization Tests
# ==============================================================================


def test_manifest_entry_to_and_from_dict():
    """Verify ManifestEntry serializes and deserializes conforming to schema."""
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/cloud/image/upload/v1/test.png",
        source_cloud="cloud",
        canonical_id="test",
        s3_key="static/test.png",
        s3_url="https://bucket.s3.ap-south-2.amazonaws.com/static/test.png",
        cloudfront_url="https://cf.domain.net/static/test.png",
        content_type="image/png",
        byte_count=1234,
        sha256="abc123sha256",
        source_files=["frontend/page.html"],
        status="uploaded",
        error=None,
    )

    data = entry.to_dict()
    # Validate required schema keys
    required_keys = {
        "original_url",
        "source_cloud",
        "canonical_id",
        "s3_key",
        "s3_url",
        "cloudfront_url",
        "content_type",
        "byte_count",
        "sha256",
        "source_files",
        "status",
        "error",
    }
    assert set(data.keys()) == required_keys

    # Roundtrip from dict
    restored = ManifestEntry.from_dict(data)
    assert restored.original_url == entry.original_url
    assert restored.byte_count == 1234
    assert restored.status == "uploaded"
    assert restored.source_files == ["frontend/page.html"]


def test_save_and_load_manifest_roundtrip(tmp_path):
    """Verify saving to JSON file and loading back preserves all data."""
    manifest_file = tmp_path / "docs" / "migrations" / "migration-manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/cloud/image/upload/v1/test.png",
        source_cloud="cloud",
        canonical_id="test",
        s3_key="static/test.png",
        s3_url="https://bucket.s3.ap-south-2.amazonaws.com/static/test.png",
        cloudfront_url="https://cf.domain.net/static/test.png",
        content_type="image/png",
        byte_count=100,
        sha256="deadbeef",
        source_files=["a.html", "b.md"],
        status="verified",
        error=None,
    )

    save_manifest(manifest_file, [entry])
    assert manifest_file.exists()

    loaded = load_manifest(manifest_file)
    assert len(loaded) == 1
    assert loaded[0].original_url == entry.original_url
    assert loaded[0].status == "verified"
    assert loaded[0].source_files == ["a.html", "b.md"]


def test_load_manifest_missing_or_empty(tmp_path):
    """Verify loading non-existent or empty manifest returns empty list."""
    missing = tmp_path / "missing.json"
    assert load_manifest(missing) == []

    empty = tmp_path / "empty.json"
    empty.write_text("   \n", encoding="utf-8")
    assert load_manifest(empty) == []


def test_load_manifest_with_dict_wrapper(tmp_path):
    """Verify loading manifest wrapped in {'entries': [...]} or {'assets': [...]}}."""
    manifest_file = tmp_path / "wrapped.json"
    content = {
        "entries": [
            {
                "original_url": "https://res.cloudinary.com/c/image/upload/v1/a.png",
                "source_cloud": "c",
                "canonical_id": "a",
                "s3_key": "static/a.png",
                "s3_url": "https://s3/a.png",
                "cloudfront_url": "https://cf/a.png",
                "content_type": "image/png",
                "byte_count": 0,
                "sha256": "",
                "source_files": ["f.html"],
                "status": "pending",
                "error": None,
            }
        ]
    }
    manifest_file.write_text(json.dumps(content), encoding="utf-8")
    loaded = load_manifest(manifest_file)
    assert len(loaded) == 1
    assert loaded[0].s3_key == "static/a.png"


# ==============================================================================
# 3. Repository Scanning & Resumable Inventory Tests
# ==============================================================================


def test_scan_repository_for_urls(tmp_path):
    """Verify scanning correctly identifies Cloudinary URLs and respects exclusions."""
    # Create test files
    html_file = tmp_path / "page.html"
    html_file.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png"/>\n'
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png"/>',  # Duplicate in same file
        encoding="utf-8",
    )

    md_file = tmp_path / "docs" / "guide.md"
    md_file.parent.mkdir(parents=True)
    md_file.write_text(
        '![img](https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png)\n'
        '![img2](https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/02/other.svg)',
        encoding="utf-8",
    )

    # Ignored directory file
    ignored_file = tmp_path / ".venv" / "lib.html"
    ignored_file.parent.mkdir(parents=True)
    ignored_file.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/03/ignore.png"/>',
        encoding="utf-8",
    )

    # Ignored extension file (.py)
    py_file = tmp_path / "script.py"
    py_file.write_text(
        'url = "https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/04/ignore.png"',
        encoding="utf-8",
    )

    found = scan_repository_for_urls(repo_root=tmp_path)
    url1 = "https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png"
    url2 = "https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/02/other.svg"

    assert url1 in found
    assert url2 in found
    assert len(found) == 2  # Ignored files not included

    # url1 appears in page.html and docs/guide.md
    assert found[url1] == ["docs/guide.md", "page.html"]
    # url2 appears only in docs/guide.md
    assert found[url2] == ["docs/guide.md"]


def test_build_or_update_manifest_resumability(tmp_path):
    """Verify that re-running inventory preserves existing progress (status, byte_count, sha256)."""
    manifest_file = tmp_path / "migration-manifest.json"
    html_file = tmp_path / "index.html"
    url = "https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png"
    html_file.write_text(f'<img src="{url}"/>', encoding="utf-8")

    # Initial inventory
    entries, stats = build_or_update_manifest(
        repo_root=tmp_path, manifest_path=manifest_file
    )
    assert len(entries) == 1
    assert stats["added"] == 1
    assert entries[0].status == "pending"

    # Simulate that asset was uploaded and verified in a previous run
    entries[0].status = "verified"
    entries[0].byte_count = 4242
    entries[0].sha256 = "verified_hash"
    save_manifest(manifest_file, entries)

    # Re-run inventory
    entries_after, stats_after = build_or_update_manifest(
        repo_root=tmp_path, manifest_path=manifest_file
    )
    assert len(entries_after) == 1
    assert stats_after["added"] == 0
    assert stats_after["unchanged"] == 1
    # Status and metrics MUST be preserved
    assert entries_after[0].status == "verified"
    assert entries_after[0].byte_count == 4242
    assert entries_after[0].sha256 == "verified_hash"


# ==============================================================================
# 4. Download & S3 Upload Logic Tests
# ==============================================================================


def test_download_asset_success():
    """Verify download computes SHA256 and retrieves content."""
    dummy_data = b"image-binary-data"
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = dummy_data
    mock_resp.headers.get.return_value = "image/png"

    with patch("urllib.request.urlopen", return_value=mock_resp):
        data, sha256, ctype = download_asset("https://res.cloudinary.com/c/image/upload/v1/test.png")
        assert data == dummy_data
        assert ctype == "image/png"
        import hashlib
        assert sha256 == hashlib.sha256(dummy_data).hexdigest()


def test_download_asset_retry_then_success():
    """Verify download retries on transient errors with exponential backoff."""
    dummy_data = b"ok-after-retry"
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.read.return_value = dummy_data
    mock_resp.headers.get.return_value = "image/svg+xml"

    # First attempt fails with network error, second attempt succeeds
    with patch(
        "urllib.request.urlopen",
        side_effect=[urllib.error.URLError("Connection reset"), mock_resp],
    ), patch("time.sleep") as mock_sleep:
        data, sha256, ctype = download_asset(
            "https://res.cloudinary.com/c/image/upload/v1/test.svg", max_retries=2
        )
        assert data == dummy_data
        assert ctype == "image/svg+xml"
        assert mock_sleep.call_count == 1


def test_download_asset_all_retries_fail():
    """Verify download raises RuntimeError when all retries are exhausted."""
    with patch(
        "urllib.request.urlopen", side_effect=urllib.error.URLError("Server unreachable")
    ), patch("time.sleep"):
        with pytest.raises(RuntimeError, match="Failed to download"):
            download_asset("https://res.cloudinary.com/c/image/upload/v1/fail.png", max_retries=2)


def test_upload_to_s3_calls_put_object():
    """Verify upload_to_s3 calls boto3 put_object with correct headers and metadata."""
    mock_s3 = MagicMock()
    upload_to_s3(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="system-design/01/fig.png",
        data=b"image-bytes",
        content_type="image/png",
        sha256="sample-sha256",
    )

    mock_s3.put_object.assert_called_once_with(
        Bucket="my-bucket",
        Key="system-design/01/fig.png",
        Body=b"image-bytes",
        ContentType="image/png",
        Metadata={"sha256": "sample-sha256", "migrated-from": "cloudinary"},
    )


def test_execute_upload_updates_manifest(tmp_path):
    """Verify execute_upload downloads assets, uploads to S3, and updates manifest status."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="system-design/01/test.png",
        s3_url="https://s3/system-design/01/test.png",
        cloudfront_url="https://cf/system-design/01/test.png",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    mock_s3 = MagicMock()
    dummy_data = b"downloaded-payload"

    with patch(
        "migrate_cloudinary_to_s3.download_asset",
        return_value=(dummy_data, "hash123", "image/png"),
    ):
        code = execute_upload(
            manifest_path=manifest_file,
            bucket="my-bucket",
            s3_client=mock_s3,
            dry_run=False,
        )
        assert code == 0
        mock_s3.put_object.assert_called_once()

    updated = load_manifest(manifest_file)
    assert updated[0].status == "uploaded"
    assert updated[0].byte_count == len(dummy_data)
    assert updated[0].sha256 == "hash123"
    assert updated[0].error is None


def test_execute_upload_dry_run_does_not_mutate(tmp_path):
    """Verify dry-run upload does not perform download or S3 calls and keeps manifest intact."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="system-design/01/test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="https://cf/test.png",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    with patch("migrate_cloudinary_to_s3.download_asset") as mock_dl:
        code = execute_upload(
            manifest_path=manifest_file,
            bucket="my-bucket",
            dry_run=True,
        )
        assert code == 0
        mock_dl.assert_not_called()

    # Manifest remains pending
    updated = load_manifest(manifest_file)
    assert updated[0].status == "pending"


# ==============================================================================
# 5. Verification Logic Tests
# ==============================================================================


def test_verify_s3_object_success():
    """Verify S3 HeadObject matching size and content-type."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 500,
        "ContentType": "image/png",
    }

    is_valid, err, details = verify_s3_object(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
        expected_size=500,
    )
    assert is_valid is True
    assert err is None
    assert details["ContentLength"] == 500


def test_verify_s3_object_size_mismatch():
    """Verify S3 HeadObject flags byte size mismatch."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 400,
        "ContentType": "image/png",
    }

    is_valid, err, details = verify_s3_object(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
        expected_size=500,
    )
    assert is_valid is False
    assert "Size mismatch" in err


def test_verify_s3_object_not_found():
    """Verify S3 HeadObject failure handling when object does not exist."""
    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = Exception("404 NoSuchKey")

    is_valid, err, details = verify_s3_object(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
    )
    assert is_valid is False
    assert "HeadObject failed" in err


def test_verify_cloudfront_object():
    """Verify HTTP HEAD check on CloudFront endpoint."""
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.status = 200

    with patch("urllib.request.urlopen", return_value=mock_resp):
        valid, err = verify_cloudfront_object("https://d123.cloudfront.net/test.png")
        assert valid is True
        assert err is None


def test_execute_verify_marks_entries_verified(tmp_path):
    """Verify execute_verify promotes 'uploaded' entries to 'verified'."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="https://cf/test.png",
        content_type="image/png",
        byte_count=100,
        sha256="abc",
        source_files=["a.html"],
        status="uploaded",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {"ContentLength": 100, "ContentType": "image/png"}

    code = execute_verify(
        manifest_path=manifest_file,
        bucket="my-bucket",
        s3_client=mock_s3,
        dry_run=False,
    )
    assert code == 0

    updated = load_manifest(manifest_file)
    assert updated[0].status == "verified"
    assert updated[0].error is None


# ==============================================================================
# 6. HTML Rewriting Safety & Attribute Preservation Tests
# ==============================================================================


def test_execute_rewrite_only_rewrites_verified_entries(tmp_path):
    """CRITICAL SAFETY TEST: Only entries with status='verified' can be rewritten."""
    manifest_file = tmp_path / "manifest.json"
    html_file = tmp_path / "lesson.html"

    url_verified = "https://res.cloudinary.com/c/image/upload/v1/verified.png"
    url_pending = "https://res.cloudinary.com/c/image/upload/v1/pending.png"

    html_file.write_text(
        f'<img src="{url_verified}"/>\n<img src="{url_pending}"/>',
        encoding="utf-8",
    )

    entry_verified = ManifestEntry(
        original_url=url_verified,
        source_cloud="c",
        canonical_id="verified",
        s3_key="system-design/01/verified.png",
        s3_url="https://bucket.s3.ap-south-2.amazonaws.com/system-design/01/verified.png",
        cloudfront_url="https://cf.domain.net/system-design/01/verified.png",
        content_type="image/png",
        byte_count=100,
        sha256="h1",
        source_files=["lesson.html"],
        status="verified",
        error=None,
    )

    entry_pending = ManifestEntry(
        original_url=url_pending,
        source_cloud="c",
        canonical_id="pending",
        s3_key="system-design/01/pending.png",
        s3_url="https://bucket.s3.ap-south-2.amazonaws.com/system-design/01/pending.png",
        cloudfront_url="https://cf.domain.net/system-design/01/pending.png",
        content_type="image/png",
        byte_count=100,
        sha256="h2",
        source_files=["lesson.html"],
        status="pending",
        error=None,
    )

    save_manifest(manifest_file, [entry_verified, entry_pending])

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        target_url_type="cloudfront",
        dry_run=False,
    )
    assert code == 0

    rewritten_content = html_file.read_text(encoding="utf-8")
    # Verified URL MUST be replaced with CloudFront URL
    assert "https://cf.domain.net/system-design/01/verified.png" in rewritten_content
    assert url_verified not in rewritten_content

    # Pending URL MUST NOT be replaced
    assert url_pending in rewritten_content


def test_execute_rewrite_preserves_html_structure_captions_and_attributes(tmp_path):
    """Verify that exact HTML attributes, layout, formatting, and captions are 100% preserved."""
    manifest_file = tmp_path / "manifest.json"
    html_file = tmp_path / "step-02.html"

    original_url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887006/"
        "interview-assistant/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    cf_url = "https://d123456abcdef8.cloudfront.net/system-design/02/figure-1-1-WCFZBBLA.png"

    original_snippet = (
        '<figure class="py-1">'
        '<div style="display: flex; justify-content: center;">'
        f'<img alt="Image with special \'quotes\' & symbols" data-nimg="1" decoding="async" '
        f'height="292" src="{original_url}" style="color: transparent;" width="500"/>'
        '</div>'
        '<div style="display: flex; justify-content: center;">'
        '<figcaption class="py-1">Figure 1: Client-Server Architecture</figcaption>'
        '</div>'
        '</figure>'
    )

    html_file.write_text(original_snippet, encoding="utf-8")

    entry = ManifestEntry(
        original_url=original_url,
        source_cloud="asdf12235464",
        canonical_id="interview-assistant/system-design/02/figure-1-1-WCFZBBLA",
        s3_key="system-design/02/figure-1-1-WCFZBBLA.png",
        s3_url="https://s3/system-design/02/figure-1-1-WCFZBBLA.png",
        cloudfront_url=cf_url,
        content_type="image/png",
        byte_count=26972,
        sha256="abc",
        source_files=["step-02.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        target_url_type="cloudfront",
        dry_run=False,
    )
    assert code == 0

    rewritten_content = html_file.read_text(encoding="utf-8")

    expected_snippet = original_snippet.replace(original_url, cf_url)
    assert rewritten_content == expected_snippet
    # All attributes preserved
    assert 'alt="Image with special \'quotes\' & symbols"' in rewritten_content
    assert 'data-nimg="1"' in rewritten_content
    assert 'decoding="async"' in rewritten_content
    assert 'height="292"' in rewritten_content
    assert 'style="color: transparent;"' in rewritten_content
    assert 'width="500"' in rewritten_content
    assert '<figcaption class="py-1">Figure 1: Client-Server Architecture</figcaption>' in rewritten_content


def test_execute_rewrite_dry_run_leaves_file_untouched(tmp_path):
    """Verify dry run does not modify files on disk."""
    manifest_file = tmp_path / "manifest.json"
    html_file = tmp_path / "lesson.html"
    url = "https://res.cloudinary.com/c/image/upload/v1/verified.png"
    initial_content = f'<img src="{url}"/>'
    html_file.write_text(initial_content, encoding="utf-8")

    entry = ManifestEntry(
        original_url=url,
        source_cloud="c",
        canonical_id="verified",
        s3_key="test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="https://cf/test.png",
        content_type="image/png",
        byte_count=10,
        sha256="abc",
        source_files=["lesson.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        dry_run=True,
    )
    assert code == 0
    assert html_file.read_text(encoding="utf-8") == initial_content


# ==============================================================================
# 7. Reconciliation Tests
# ==============================================================================


def test_execute_reconcile_clean(tmp_path):
    """Verify clean reconciliation exit code 0 when all references are migrated and verified."""
    manifest_file = tmp_path / "docs" / "migrations" / "migration-manifest.json"
    manifest_file.parent.mkdir(parents=True)

    # HTML contains migrated CloudFront URL
    html_file = tmp_path / "step.html"
    html_file.write_text('<img src="https://cf.domain.net/fig.png"/>', encoding="utf-8")

    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://cf.domain.net/fig.png",
        content_type="image/png",
        byte_count=100,
        sha256="abc",
        source_files=["step.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 0


def test_execute_reconcile_unreconciled_references_returns_1(tmp_path):
    """Verify reconcile returns exit code 1 when Cloudinary references remain in files."""
    manifest_file = tmp_path / "migration-manifest.json"
    url = "https://res.cloudinary.com/c/image/upload/v1/fig.png"

    html_file = tmp_path / "step.html"
    html_file.write_text(f'<img src="{url}"/>', encoding="utf-8")

    entry = ManifestEntry(
        original_url=url,
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://cf/fig.png",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["step.html"],
        status="pending",
        error=None,
    )
    save_manifest(manifest_file, [entry])

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 1


def test_execute_reconcile_failed_manifest_entry_returns_1(tmp_path):
    """Verify reconcile returns exit code 1 if any manifest entry is marked 'failed'."""
    manifest_file = tmp_path / "migration-manifest.json"
    html_file = tmp_path / "step.html"
    html_file.write_text('<p>No urls</p>', encoding="utf-8")

    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://cf/fig.png",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["step.html"],
        status="failed",
        error="S3 upload failed",
    )
    save_manifest(manifest_file, [entry])

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 1


# ==============================================================================
# 8. CLI Interface & Pipeline Orchestration Tests
# ==============================================================================


def test_main_cli_inventory(tmp_path):
    """Verify running CLI with --inventory builds manifest."""
    html_file = tmp_path / "test.html"
    html_file.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/a.png"/>',
        encoding="utf-8",
    )
    manifest_file = tmp_path / "manifest.json"

    exit_code = main([
        "--inventory",
        "--repo-root", str(tmp_path),
        "--manifest", str(manifest_file),
    ])
    assert exit_code == 0
    assert manifest_file.exists()

    entries = load_manifest(manifest_file)
    assert len(entries) == 1
    assert entries[0].s3_key == "system-design/01/a.png"


def test_main_cli_no_args_shows_help(capsys):
    """Verify running CLI with no operations prints help and exits 0."""
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out or "usage:" in captured.err or "Migrate static assets" in captured.out
