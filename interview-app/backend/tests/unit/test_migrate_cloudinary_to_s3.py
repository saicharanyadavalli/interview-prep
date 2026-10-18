"""Unit tests for Cloudinary to S3 + CloudFront migration utility (scripts/migrate_cloudinary_to_s3.py).

Verifies:
- Rejection of fictitious, empty, and invalid CloudFront URLs.
- Validation of HTTPS base URLs (production FQDN vs test mode).
- Safe URL parsing, Cloudinary canonical ID generation, and S3 key generation rules.
- Separate inventory scopes (static asset vs runtime dependency vs documentation).
- Manifest schema validation, load/save, and incremental update resumability.
- Strict dry-run zero mutation guarantees across files, manifests, and AWS resources.
- Download and idempotent S3 upload logic with SHA-256 integrity and key collision detection.
- Verification logic via S3 HeadObject (size, content-type, SHA-256) and CloudFront checks.
- HTML rewriting safety rules (ONLY verified assets rewritten, all structure/attributes preserved).
- Post-rewrite reconciliation audit scopes, reporting, and gate exit codes.
- CLI argument parsing, flags (--test-mode, --audit-scope), and pipeline orchestration.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
scripts_dir = backend_dir.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from migrate_cloudinary_to_s3 import (
    ManifestEntry,
    ScopedAuditInventory,
    build_or_update_manifest,
    check_s3_collision_or_existing,
    classify_file_scope,
    detect_manifest_key_collisions,
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
    run_scoped_audit,
    save_manifest,
    scan_repository_for_urls,
    scan_runtime_dependencies,
    upload_to_s3,
    validate_asset_base_url,
    verify_cloudfront_object,
    verify_s3_object,
)


# ==============================================================================
# 1. CloudFront Base URL Validation & Safety Tests
# ==============================================================================


def test_validate_asset_base_url_rejects_empty_or_none():
    """Verify empty, None, or whitespace-only base URLs are rejected."""
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_asset_base_url(None)
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_asset_base_url("")
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_asset_base_url("   ")


def test_validate_asset_base_url_rejects_fictitious_host():
    """Verify fictitious default hostname https://d123456abcdef8.cloudfront.net is strictly rejected."""
    with pytest.raises(ValueError, match="forbidden placeholder token"):
        validate_asset_base_url("https://d123456abcdef8.cloudfront.net", test_mode=False)
    with pytest.raises(ValueError, match="forbidden placeholder token"):
        validate_asset_base_url("https://d123456abcdef8.cloudfront.net", test_mode=True)


def test_validate_asset_base_url_rejects_placeholder_tokens():
    """Verify template and placeholder tokens are rejected."""
    placeholders = [
        "https://<distribution-id>.cloudfront.net",
        "https://<your-distribution-id>.cloudfront.net",
        "https://${ASSET_BASE_URL}",
        "https://${asset_base_url}.cloudfront.net",
        "https://distribution-id.net",
    ]
    for p in placeholders:
        with pytest.raises(ValueError, match="placeholder"):
            validate_asset_base_url(p, test_mode=False)


def test_validate_asset_base_url_rejects_http_and_invalid_schemes():
    """Verify non-HTTPS schemes are rejected."""
    with pytest.raises(ValueError, match="must start with 'https://'"):
        validate_asset_base_url("http://d3staging123.cloudfront.net")
    with pytest.raises(ValueError, match="must start with 'https://'"):
        validate_asset_base_url("ftp://d3staging123.cloudfront.net")
    with pytest.raises(ValueError, match="must start with 'https://'"):
        validate_asset_base_url("d3staging123.cloudfront.net")


def test_validate_asset_base_url_rejects_subpaths():
    """Verify origin base URLs containing subpaths are rejected."""
    with pytest.raises(ValueError, match="must be an origin base without subpaths"):
        validate_asset_base_url("https://d3staging123.cloudfront.net/static")
    with pytest.raises(ValueError, match="must be an origin base without subpaths"):
        validate_asset_base_url("https://d3staging123.cloudfront.net/v1/")


def test_validate_asset_base_url_rejects_test_domain_in_production_mode():
    """Verify generic test/example domains are rejected when not in test mode."""
    with pytest.raises(ValueError, match="test/mock domain"):
        validate_asset_base_url("https://example.com", test_mode=False)
    with pytest.raises(ValueError, match="test/mock domain"):
        validate_asset_base_url("https://localhost:8000", test_mode=False)


def test_validate_asset_base_url_valid_production():
    """Verify valid CloudFront staging/production distribution URLs pass validation."""
    valid_url = "https://d3stagingassets123.cloudfront.net"
    assert validate_asset_base_url(valid_url, test_mode=False) == valid_url
    assert validate_asset_base_url(valid_url + "/", test_mode=False) == valid_url

    custom_cdn = "https://cdn.interviewprep.example-internal.com"
    # Valid FQDN in non-test mode
    valid_prod = "https://cdn.interviewprep-app.com"
    assert validate_asset_base_url(valid_prod, test_mode=False) == valid_prod


def test_validate_asset_base_url_test_mode_permits_test_hostnames():
    """Verify test mode allows test hostnames like cf.domain.net or test-cdn.example.com."""
    assert validate_asset_base_url("https://cf.domain.net", test_mode=True) == "https://cf.domain.net"
    assert (
        validate_asset_base_url("https://test-cdn.example.com", test_mode=True)
        == "https://test-cdn.example.com"
    )


# ==============================================================================
# 2. URL Parsing & Key Generation Tests
# ==============================================================================


def test_parse_cloudinary_url_requires_valid_base_url():
    """Verify parse_cloudinary_url requires a valid HTTPS base URL before generating URLs."""
    url = "https://res.cloudinary.com/asdf12235464/image/upload/v1/test.png"
    # When no base URL is configured
    with patch.dict(os.environ, {"ASSET_BASE_URL": ""}):
        with pytest.raises(ValueError, match="ASSET_BASE_URL.*required"):
            parse_cloudinary_url(url, cloudfront_base="")

    # When fictitious URL is provided
    with pytest.raises(ValueError, match="forbidden placeholder token"):
        parse_cloudinary_url(url, cloudfront_base="https://d123456abcdef8.cloudfront.net")


def test_parse_cloudinary_url_standard_system_design_lesson():
    """Verify parsing a standard system design lesson Cloudinary URL with valid CloudFront base."""
    url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887006/"
        "interview-assistant/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    parsed = parse_cloudinary_url(
        url,
        bucket="interview-prep-assets-808431466075-staging-ap-south-2",
        region="ap-south-2",
        cloudfront_base="https://d3staging123.cloudfront.net",
    )

    assert parsed is not None
    assert parsed["original_url"] == url
    assert parsed["source_cloud"] == "asdf12235464"
    assert parsed["canonical_id"] == "interview-assistant/system-design/02/figure-1-1-WCFZBBLA"
    assert parsed["s3_key"] == "system-design/02/figure-1-1-WCFZBBLA.png"
    assert (
        parsed["s3_url"]
        == "https://interview-prep-assets-808431466075-staging-ap-south-2.s3.ap-south-2.amazonaws.com/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    assert (
        parsed["cloudfront_url"]
        == "https://d3staging123.cloudfront.net/system-design/02/figure-1-1-WCFZBBLA.png"
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
    cf_base = "https://d3staging123.cloudfront.net"

    parsed_svg = parse_cloudinary_url(svg_url, cloudfront_base=cf_base)
    assert parsed_svg is not None
    assert parsed_svg["content_type"] == "image/svg+xml"
    assert parsed_svg["s3_key"].endswith(".svg")

    parsed_webp = parse_cloudinary_url(webp_url, cloudfront_base=cf_base)
    assert parsed_webp is not None
    assert parsed_webp["content_type"] == "image/webp"
    assert parsed_webp["s3_key"].endswith(".webp")


def test_parse_cloudinary_url_without_version_tag():
    """Verify URLs without version tag (v\\d+/) parse correctly."""
    url = "https://res.cloudinary.com/asdf12235464/image/upload/interview-assistant/system-design/05/diagram.png"
    parsed = parse_cloudinary_url(url, cloudfront_base="https://d3staging123.cloudfront.net")
    assert parsed is not None
    assert parsed["s3_key"] == "system-design/05/diagram.png"
    assert parsed["canonical_id"] == "interview-assistant/system-design/05/diagram"


def test_parse_cloudinary_url_with_transformations():
    """Verify URLs with image transformations parse cleanly."""
    url = "https://res.cloudinary.com/asdf12235464/image/upload/c_scale,w_500/v123456/interview-assistant/system-design/03/chart.jpg"
    parsed = parse_cloudinary_url(url, cloudfront_base="https://d3staging123.cloudfront.net")
    assert parsed is not None
    assert parsed["s3_key"] == "system-design/03/chart.jpg"


def test_parse_cloudinary_url_avatars_and_other_static():
    """Verify avatar and generic static path mappings."""
    cf_base = "https://d3staging123.cloudfront.net"
    avatar_url = "https://res.cloudinary.com/asdf12235464/image/upload/v1/interview-assistant/avatars/user123/profile.png"
    parsed_avatar = parse_cloudinary_url(avatar_url, cloudfront_base=cf_base)
    assert parsed_avatar is not None
    assert parsed_avatar["s3_key"] == "avatars/user123/profile.png"

    general_url = "https://res.cloudinary.com/asdf12235464/image/upload/v1/interview-assistant/marketing/banner.jpg"
    parsed_general = parse_cloudinary_url(general_url, cloudfront_base=cf_base)
    assert parsed_general is not None
    assert parsed_general["s3_key"] == "static/marketing/banner.jpg"


def test_parse_cloudinary_url_invalid():
    """Verify non-Cloudinary or malformed URLs return None."""
    cf_base = "https://d3staging123.cloudfront.net"
    assert parse_cloudinary_url("https://example.com/image.png", cloudfront_base=cf_base) is None
    assert parse_cloudinary_url("not-a-url", cloudfront_base=cf_base) is None
    assert parse_cloudinary_url("", cloudfront_base=cf_base) is None


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
# 3. Audit Scopes (Static vs Runtime vs Documentation) Tests
# ==============================================================================


def test_classify_file_scope():
    """Verify file classification into static, docs, and runtime scopes."""
    assert classify_file_scope("frontend/system-design/lessons/step-02.html") == "static"
    assert classify_file_scope("frontend/system-design/lessons/step-29.html") == "static"
    assert classify_file_scope("static/branding/logo.png") == "static"

    assert classify_file_scope("docs/migrations/migration-contracts.md") == "docs"
    assert classify_file_scope("docs/architecture.md") == "docs"
    assert classify_file_scope("DEPLOYMENT.md") == "docs"
    assert classify_file_scope("README.md") == "docs"

    assert classify_file_scope("backend/routes/profile.py") == "runtime"
    assert classify_file_scope("backend/requirements.txt") == "runtime"
    assert classify_file_scope("docker-compose.yml") == "runtime"
    assert classify_file_scope("backend/tests/unit/test_api.py") == "runtime"


def test_scan_repository_isolated_scopes(tmp_path):
    """Verify repository scanning separates static, documentation, and all scopes."""
    lesson_html = tmp_path / "frontend" / "system-design" / "lessons" / "step-01.html"
    lesson_html.parent.mkdir(parents=True)
    url_static = "https://res.cloudinary.com/cloud/image/upload/v1/system-design/01/fig.png"
    lesson_html.write_text(f'<img src="{url_static}"/>', encoding="utf-8")

    doc_file = tmp_path / "docs" / "guide.md"
    doc_file.parent.mkdir(parents=True)
    url_doc = "https://res.cloudinary.com/cloud/image/upload/v1/example-diagram.png"
    doc_file.write_text(f'Example: ![img]({url_doc})', encoding="utf-8")

    # 1. Scan static only
    static_results = scan_repository_for_urls(repo_root=tmp_path, scope="static")
    assert url_static in static_results
    assert url_doc not in static_results

    # 2. Scan docs only
    docs_results = scan_repository_for_urls(repo_root=tmp_path, scope="docs")
    assert url_doc in docs_results
    assert url_static not in docs_results

    # 3. Scan all
    all_results = scan_repository_for_urls(repo_root=tmp_path, scope="all")
    assert url_static in all_results
    assert url_doc in all_results


def test_scan_runtime_dependencies_detects_sdk_and_env_vars(tmp_path):
    """Verify scan_runtime_dependencies identifies SDK imports, env vars, and packages."""
    # 1. Python file with SDK usage
    app_file = tmp_path / "backend" / "services" / "legacy.py"
    app_file.parent.mkdir(parents=True)
    app_file.write_text(
        "import cloudinary\n"
        "import cloudinary.uploader\n"
        "res = cloudinary.uploader.upload(file)\n",
        encoding="utf-8",
    )

    # 2. Requirements.txt with package dependency
    req_file = tmp_path / "backend" / "requirements.txt"
    req_file.write_text("fastapi==0.115.0\ncloudinary>=1.36.0\nboto3==1.34.0\n", encoding="utf-8")

    # 3. Docker Compose with env var
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        "services:\n"
        "  backend:\n"
        "    environment:\n"
        "      - CLOUDINARY_URL=cloudinary://123:abc@cloud\n",
        encoding="utf-8",
    )

    findings = scan_runtime_dependencies(repo_root=tmp_path)
    categories = {f["category"] for f in findings}

    assert "sdk_call" in categories
    assert "package_dependency" in categories
    assert "env_var" in categories

    pkg_items = [f for f in findings if f["category"] == "package_dependency"]
    assert any("cloudinary" in p["snippet"] for p in pkg_items)

    sdk_items = [f for f in findings if f["category"] == "sdk_call"]
    assert len(sdk_items) >= 2


def test_run_scoped_audit_structure(tmp_path):
    """Verify run_scoped_audit returns structured ScopedAuditInventory."""
    lesson = tmp_path / "frontend" / "system-design" / "lessons" / "step-01.html"
    lesson.parent.mkdir(parents=True)
    lesson.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/system-design/01/a.png"/>',
        encoding="utf-8",
    )

    audit = run_scoped_audit(repo_root=tmp_path)
    assert isinstance(audit, ScopedAuditInventory)
    assert len(audit.static_assets) == 1
    assert isinstance(audit.runtime_dependencies, list)
    assert isinstance(audit.documentation_assets, dict)


# ==============================================================================
# 4. Strict Dry-Run Zero Mutation Guarantees
# ==============================================================================


def test_save_manifest_dry_run_guard(tmp_path):
    """Verify save_manifest does not write to disk when dry_run=True."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
    )
    save_manifest(manifest_file, [entry], dry_run=True)
    assert not manifest_file.exists()


def test_dry_run_zero_mutation_inventory(tmp_path):
    """Verify execute_inventory with dry_run=True leaves filesystem untouched."""
    lesson = tmp_path / "frontend" / "system-design" / "lessons" / "step-01.html"
    lesson.parent.mkdir(parents=True)
    lesson.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/p.png"/>',
        encoding="utf-8",
    )
    manifest_file = tmp_path / "manifest.json"

    code = execute_inventory(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        bucket="test-bucket",
        region="ap-south-2",
        cloudfront_base="https://d3staging123.cloudfront.net",
        dry_run=True,
    )
    assert code == 0
    # Manifest MUST NOT be created in dry-run
    assert not manifest_file.exists()


def test_dry_run_zero_mutation_upload(tmp_path):
    """Verify execute_upload with dry_run=True makes zero network calls and manifest writes."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    with patch("migrate_cloudinary_to_s3.download_asset") as mock_dl:
        code = execute_upload(
            manifest_path=manifest_file,
            bucket="test-bucket",
            dry_run=True,
        )
        assert code == 0
        mock_dl.assert_not_called()

    # Manifest status must remain pending
    loaded = load_manifest(manifest_file)
    assert loaded[0].status == "pending"


def test_dry_run_zero_mutation_verify(tmp_path):
    """Verify execute_verify with dry_run=True does not call S3 HeadObject."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/test.png",
        source_cloud="c",
        canonical_id="test",
        s3_key="test.png",
        s3_url="https://s3/test.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=100,
        sha256="hash",
        source_files=["a.html"],
        status="uploaded",
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    mock_s3 = MagicMock()
    code = execute_verify(
        manifest_path=manifest_file,
        bucket="test-bucket",
        s3_client=mock_s3,
        dry_run=True,
    )
    assert code == 0
    mock_s3.head_object.assert_not_called()
    # Manifest status must remain uploaded
    loaded = load_manifest(manifest_file)
    assert loaded[0].status == "uploaded"


def test_dry_run_zero_mutation_rewrite(tmp_path):
    """Verify execute_rewrite with dry_run=True does not modify files on disk."""
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
        cloudfront_url="https://d3staging123.cloudfront.net/test.png",
        content_type="image/png",
        byte_count=10,
        sha256="abc",
        source_files=["lesson.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        dry_run=True,
    )
    assert code == 0
    assert html_file.read_text(encoding="utf-8") == initial_content


# ==============================================================================
# 5. Checksum Validation, Idempotency & Collision Detection Tests
# ==============================================================================


def test_detect_manifest_key_collisions():
    """Verify detect_manifest_key_collisions catches colliding S3 keys between distinct URLs."""
    e1 = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/a.png",
        source_cloud="c",
        canonical_id="a",
        s3_key="system-design/01/a.png",
        s3_url="https://s3/a.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["1.html"],
        status="pending",
    )
    e2 = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v2/other-path/system-design/01/a.png",
        source_cloud="c",
        canonical_id="other",
        s3_key="system-design/01/a.png",  # Same s3_key, different original_url
        s3_url="https://s3/a.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["2.html"],
        status="pending",
    )
    collisions = detect_manifest_key_collisions([e1, e2])
    assert len(collisions) == 1
    assert collisions[0][0] == "system-design/01/a.png"


def test_check_s3_collision_or_existing_not_found():
    """Verify when object does not exist in S3, collision check returns False without error."""
    mock_s3 = MagicMock()
    mock_s3.head_object.side_effect = Exception("404 NoSuchKey")

    exists, col_err, resp = check_s3_collision_or_existing(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
        data_sha256="abc123sha",
        data_size=500,
    )
    assert exists is False
    assert col_err is None
    assert resp is None


def test_check_s3_collision_idempotent_skip_on_matching_sha():
    """Verify when object exists with identical SHA-256, returns idempotent skip (no error)."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 500,
        "ContentType": "image/png",
        "Metadata": {"sha256": "abc123sha"},
    }

    exists, col_err, resp = check_s3_collision_or_existing(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
        data_sha256="abc123sha",
        data_size=500,
    )
    assert exists is True
    assert col_err is None  # Idempotent match, NOT a collision


def test_check_s3_collision_detected_on_differing_sha():
    """Verify when object exists with different SHA-256, collision error is raised."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 500,
        "ContentType": "image/png",
        "Metadata": {"sha256": "different_existing_hash"},
    }

    exists, col_err, resp = check_s3_collision_or_existing(
        s3_client=mock_s3,
        bucket="my-bucket",
        key="test.png",
        data_sha256="incoming_hash",
        data_size=500,
    )
    assert exists is True
    assert col_err is not None
    assert "Key collision detected" in col_err


def test_execute_upload_collision_marks_entry_failed(tmp_path):
    """Verify execute_upload marks entry failed and skips overwrite on key collision."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="system-design/01/fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    mock_s3 = MagicMock()
    # S3 returns an existing object with different hash
    mock_s3.head_object.return_value = {
        "ContentLength": 200,
        "Metadata": {"sha256": "existing_sha"},
    }

    dummy_data = b"new_data"
    with patch(
        "migrate_cloudinary_to_s3.download_asset",
        return_value=(dummy_data, "new_sha", "image/png"),
    ):
        code = execute_upload(
            manifest_path=manifest_file,
            bucket="my-bucket",
            s3_client=mock_s3,
            force=False,
        )
        assert code == 1  # Fails due to collision
        mock_s3.put_object.assert_not_called()  # PutObject NOT called

    updated = load_manifest(manifest_file)
    assert updated[0].status == "failed"
    assert "Key collision detected" in updated[0].error


def test_execute_upload_force_overwrites_collision(tmp_path):
    """Verify execute_upload with force=True overwrites on collision."""
    manifest_file = tmp_path / "manifest.json"
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="system-design/01/fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["a.html"],
        status="pending",
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 200,
        "Metadata": {"sha256": "existing_sha"},
    }

    dummy_data = b"new_data"
    with patch(
        "migrate_cloudinary_to_s3.download_asset",
        return_value=(dummy_data, "new_sha", "image/png"),
    ):
        code = execute_upload(
            manifest_path=manifest_file,
            bucket="my-bucket",
            s3_client=mock_s3,
            force=True,  # Force overwrite
        )
        assert code == 0
        mock_s3.put_object.assert_called_once()

    updated = load_manifest(manifest_file)
    assert updated[0].status == "uploaded"


def test_verify_s3_object_sha256_integrity_match_and_mismatch():
    """Verify verify_s3_object accurately reports SHA-256 verification and catches mismatches."""
    mock_s3 = MagicMock()
    mock_s3.head_object.return_value = {
        "ContentLength": 500,
        "ContentType": "image/png",
        "Metadata": {"sha256": "correct_hash"},
    }

    # 1. Matching SHA-256
    is_valid, err, details = verify_s3_object(
        s3_client=mock_s3,
        bucket="b",
        key="k",
        expected_size=500,
        expected_sha256="correct_hash",
    )
    assert is_valid is True
    assert details["sha256_verified"] is True

    # 2. Mismatched SHA-256
    is_valid_bad, err_bad, _ = verify_s3_object(
        s3_client=mock_s3,
        bucket="b",
        key="k",
        expected_size=500,
        expected_sha256="different_hash",
    )
    assert is_valid_bad is False
    assert "SHA-256 integrity mismatch" in err_bad


# ==============================================================================
# 6. Manifest Management & Roundtrip Tests
# ==============================================================================


def test_manifest_entry_to_and_from_dict():
    """Verify ManifestEntry serializes and deserializes conforming to schema."""
    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/cloud/image/upload/v1/test.png",
        source_cloud="cloud",
        canonical_id="test",
        s3_key="static/test.png",
        s3_url="https://bucket.s3.ap-south-2.amazonaws.com/static/test.png",
        cloudfront_url="https://d3staging123.cloudfront.net/static/test.png",
        content_type="image/png",
        byte_count=1234,
        sha256="abc123sha256",
        source_files=["frontend/page.html"],
        status="uploaded",
        error=None,
    )

    data = entry.to_dict()
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
        cloudfront_url="https://d3staging123.cloudfront.net/static/test.png",
        content_type="image/png",
        byte_count=100,
        sha256="deadbeef",
        source_files=["a.html", "b.md"],
        status="verified",
        error=None,
    )

    save_manifest(manifest_file, [entry], dry_run=False)
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
                "cloudfront_url": "https://d3staging123.cloudfront.net/a.png",
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


def test_build_or_update_manifest_resumability(tmp_path):
    """Verify that re-running inventory preserves existing progress (status, byte_count, sha256)."""
    manifest_file = tmp_path / "migration-manifest.json"
    html_file = tmp_path / "frontend" / "system-design" / "lessons" / "index.html"
    html_file.parent.mkdir(parents=True)
    url = "https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/pic.png"
    html_file.write_text(f'<img src="{url}"/>', encoding="utf-8")

    cf_base = "https://d3staging123.cloudfront.net"

    # Initial inventory
    entries, stats = build_or_update_manifest(
        repo_root=tmp_path, manifest_path=manifest_file, cloudfront_base=cf_base
    )
    assert len(entries) == 1
    assert stats["added"] == 1
    assert entries[0].status == "pending"

    # Simulate upload and verify
    entries[0].status = "verified"
    entries[0].byte_count = 4242
    entries[0].sha256 = "verified_hash"
    save_manifest(manifest_file, entries, dry_run=False)

    # Re-run inventory
    entries_after, stats_after = build_or_update_manifest(
        repo_root=tmp_path, manifest_path=manifest_file, cloudfront_base=cf_base
    )
    assert len(entries_after) == 1
    assert stats_after["added"] == 0
    assert stats_after["unchanged"] == 1
    assert entries_after[0].status == "verified"
    assert entries_after[0].byte_count == 4242
    assert entries_after[0].sha256 == "verified_hash"


# ==============================================================================
# 7. HTML Rewriting Safety & Attribute Preservation Tests
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
        cloudfront_url="https://d3staging123.cloudfront.net/system-design/01/verified.png",
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
        cloudfront_url="https://d3staging123.cloudfront.net/system-design/01/pending.png",
        content_type="image/png",
        byte_count=100,
        sha256="h2",
        source_files=["lesson.html"],
        status="pending",
        error=None,
    )

    save_manifest(manifest_file, [entry_verified, entry_pending], dry_run=False)

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        target_url_type="cloudfront",
        dry_run=False,
    )
    assert code == 0

    rewritten_content = html_file.read_text(encoding="utf-8")
    assert "https://d3staging123.cloudfront.net/system-design/01/verified.png" in rewritten_content
    assert url_verified not in rewritten_content
    assert url_pending in rewritten_content


def test_execute_rewrite_rejects_empty_or_placeholder_cloudfront_url(tmp_path):
    """Verify rewrite aborts if verified entry has empty or invalid CloudFront URL."""
    manifest_file = tmp_path / "manifest.json"
    html_file = tmp_path / "lesson.html"
    url = "https://res.cloudinary.com/c/image/upload/v1/pic.png"
    html_file.write_text(f'<img src="{url}"/>', encoding="utf-8")

    entry_empty = ManifestEntry(
        original_url=url,
        source_cloud="c",
        canonical_id="pic",
        s3_key="pic.png",
        s3_url="https://s3/pic.png",
        cloudfront_url="",  # Empty
        content_type="image/png",
        byte_count=100,
        sha256="h",
        source_files=["lesson.html"],
        status="verified",
    )
    save_manifest(manifest_file, [entry_empty], dry_run=False)

    code = execute_rewrite(
        repo_root=tmp_path,
        manifest_path=manifest_file,
        target_url_type="cloudfront",
        dry_run=False,
    )
    assert code == 1  # Aborts rewrite
    assert url in html_file.read_text(encoding="utf-8")  # Untouched


def test_execute_rewrite_preserves_html_structure_captions_and_attributes(tmp_path):
    """Verify that exact HTML attributes, layout, formatting, and captions are 100% preserved."""
    manifest_file = tmp_path / "manifest.json"
    html_file = tmp_path / "step-02.html"

    original_url = (
        "https://res.cloudinary.com/asdf12235464/image/upload/v1776887006/"
        "interview-assistant/system-design/02/figure-1-1-WCFZBBLA.png"
    )
    cf_url = "https://d3staging123.cloudfront.net/system-design/02/figure-1-1-WCFZBBLA.png"

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
    save_manifest(manifest_file, [entry], dry_run=False)

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
    assert 'alt="Image with special \'quotes\' & symbols"' in rewritten_content
    assert 'data-nimg="1"' in rewritten_content
    assert 'decoding="async"' in rewritten_content
    assert '<figcaption class="py-1">Figure 1: Client-Server Architecture</figcaption>' in rewritten_content


# ==============================================================================
# 8. Scoped Reconciliation Tests
# ==============================================================================


def test_execute_reconcile_clean_with_scopes(tmp_path):
    """Verify clean reconciliation exit code 0 when all production references are migrated."""
    manifest_file = tmp_path / "docs" / "migrations" / "migration-manifest.json"
    manifest_file.parent.mkdir(parents=True)

    # HTML contains migrated CloudFront URL
    lesson_html = tmp_path / "frontend" / "system-design" / "lessons" / "step.html"
    lesson_html.parent.mkdir(parents=True)
    lesson_html.write_text('<img src="https://d3staging123.cloudfront.net/fig.png"/>', encoding="utf-8")

    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://d3staging123.cloudfront.net/fig.png",
        content_type="image/png",
        byte_count=100,
        sha256="abc",
        source_files=["frontend/system-design/lessons/step.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 0


def test_execute_reconcile_unreconciled_production_references_returns_1(tmp_path):
    """Verify reconcile returns exit code 1 when Cloudinary references remain in production content."""
    manifest_file = tmp_path / "migration-manifest.json"
    url = "https://res.cloudinary.com/c/image/upload/v1/fig.png"

    lesson_html = tmp_path / "frontend" / "system-design" / "lessons" / "step.html"
    lesson_html.parent.mkdir(parents=True)
    lesson_html.write_text(f'<img src="{url}"/>', encoding="utf-8")

    entry = ManifestEntry(
        original_url=url,
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://d3staging123.cloudfront.net/fig.png",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["frontend/system-design/lessons/step.html"],
        status="pending",
        error=None,
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 1


def test_execute_reconcile_distinguishes_docs_and_runtime(tmp_path):
    """Verify historical docs and runtime findings are reported but don't fail gate if production assets clean."""
    manifest_file = tmp_path / "migration-manifest.json"

    # Production file is 100% clean
    lesson_html = tmp_path / "frontend" / "system-design" / "lessons" / "step.html"
    lesson_html.parent.mkdir(parents=True)
    lesson_html.write_text('<img src="https://d3staging123.cloudfront.net/fig.png"/>', encoding="utf-8")

    # Documentation file has historical example
    doc_file = tmp_path / "docs" / "migration.md"
    doc_file.parent.mkdir(parents=True)
    doc_file.write_text('Historical: https://res.cloudinary.com/c/image/upload/v1/old.png', encoding="utf-8")

    # Runtime code file has historical mention
    code_file = tmp_path / "backend" / "test_ref.py"
    code_file.parent.mkdir(parents=True)
    code_file.write_text('# Ref: CLOUDINARY_URL legacy note\n', encoding="utf-8")

    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="https://d3staging123.cloudfront.net/fig.png",
        content_type="image/png",
        byte_count=100,
        sha256="abc",
        source_files=["frontend/system-design/lessons/step.html"],
        status="verified",
        error=None,
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    # Production gate passes because 0 broken production assets remain
    assert code == 0


def test_execute_reconcile_failed_manifest_entry_returns_1(tmp_path):
    """Verify reconcile returns exit code 1 if any manifest entry is marked 'failed'."""
    manifest_file = tmp_path / "migration-manifest.json"

    entry = ManifestEntry(
        original_url="https://res.cloudinary.com/c/image/upload/v1/fig.png",
        source_cloud="c",
        canonical_id="fig",
        s3_key="fig.png",
        s3_url="https://s3/fig.png",
        cloudfront_url="",
        content_type="image/png",
        byte_count=0,
        sha256="",
        source_files=["step.html"],
        status="failed",
        error="S3 upload failed",
    )
    save_manifest(manifest_file, [entry], dry_run=False)

    code = execute_reconcile(repo_root=tmp_path, manifest_path=manifest_file)
    assert code == 1


# ==============================================================================
# 9. CLI Interface & Orchestration Tests
# ==============================================================================


def test_main_cli_inventory_with_valid_base_url(tmp_path):
    """Verify running CLI with --inventory and valid --asset-base-url succeeds."""
    lesson = tmp_path / "frontend" / "system-design" / "lessons" / "test.html"
    lesson.parent.mkdir(parents=True)
    lesson.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/a.png"/>',
        encoding="utf-8",
    )
    manifest_file = tmp_path / "manifest.json"

    exit_code = main([
        "--inventory",
        "--repo-root", str(tmp_path),
        "--manifest", str(manifest_file),
        "--asset-base-url", "https://d3staging123.cloudfront.net",
    ])
    assert exit_code == 0
    assert manifest_file.exists()

    entries = load_manifest(manifest_file)
    assert len(entries) == 1
    assert entries[0].s3_key == "system-design/01/a.png"
    assert entries[0].cloudfront_url == "https://d3staging123.cloudfront.net/system-design/01/a.png"


def test_main_cli_inventory_rejects_fictitious_base_url(tmp_path):
    """Verify CLI rejects fictitious CloudFront URL during inventory."""
    manifest_file = tmp_path / "manifest.json"
    exit_code = main([
        "--inventory",
        "--repo-root", str(tmp_path),
        "--manifest", str(manifest_file),
        "--asset-base-url", "https://d123456abcdef8.cloudfront.net",
    ])
    assert exit_code == 1
    assert not manifest_file.exists()


def test_main_cli_test_mode_flag(tmp_path):
    """Verify --test-mode permits test hostnames."""
    lesson = tmp_path / "frontend" / "system-design" / "lessons" / "test.html"
    lesson.parent.mkdir(parents=True)
    lesson.write_text(
        '<img src="https://res.cloudinary.com/c/image/upload/v1/interview-assistant/system-design/01/a.png"/>',
        encoding="utf-8",
    )
    manifest_file = tmp_path / "manifest.json"

    exit_code = main([
        "--inventory",
        "--test-mode",
        "--repo-root", str(tmp_path),
        "--manifest", str(manifest_file),
        "--asset-base-url", "https://test-cdn.example.com",
    ])
    assert exit_code == 0
    assert manifest_file.exists()


def test_main_cli_no_args_shows_help(capsys):
    """Verify running CLI with no operations prints help and exits 0."""
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out or "usage:" in captured.err or "Migrate static assets" in captured.out
