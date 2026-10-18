#!/usr/bin/env python3
"""Migrate static assets from Cloudinary to Amazon S3 + CloudFront.

This production-grade, resumable CLI tool performs:
1. Inventory: Scans repo (HTML, Markdown, JSON) for Cloudinary URLs & builds/updates manifest
   with distinct audit scopes (static assets, runtime dependencies, documentation).
2. Dry-Run: Previews actions with strict zero-mutation guarantees across files, manifests, and AWS resources.
3. Upload: Downloads assets from Cloudinary with retries/timeouts, computes SHA-256,
   detects key collisions, provides idempotency, and uploads to S3 with content types & metadata.
4. Verify: Verifies S3 objects via HeadObject (size, content-type, SHA-256 integrity) and CloudFront HTTP checks.
5. Rewrite: Rewrites source files (e.g. system-design HTML) ONLY for verified assets,
   strictly preserving all surrounding HTML structure, tags, and attributes.
6. Reconcile: Verifies that 0 broken or unverified production asset references remain across the codebase,
   categorizing remaining references by scope (static, runtime, documentation).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Initialize standard mime types for common web assets
mimetypes.init()
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/png", ".png")
mimetypes.add_type("image/jpeg", ".jpg")
mimetypes.add_type("image/jpeg", ".jpeg")
mimetypes.add_type("image/gif", ".gif")

# Logger setup
logger = logging.getLogger("migrate_cloudinary_to_s3")

# Environment & Config Defaults (aligned with migration-contracts.md)
DEFAULT_BUCKET = os.getenv("S3_ASSETS_BUCKET", "interview-prep-assets-808431466075-personal-ap-south-2")
DEFAULT_REGION = os.getenv("S3_ASSETS_REGION", "ap-south-2")
# STRICT: ASSET_BASE_URL defaults to empty; fictitious hostnames (e.g. d123456abcdef8) are forbidden
DEFAULT_CLOUDFRONT_BASE = os.getenv("ASSET_BASE_URL", "").strip()
DEFAULT_MANIFEST_REL = Path("docs") / "migrations" / "migration-manifest.json"

DEFAULT_EXTENSIONS = {".html", ".md", ".json"}
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-new",
    ".venv-win",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
}
DEFAULT_EXCLUDE_FILES = {
    "migration-manifest.json",
    "cloudinary-inventory.json",
}

# Forbidden placeholder tokens that must never appear in production or staging base URLs
FORBIDDEN_PLACEHOLDER_TOKENS = {
    "d123456abcdef8",
    "<distribution-id>",
    "<your-distribution-id>",
    "${asset_base_url}",
    "distribution-id",
    "your-distribution-id",
}

FORBIDDEN_TEST_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "localhost",
    "test.com",
    "placeholder",
}

# Regex to detect and parse Cloudinary delivery URLs
CLOUDINARY_URL_PATTERN = re.compile(
    r'https?://(?:res\.cloudinary\.com|[^/\s"\'<>]+\.cloudinary\.com)/'
    r'([^/\s"\'<>]+)/'                             # group 1: cloud_name
    r'(?:(?:image|raw|video)/)?'                  # optional resource_type
    r'(?:upload/)?'                                # optional delivery_type
    r'(?:(?:[a-zA-Z]_[^/]+,)*[a-zA-Z]_[^/]+/)?'    # optional transformations (e.g. c_scale,w_500/)
    r'(?:v\d+/)?'                                  # optional version (e.g. v1776887006/)
    r'([^\s"\'<>\)]+)'                             # group 2: asset path
)

VALID_STATUSES = {"pending", "downloaded", "uploaded", "verified", "failed", "skipped"}


# ==============================================================================
# URL Validation & Key Generation
# ==============================================================================


def validate_asset_base_url(url: Optional[str], test_mode: bool = False) -> str:
    """Validate CloudFront base URL according to staging readiness contract.

    Rules:
    - Must be a non-empty string.
    - Must start with 'https://'.
    - Must have a valid domain / host name.
    - Must not have a path other than root ('/').
    - Must NOT contain forbidden placeholder tokens ('d123456abcdef8', '<distribution-id>', '${ASSET_BASE_URL}').
    - In non-test mode (test_mode=False): must have a valid FQDN domain and not contain test domains (e.g. example.com).
    - In test mode (test_mode=True): test hostnames (e.g. cf.domain.net, test-cdn.example.com) are permitted.

    Returns:
        The normalized HTTPS base URL (without trailing slash).

    Raises:
        ValueError: If validation fails.
    """
    if not url or not isinstance(url, str) or not url.strip():
        raise ValueError(
            "Asset base URL cannot be empty. A validated HTTPS CloudFront base URL is required."
        )

    clean_url = url.strip().rstrip("/")
    lower_url = clean_url.lower()

    # Must start with https://
    parsed = urllib.parse.urlsplit(clean_url)
    if parsed.scheme != "https":
        raise ValueError(
            f"Asset base URL must start with 'https://' (got scheme '{parsed.scheme}')."
        )

    if not parsed.netloc:
        raise ValueError("Asset base URL must include a valid domain or host.")

    if parsed.path and parsed.path != "/":
        raise ValueError(
            f"Asset base URL must be an origin base without subpaths (got '{parsed.path}')."
        )

    # Check for forbidden placeholder tokens
    for token in FORBIDDEN_PLACEHOLDER_TOKENS:
        if token in lower_url:
            raise ValueError(
                f"Asset base URL contains forbidden placeholder token '{token}' in '{clean_url}'."
            )

    # Check for template markers
    if any(marker in clean_url for marker in ["${", "}", "<", ">"]):
        raise ValueError(
            f"Asset base URL contains template placeholder markers in '{clean_url}'."
        )

    host = parsed.netloc.split(":")[0]

    # Test mode check vs production/staging check
    if not test_mode:
        for test_domain in FORBIDDEN_TEST_DOMAINS:
            if test_domain in lower_url:
                raise ValueError(
                    f"Asset base URL contains test/mock domain '{test_domain}' in '{clean_url}'. "
                    f"A valid staging or production CloudFront distribution URL is required."
                )

        domain_regex = re.compile(
            r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        )
        if not domain_regex.match(host):
            raise ValueError(
                f"Asset base URL host '{parsed.netloc}' is not a valid fully qualified domain."
            )

    return clean_url


@dataclass
class ManifestEntry:
    original_url: str
    source_cloud: str
    canonical_id: str
    s3_key: str
    s3_url: str
    cloudfront_url: str
    content_type: str
    byte_count: int
    sha256: str
    source_files: List[str]
    status: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ManifestEntry:
        return cls(
            original_url=str(data.get("original_url", "")),
            source_cloud=str(data.get("source_cloud", "")),
            canonical_id=str(data.get("canonical_id", "")),
            s3_key=str(data.get("s3_key", "")),
            s3_url=str(data.get("s3_url", "")),
            cloudfront_url=str(data.get("cloudfront_url", "")),
            content_type=str(data.get("content_type", "application/octet-stream")),
            byte_count=int(data.get("byte_count", 0)),
            sha256=str(data.get("sha256", "")),
            source_files=list(data.get("source_files", [])),
            status=str(data.get("status", "pending")),
            error=data.get("error"),
        )


def guess_content_type(filename_or_key: str, default: str = "application/octet-stream") -> str:
    """Guess MIME content type from filename or S3 key."""
    ctype, _ = mimetypes.guess_type(filename_or_key)
    return ctype or default


def generate_canonical_id(asset_path: str) -> str:
    """Derive canonical identifier from Cloudinary asset path.

    E.g. 'interview-assistant/system-design/02/figure-1-1-WCFZBBLA.png'
    -> 'interview-assistant/system-design/02/figure-1-1-WCFZBBLA'
    """
    clean_path = asset_path.split("?")[0].split("#")[0]
    if "." in clean_path:
        return clean_path.rsplit(".", 1)[0]
    return clean_path


def generate_s3_key(asset_path: str) -> str:
    """Derive S3 object key according to project naming conventions in migration-contracts.md.

    - System design lessons: system-design/{chapter_number}/{filename_slug}.{ext}
    - Avatars: avatars/{user_id}/{unique_uuid}.{ext}
    - Other static assets: static/{category}/{filename_slug}.{ext}
    """
    clean_path = asset_path.split("?")[0].split("#")[0].lstrip("/")

    # Strip 'interview-assistant/' if present
    if clean_path.startswith("interview-assistant/"):
        inner = clean_path[len("interview-assistant/"):]
        if inner.startswith("system-design/") or inner.startswith("avatars/"):
            return inner
        return f"static/{inner}"

    # If path already begins with standard prefix
    if clean_path.startswith("system-design/") or clean_path.startswith("avatars/"):
        return clean_path

    if clean_path.startswith("static/"):
        return clean_path

    return f"static/{clean_path}"


def parse_cloudinary_url(
    url: str,
    bucket: str = DEFAULT_BUCKET,
    region: str = DEFAULT_REGION,
    cloudfront_base: Optional[str] = None,
    test_mode: bool = False,
) -> Optional[Dict[str, Any]]:
    """Parse a Cloudinary URL into manifest fields, or None if not matching.

    Requires an actual, validated HTTPS CloudFront base URL before URL generation.
    """
    match = CLOUDINARY_URL_PATTERN.match(url.strip())
    if not match:
        return None

    # Base URL must be explicitly provided or configured in ASSET_BASE_URL
    cf_base_raw = cloudfront_base if cloudfront_base is not None else DEFAULT_CLOUDFRONT_BASE
    if not cf_base_raw:
        raise ValueError(
            "A validated HTTPS CloudFront base URL (ASSET_BASE_URL) is required for CloudFront URL generation."
        )

    validated_cf_base = validate_asset_base_url(cf_base_raw, test_mode=test_mode)

    cloud_name = match.group(1)
    raw_path = match.group(2)

    canonical_id = generate_canonical_id(raw_path)
    s3_key = generate_s3_key(raw_path)
    content_type = guess_content_type(s3_key)

    s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
    cloudfront_url = f"{validated_cf_base}/{s3_key}"

    return {
        "original_url": url.strip(),
        "source_cloud": cloud_name,
        "canonical_id": canonical_id,
        "s3_key": s3_key,
        "s3_url": s3_url,
        "cloudfront_url": cloudfront_url,
        "content_type": content_type,
        "byte_count": 0,
        "sha256": "",
        "status": "pending",
        "error": None,
    }


# ==============================================================================
# Audit Scope Classification & Repository Scanning
# ==============================================================================


def classify_file_scope(rel_path: str) -> str:
    """Classify file into one of the 3 audit scopes:
    - 'static': actual content files embedding production asset URLs (e.g. frontend/system-design/lessons/step-*.html)
    - 'docs': documentation, architectural notes, guides, or markdown files
    - 'runtime': application code, dependencies, docker, config, tests
    """
    p = rel_path.replace("\\", "/").lower()
    if p.startswith("docs/") or p.endswith(".md") or "/docs/" in p or p in {"deployment.md", "readme.md"}:
        return "docs"
    if (
        p.startswith("frontend/system-design/")
        or (p.startswith("frontend/") and any(p.endswith(ext) for ext in [".html", ".htm"]))
        or "lessons/" in p
        or p.startswith("static/")
    ):
        return "static"
    return "runtime"


def scan_repository_for_urls(
    repo_root: Path,
    scan_dir: Optional[Path] = None,
    extensions: Optional[Set[str]] = None,
    exclude_dirs: Optional[Set[str]] = None,
    exclude_files: Optional[Set[str]] = None,
    manifest_path: Optional[Path] = None,
    scope: str = "all",  # "all", "static", "docs", "runtime"
) -> Dict[str, List[str]]:
    """Scan files for Cloudinary URLs. Returns mapping of url -> list of relative file paths.

    If scope is provided ('static', 'docs', 'runtime'), filters results to that scope.
    """
    target_dir = scan_dir or repo_root
    exts = extensions or DEFAULT_EXTENSIONS
    excludes = exclude_dirs or DEFAULT_EXCLUDE_DIRS
    excl_files = exclude_files or DEFAULT_EXCLUDE_FILES

    resolved_manifest = manifest_path.resolve() if manifest_path else None
    raw_url_pattern = re.compile(r'https?://[^\s"\'<>\)]*cloudinary\.com/[^\s"\'<>\)]+')
    found_urls: Dict[str, List[str]] = {}

    for root, dirs, files in os.walk(target_dir):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in excludes]

        for file in files:
            if file in excl_files:
                continue
            file_path = Path(root) / file
            if resolved_manifest and file_path.resolve() == resolved_manifest:
                continue
            if file_path.suffix.lower() not in exts:
                continue

            try:
                rel_path = file_path.relative_to(repo_root).as_posix()
            except ValueError:
                rel_path = file_path.as_posix()

            file_scope = classify_file_scope(rel_path)
            if scope != "all" and file_scope != scope:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning("Could not read file %s: %s", rel_path, e)
                continue

            for match in raw_url_pattern.finditer(content):
                u = match.group(0).rstrip(".,;)]}\"'")
                if CLOUDINARY_URL_PATTERN.match(u):
                    if u not in found_urls:
                        found_urls[u] = []
                    if rel_path not in found_urls[u]:
                        found_urls[u].append(rel_path)

    # Sort source files for determinism
    for u in found_urls:
        found_urls[u].sort()

    return found_urls


RUNTIME_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".txt", ".yml", ".yaml", ".env", ".sh", ".dockerfile"
}
RUNTIME_EXCLUDED_FILES = {
    "migrate_cloudinary_to_s3.py",
    "reconcile_db_avatars.py",
    "test_migrate_cloudinary_to_s3.py",
    "test_reconcile_db_avatars.py",
    "migration-manifest.json",
    "cloudinary-inventory.json",
    "avatar-rollback-map.json",
}


def scan_runtime_dependencies(
    repo_root: Path,
    scan_dir: Optional[Path] = None,
    exclude_dirs: Optional[Set[str]] = None,
    exclude_files: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Scan codebase, dependency files, docker config, tests for remaining Cloudinary SDK/API calls and variables."""
    target_dir = scan_dir or repo_root
    excludes = exclude_dirs or DEFAULT_EXCLUDE_DIRS
    excl_files = exclude_files or RUNTIME_EXCLUDED_FILES

    findings: List[Dict[str, Any]] = []

    sdk_pattern = re.compile(
        r'\b(?:import\s+cloudinary|from\s+cloudinary\b|cloudinary\.(?:uploader|api|config|v2))\b',
        re.IGNORECASE,
    )
    env_var_pattern = re.compile(r'\bCLOUDINARY_(?:URL|CLOUD_NAME|API_KEY|API_SECRET)\b')
    pkg_pattern = re.compile(r'^\s*cloudinary\b', re.IGNORECASE)

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in excludes]

        for file in files:
            if file in excl_files or file.startswith("."):
                continue
            file_path = Path(root) / file

            suffix = file_path.suffix.lower()
            name_lower = file.lower()
            is_relevant = (
                suffix in RUNTIME_EXTENSIONS
                or "dockerfile" in name_lower
                or "requirements" in name_lower
                or name_lower.startswith(".env")
            )
            if not is_relevant:
                continue

            try:
                rel_path = file_path.relative_to(repo_root).as_posix()
            except ValueError:
                rel_path = file_path.as_posix()

            # Skip documentation files from runtime scan
            if classify_file_scope(rel_path) == "docs":
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception as e:
                logger.warning("Could not read file %s: %s", rel_path, e)
                continue

            for idx, line in enumerate(lines, start=1):
                clean_line = line.strip()
                if not clean_line or clean_line.startswith("#") or clean_line.startswith("//"):
                    continue

                if "requirements" in name_lower and pkg_pattern.match(clean_line):
                    findings.append({
                        "file": rel_path,
                        "line": idx,
                        "category": "package_dependency",
                        "snippet": clean_line,
                    })
                elif sdk_pattern.search(clean_line):
                    findings.append({
                        "file": rel_path,
                        "line": idx,
                        "category": "sdk_call",
                        "snippet": clean_line,
                    })
                elif env_var_pattern.search(clean_line):
                    findings.append({
                        "file": rel_path,
                        "line": idx,
                        "category": "env_var",
                        "snippet": clean_line,
                    })

    return findings


@dataclass
class ScopedAuditInventory:
    static_assets: Dict[str, List[str]]
    runtime_dependencies: List[Dict[str, Any]]
    documentation_assets: Dict[str, List[str]]


def run_scoped_audit(
    repo_root: Path,
    scan_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
) -> ScopedAuditInventory:
    """Run comprehensive repository audit separated across the 3 scopes."""
    static = scan_repository_for_urls(
        repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path, scope="static"
    )
    runtime = scan_runtime_dependencies(
        repo_root=repo_root, scan_dir=scan_dir
    )
    docs = scan_repository_for_urls(
        repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path, scope="docs"
    )
    return ScopedAuditInventory(
        static_assets=static,
        runtime_dependencies=runtime,
        documentation_assets=docs,
    )


# ==============================================================================
# Manifest Management & Collision Detection
# ==============================================================================


def detect_manifest_key_collisions(
    entries: Sequence[ManifestEntry],
) -> List[Tuple[str, str, str]]:
    """Detect key collisions where different original URLs map to the same S3 key."""
    key_to_url: Dict[str, str] = {}
    collisions: List[Tuple[str, str, str]] = []
    for entry in entries:
        if entry.s3_key in key_to_url:
            existing_url = key_to_url[entry.s3_key]
            if existing_url != entry.original_url:
                collisions.append((entry.s3_key, existing_url, entry.original_url))
        else:
            key_to_url[entry.s3_key] = entry.original_url
    return collisions


def load_manifest(manifest_path: Path) -> List[ManifestEntry]:
    """Load migration manifest from JSON file. Returns list of ManifestEntry."""
    if not manifest_path.exists():
        return []

    try:
        content = manifest_path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        data = json.loads(content)
    except Exception as e:
        logger.error("Failed to parse manifest %s: %s", manifest_path, e)
        raise

    raw_entries: List[Dict[str, Any]] = []
    if isinstance(data, list):
        raw_entries = data
    elif isinstance(data, dict):
        raw_entries = data.get("entries") or data.get("assets") or []
    else:
        logger.warning("Unexpected manifest structure in %s", manifest_path)
        return []

    entries: List[ManifestEntry] = []
    for item in raw_entries:
        if isinstance(item, dict) and "original_url" in item:
            entries.append(ManifestEntry.from_dict(item))
    return entries


def save_manifest(manifest_path: Path, entries: Sequence[ManifestEntry], dry_run: bool = False) -> None:
    """Atomically write manifest to JSON file, strictly respecting dry-run."""
    if dry_run:
        logger.info("[DRY-RUN] Would save manifest with %d entries to %s", len(entries), manifest_path)
        return

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    dict_list = [e.to_dict() for e in entries]

    temp_path = manifest_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(dict_list, f, indent=2)
        f.write("\n")

    temp_path.replace(manifest_path)
    logger.debug("Saved manifest with %d entries to %s", len(entries), manifest_path)


def build_or_update_manifest(
    repo_root: Path,
    manifest_path: Path,
    bucket: str = DEFAULT_BUCKET,
    region: str = DEFAULT_REGION,
    cloudfront_base: Optional[str] = None,
    scan_dir: Optional[Path] = None,
    dry_run: bool = False,
    test_mode: bool = False,
    scope: str = "static",
) -> Tuple[List[ManifestEntry], Dict[str, int]]:
    """Scan repo and build or merge into manifest preserving existing progress."""
    existing_entries = load_manifest(manifest_path)
    existing_map: Dict[str, ManifestEntry] = {e.original_url: e for e in existing_entries}

    validated_cf_base: Optional[str] = None
    if cloudfront_base:
        validated_cf_base = validate_asset_base_url(cloudfront_base, test_mode=test_mode)

    discovered = scan_repository_for_urls(
        repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path, scope=scope
    )

    added_count = 0
    updated_count = 0
    unchanged_count = 0

    merged_entries: List[ManifestEntry] = []

    # Process all discovered URLs
    for url, files in discovered.items():
        if url in existing_map:
            entry = existing_map[url]
            changed = False
            if set(entry.source_files) != set(files):
                entry.source_files = files
                changed = True
            expected_s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{entry.s3_key}"
            if entry.s3_url != expected_s3_url:
                entry.s3_url = expected_s3_url
                changed = True
            if validated_cf_base and (not entry.cloudfront_url or entry.cloudfront_url.startswith("https://")):
                new_cf = f"{validated_cf_base}/{entry.s3_key}"
                if entry.cloudfront_url != new_cf:
                    entry.cloudfront_url = new_cf
                    changed = True
            if changed:
                updated_count += 1
            else:
                unchanged_count += 1
            merged_entries.append(entry)
        else:
            if not validated_cf_base:
                raise ValueError(
                    "A validated HTTPS CloudFront base URL is required before generating new manifest entries. "
                    "Provide --asset-base-url or set ASSET_BASE_URL."
                )
            parsed = parse_cloudinary_url(
                url=url,
                bucket=bucket,
                region=region,
                cloudfront_base=validated_cf_base,
                test_mode=test_mode,
            )
            if parsed:
                parsed["source_files"] = files
                new_entry = ManifestEntry.from_dict(parsed)
                merged_entries.append(new_entry)
                added_count += 1

    # Keep any existing entries that were in the manifest even if not found in current scan
    discovered_urls = set(discovered.keys())
    for url, entry in existing_map.items():
        if url not in discovered_urls:
            changed = False
            expected_s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{entry.s3_key}"
            if entry.s3_url != expected_s3_url:
                entry.s3_url = expected_s3_url
                changed = True
            if validated_cf_base and (not entry.cloudfront_url or entry.cloudfront_url.startswith("https://")):
                new_cf = f"{validated_cf_base}/{entry.s3_key}"
                if entry.cloudfront_url != new_cf:
                    entry.cloudfront_url = new_cf
                    changed = True
            if changed:
                updated_count += 1
            merged_entries.append(entry)

    # Check for key collisions
    collisions = detect_manifest_key_collisions(merged_entries)
    if collisions:
        for k, u1, u2 in collisions:
            logger.error("Manifest key collision on S3 key '%s' between '%s' and '%s'", k, u1, u2)
        raise ValueError(f"Detected {len(collisions)} S3 key collisions in manifest assets.")

    # Sort entries by s3_key for deterministic manifest ordering
    merged_entries.sort(key=lambda x: x.s3_key)

    stats = {
        "total": len(merged_entries),
        "added": added_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
        "files_scanned": len(set(f for files in discovered.values() for f in files)),
    }

    if not dry_run:
        save_manifest(manifest_path, merged_entries)

    return merged_entries, stats


# ==============================================================================
# Download, S3 Upload & Checksum Verification
# ==============================================================================


def download_asset(
    url: str, timeout: int = 30, max_retries: int = 3, backoff_factor: float = 1.5
) -> Tuple[bytes, str, str]:
    """Download asset with retries and exponential backoff.

    Returns: (content_bytes, sha256_hash, content_type)
    """
    last_err: Optional[Exception] = None
    headers = {"User-Agent": "InterviewPrep-Migration-Tool/1.0"}

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                raw_ctype = resp.headers.get("Content-Type", "")
                ctype = raw_ctype.split(";")[0].strip() or guess_content_type(url)
                sha256 = hashlib.sha256(content).hexdigest()
                return content, sha256, ctype
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                sleep_secs = backoff_factor ** (attempt - 1)
                logger.warning(
                    "Download failed for %s (attempt %d/%d): %s. Retrying in %.1fs...",
                    url,
                    attempt,
                    max_retries,
                    e,
                    sleep_secs,
                )
                time.sleep(sleep_secs)

    raise RuntimeError(f"Failed to download {url} after {max_retries} attempts: {last_err}")


def check_s3_collision_or_existing(
    s3_client: Any,
    bucket: str,
    key: str,
    data_sha256: str,
    data_size: int,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """Check if object already exists in S3 and detect content/sha256 collisions.

    Returns:
        (already_exists, collision_error, head_object_response)
        - Object not found: (False, None, None)
        - Object exists and matches SHA-256 (or size): (True, None, head_object_dict) -> Idempotent skip
        - Object exists but differs in SHA-256 or size: (True, "Key collision: ...", head_object_dict)
    """
    try:
        resp = s3_client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        is_missing = False
        error_code = None
        http_status = None

        err_str = str(exc).lower()
        if hasattr(exc, "response") and isinstance(exc.response, dict):
            error_code = str(exc.response.get("Error", {}).get("Code", "")).strip()
            http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if error_code in {"404", "NoSuchKey", "NotFound"} or http_status == 404:
                is_missing = True
        elif type(exc).__name__ in {"NoSuchKey", "NotFound"}:
            is_missing = True
        elif any(token in err_str for token in ["404", "nosuchkey", "not found"]):
            # Guardrail: Never recognize as missing if it contains auth, permission, timeout, or rate limit indicators
            non_missing_indicators = [
                "accessdenied", "access denied", "403", "forbidden", "unauthorized",
                "credential", "slowdown", "throttl", "timeout", "timed out"
            ]
            if not any(token in err_str for token in non_missing_indicators):
                is_missing = True

        if is_missing:
            # Verified that object is absent in S3
            return False, None, None

        # Never treat AccessDenied, credential failures, throttling, timeouts, or unexpected errors as object absent
        logger.error(
            "Unexpected error during S3 HeadObject check for s3://%s/%s (code=%s, status=%s): %s",
            bucket,
            key,
            error_code,
            http_status,
            exc,
        )
        raise

    metadata = resp.get("Metadata", {})
    existing_sha = metadata.get("sha256", "").strip()
    existing_size = resp.get("ContentLength", 0)

    if existing_sha:
        if existing_sha.lower() == data_sha256.lower():
            # Matching SHA-256: idempotent match!
            return True, None, resp
        else:
            # Different SHA-256: collision!
            err = (
                f"Key collision detected: s3://{bucket}/{key} already exists with SHA-256 "
                f"'{existing_sha}' (incoming asset SHA-256: '{data_sha256}')."
            )
            return True, err, resp

    # If no SHA-256 metadata, compare byte sizes
    if existing_size > 0 and data_size > 0:
        if existing_size == data_size:
            return True, None, resp
        else:
            err = (
                f"Key collision detected: s3://{bucket}/{key} already exists with size "
                f"{existing_size} bytes (incoming asset size: {data_size} bytes)."
            )
            return True, err, resp

    return True, None, resp


def upload_to_s3(
    s3_client: Any,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    sha256: Optional[str] = None,
    extra_metadata: Optional[Dict[str, str]] = None,
) -> None:
    """Upload byte buffer to S3 with content-type and metadata."""
    metadata = extra_metadata or {}
    if sha256:
        metadata["sha256"] = sha256
    metadata["migrated-from"] = "cloudinary"

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        Metadata=metadata,
    )


def verify_s3_object(
    s3_client: Any,
    bucket: str,
    key: str,
    expected_size: Optional[int] = None,
    expected_content_type: Optional[str] = None,
    expected_sha256: Optional[str] = None,
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Verify object existence, attributes, and SHA-256 integrity via HeadObject.

    Returns: (is_valid, error_msg, details)
    """
    try:
        resp = s3_client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        return False, f"HeadObject failed: {e}", {}

    size = resp.get("ContentLength", 0)
    ctype = resp.get("ContentType", "")
    metadata = resp.get("Metadata", {})
    actual_sha = metadata.get("sha256", "").strip()

    if expected_size is not None and expected_size > 0:
        if size != expected_size:
            return (
                False,
                f"Size mismatch: expected {expected_size} bytes, got {size} bytes",
                resp,
            )

    sha256_verified = False
    if expected_sha256:
        if actual_sha:
            if actual_sha.lower() != expected_sha256.lower():
                return (
                    False,
                    f"SHA-256 integrity mismatch: expected {expected_sha256}, got {actual_sha}",
                    resp,
                )
            sha256_verified = True

    return True, None, {
        "ContentLength": size,
        "ContentType": ctype,
        "sha256": actual_sha,
        "sha256_verified": sha256_verified,
    }


def verify_cloudfront_object(
    cloudfront_url: str,
    timeout: int = 10,
    test_mode: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Verify CloudFront edge availability via HTTP HEAD/GET with URL safety validation."""
    if not cloudfront_url:
        return False, "CloudFront URL is empty"

    try:
        # Validate CloudFront URL before making HTTP request
        parsed = urllib.parse.urlsplit(cloudfront_url)
        origin_base = f"{parsed.scheme}://{parsed.netloc}"
        validate_asset_base_url(origin_base, test_mode=test_mode)
        for token in FORBIDDEN_PLACEHOLDER_TOKENS:
            if token in cloudfront_url.lower():
                return False, f"CloudFront URL contains forbidden placeholder token: '{token}'"
    except Exception as e:
        return False, f"Invalid CloudFront URL: {e}"

    try:
        req = urllib.request.Request(
            cloudfront_url, headers={"User-Agent": "InterviewPrep-Migration-Verifier/1.0"}
        )
        req.get_method = lambda: "HEAD"  # type: ignore[assignment]
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return True, None
            return False, f"HTTP status {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"CloudFront HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, f"CloudFront check error: {e}"


# ==============================================================================
# High-Level CLI Operations
# ==============================================================================


def execute_inventory(
    repo_root: Path,
    manifest_path: Path,
    bucket: str,
    region: str,
    cloudfront_base: Optional[str] = None,
    scan_dir: Optional[Path] = None,
    dry_run: bool = False,
    test_mode: bool = False,
    audit_scope: str = "all",
) -> int:
    """Execute inventory scan and report across scopes."""
    logger.info("Starting scoped inventory scan in %s (scope: %s)...", scan_dir or repo_root, audit_scope)

    if audit_scope in {"all", "static"}:
        if not cloudfront_base:
            logger.error(
                "A validated HTTPS CloudFront base URL is required before inventory/URL generation. "
                "Provide --asset-base-url or set ASSET_BASE_URL."
            )
            return 1

        try:
            entries, stats = build_or_update_manifest(
                repo_root=repo_root,
                manifest_path=manifest_path,
                bucket=bucket,
                region=region,
                cloudfront_base=cloudfront_base,
                scan_dir=scan_dir,
                dry_run=dry_run,
                test_mode=test_mode,
                scope="static",
            )
        except Exception as e:
            logger.error("Inventory failed: %s", e)
            return 1

        prefix = "[DRY-RUN] " if dry_run else ""
        logger.info(
            "%sStatic Asset Inventory: %d total assets in manifest (%d newly added, %d updated, %d unchanged across %d files)",
            prefix,
            stats["total"],
            stats["added"],
            stats["updated"],
            stats["unchanged"],
            stats["files_scanned"],
        )

    if audit_scope in {"all", "runtime"}:
        runtime_deps = scan_runtime_dependencies(repo_root=repo_root, scan_dir=scan_dir)
        logger.info(
            "Runtime Dependency Inventory: found %d Cloudinary SDK/API calls or variables in codebase.",
            len(runtime_deps),
        )

    if audit_scope in {"all", "docs"}:
        docs_urls = scan_repository_for_urls(
            repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path, scope="docs"
        )
        logger.info(
            "Documentation Inventory: found %d historical/docs Cloudinary URLs across %d documentation files.",
            len(docs_urls),
            sum(len(f) for f in docs_urls.values()),
        )

    return 0


def execute_upload(
    manifest_path: Path,
    bucket: str,
    s3_client: Any = None,
    dry_run: bool = False,
    force: bool = False,
    limit: Optional[int] = None,
    timeout: int = 30,
    max_retries: int = 3,
) -> int:
    """Execute asset download from Cloudinary and idempotent upload to S3 with collision detection."""
    entries = load_manifest(manifest_path)
    if not entries:
        logger.warning("Manifest is empty or missing at %s. Run --inventory first.", manifest_path)
        return 1

    targets: List[ManifestEntry] = []
    for e in entries:
        if force or e.status in {"pending", "downloaded", "failed"}:
            targets.append(e)

    if limit and limit > 0:
        targets = targets[:limit]

    logger.info("Found %d assets queued for upload processing.", len(targets))

    # STRICT DRY-RUN: zero network writes, zero manifest writes
    if dry_run:
        for e in targets:
            logger.info(
                "[DRY-RUN] Would download: %s and upload to s3://%s/%s (content_type=%s)",
                e.original_url,
                bucket,
                e.s3_key,
                e.content_type,
            )
        logger.info("[DRY-RUN] Upload simulation complete for %d items (zero mutation guarantee).", len(targets))
        return 0

    if s3_client is None:
        import boto3
        s3_client = boto3.client("s3")

    success_count = 0
    failure_count = 0
    idempotent_skipped = 0
    collision_count = 0

    for idx, entry in enumerate(targets, start=1):
        logger.info("[%d/%d] Processing %s...", idx, len(targets), entry.s3_key)
        try:
            # 1. Download & hash
            data, sha256, ctype = download_asset(
                entry.original_url, timeout=timeout, max_retries=max_retries
            )
            entry.byte_count = len(data)
            entry.sha256 = sha256
            if ctype and ctype != "application/octet-stream":
                entry.content_type = ctype
            entry.status = "downloaded"

            # 2. Collision & Idempotency check in S3
            already_exists, col_err, head_resp = check_s3_collision_or_existing(
                s3_client=s3_client,
                bucket=bucket,
                key=entry.s3_key,
                data_sha256=sha256,
                data_size=len(data),
            )

            if col_err and not force:
                entry.status = "failed"
                entry.error = col_err
                collision_count += 1
                failure_count += 1
                logger.error("%s", col_err)
                save_manifest(manifest_path, entries)
                continue

            if already_exists and not force:
                entry.status = "uploaded"
                entry.error = None
                idempotent_skipped += 1
                success_count += 1
                logger.info(
                    "Object already exists in s3://%s/%s with matching SHA-256. Skipping upload (idempotent).",
                    bucket,
                    entry.s3_key,
                )
                save_manifest(manifest_path, entries)
                continue

            # 3. Upload to S3
            upload_to_s3(
                s3_client=s3_client,
                bucket=bucket,
                key=entry.s3_key,
                data=data,
                content_type=entry.content_type,
                sha256=sha256,
            )
            entry.status = "uploaded"
            entry.error = None
            success_count += 1
            logger.info("Successfully uploaded %s (%d bytes, sha256=%s)", entry.s3_key, entry.byte_count, sha256[:8])
        except Exception as e:
            entry.status = "failed"
            entry.error = str(e)
            failure_count += 1
            logger.error("Failed to process %s: %s", entry.original_url, e)

        # Save progress incrementally to guarantee resumability
        save_manifest(manifest_path, entries)

    logger.info(
        "Upload run finished: %d succeeded (%d already existed/idempotent), %d collisions, %d failed out of %d processed.",
        success_count,
        idempotent_skipped,
        collision_count,
        failure_count,
        len(targets),
    )
    return 1 if failure_count > 0 else 0


def execute_verify(
    manifest_path: Path,
    bucket: str,
    s3_client: Any = None,
    verify_cloudfront: bool = False,
    dry_run: bool = False,
    force: bool = False,
    limit: Optional[int] = None,
    test_mode: bool = False,
) -> int:
    """Verify uploaded assets via HeadObject (size, content-type, SHA-256) and optional CloudFront checks."""
    entries = load_manifest(manifest_path)
    if not entries:
        logger.warning("Manifest is empty or missing at %s.", manifest_path)
        return 1

    targets: List[ManifestEntry] = []
    for e in entries:
        if force or e.status in {"uploaded", "verified"}:
            targets.append(e)

    if limit and limit > 0:
        targets = targets[:limit]

    logger.info("Found %d assets queued for verification.", len(targets))

    # STRICT DRY-RUN: zero HeadObject mutations, zero manifest modifications
    if dry_run:
        for e in targets:
            cf_msg = f" and CloudFront ({e.cloudfront_url})" if verify_cloudfront else ""
            logger.info(
                "[DRY-RUN] Would verify s3://%s/%s (size=%d, sha256=%s)%s",
                bucket,
                e.s3_key,
                e.byte_count,
                e.sha256[:8] if e.sha256 else "none",
                cf_msg,
            )
        logger.info("[DRY-RUN] Verification preview complete for %d items (zero mutation guarantee).", len(targets))
        return 0

    if s3_client is None:
        import boto3
        s3_client = boto3.client("s3")

    verified_count = 0
    sha256_verified_count = 0
    size_verified_count = 0
    failed_count = 0

    for idx, entry in enumerate(targets, start=1):
        logger.debug("[%d/%d] Verifying s3://%s/%s...", idx, len(targets), bucket, entry.s3_key)

        is_valid, err_msg, details = verify_s3_object(
            s3_client=s3_client,
            bucket=bucket,
            key=entry.s3_key,
            expected_size=entry.byte_count if entry.byte_count > 0 else None,
            expected_sha256=entry.sha256 if entry.sha256 else None,
        )

        if not is_valid:
            entry.status = "failed"
            entry.error = err_msg
            failed_count += 1
            logger.error("S3 verification failed for %s: %s", entry.s3_key, err_msg)
            continue

        if details.get("sha256_verified"):
            sha256_verified_count += 1
        if details.get("ContentLength"):
            size_verified_count += 1
            if entry.byte_count == 0:
                entry.byte_count = details["ContentLength"]

        if verify_cloudfront:
            if not entry.cloudfront_url:
                entry.status = "failed"
                entry.error = "CloudFront verification failed: cloudfront_url is empty in manifest"
                failed_count += 1
                logger.error("CloudFront verification failed for %s: cloudfront_url is empty", entry.s3_key)
                continue

            cf_valid, cf_err = verify_cloudfront_object(entry.cloudfront_url, test_mode=test_mode)
            if not cf_valid:
                entry.status = "failed"
                entry.error = f"CloudFront check failed: {cf_err}"
                failed_count += 1
                logger.error("CloudFront verification failed for %s: %s", entry.s3_key, cf_err)
                continue

        entry.status = "verified"
        entry.error = None
        verified_count += 1

    save_manifest(manifest_path, entries)
    logger.info(
        "Verification complete: %d verified (%d SHA-256 integrity verified, %d size verified), %d failed out of %d checked.",
        verified_count,
        sha256_verified_count,
        size_verified_count,
        failed_count,
        len(targets),
    )
    return 1 if failed_count > 0 else 0


def execute_rewrite(
    repo_root: Path,
    manifest_path: Path,
    target_url_type: str = "cloudfront",
    scan_dir: Optional[Path] = None,
    dry_run: bool = False,
    test_mode: bool = False,
) -> int:
    """Rewrite source file references ONLY for verified assets.

    Strictly preserves all surrounding HTML structure, captions, and attributes.
    """
    entries = load_manifest(manifest_path)
    if not entries:
        logger.warning("Manifest is empty or missing at %s.", manifest_path)
        return 1

    # STRICT SAFETY RULE: ONLY rewrite URLs that are explicitly marked 'verified'
    verified_entries = [e for e in entries if e.status == "verified"]

    if not verified_entries:
        logger.warning(
            "No verified entries in manifest to rewrite (total entries: %d). "
            "Run --upload and --verify before rewriting.",
            len(entries),
        )
        return 0

    # Validate destination URLs before source rewriting
    if target_url_type == "cloudfront":
        for e in verified_entries:
            if not e.cloudfront_url:
                logger.error("Cannot rewrite: verified entry %s has empty cloudfront_url.", e.s3_key)
                return 1
            try:
                parsed = urllib.parse.urlsplit(e.cloudfront_url)
                origin_base = f"{parsed.scheme}://{parsed.netloc}"
                validate_asset_base_url(origin_base, test_mode=test_mode)
                for token in FORBIDDEN_PLACEHOLDER_TOKENS:
                    if token in e.cloudfront_url.lower():
                        raise ValueError(f"URL contains forbidden placeholder token '{token}'")
            except Exception as ex:
                logger.error(
                    "Cannot rewrite: verified entry %s has invalid cloudfront_url '%s': %s",
                    e.s3_key,
                    e.cloudfront_url,
                    ex,
                )
                return 1

    # Build replacement mapping: original_url -> target_url
    url_replacements: Dict[str, str] = {}
    for e in verified_entries:
        target = e.s3_url if target_url_type == "s3" else e.cloudfront_url
        url_replacements[e.original_url] = target

    # Group verified entries by source file
    file_to_entries: Dict[str, List[ManifestEntry]] = {}
    for e in verified_entries:
        for f in e.source_files:
            file_to_entries.setdefault(f, []).append(e)

    total_files_modified = 0
    total_replacements = 0

    for rel_path, file_entries in sorted(file_to_entries.items()):
        file_path = repo_root / rel_path
        if not file_path.exists():
            logger.warning("Referenced file does not exist: %s", file_path)
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("Could not read file %s: %s", file_path, e)
            continue

        modified_content = content
        replacements_in_file = 0

        for entry in file_entries:
            orig = entry.original_url
            target = url_replacements[orig]
            if orig in modified_content:
                count = modified_content.count(orig)
                modified_content = modified_content.replace(orig, target)
                replacements_in_file += count

        if replacements_in_file > 0:
            total_replacements += replacements_in_file
            total_files_modified += 1
            if dry_run:
                logger.info(
                    "[DRY-RUN] In %s: would rewrite %d references",
                    rel_path,
                    replacements_in_file,
                )
            else:
                file_path.write_text(modified_content, encoding="utf-8")
                logger.info("Rewrote %d references in %s", replacements_in_file, rel_path)

    prefix = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%sRewrite finished: %d references rewritten across %d files.",
        prefix,
        total_replacements,
        total_files_modified,
    )
    return 0


def execute_reconcile(
    repo_root: Path,
    manifest_path: Path,
    scan_dir: Optional[Path] = None,
) -> int:
    """Compare repository references against manifest across all audit scopes.

    Verifies that every required production asset reference is accounted for in the manifest
    and fully verified. Distinguishes runtime dependencies and historical documentation.
    Returns 0 if clean, 1 if required production asset references remain unresolved.
    """
    logger.info("Running comprehensive audit across repository scopes...")
    audit = run_scoped_audit(repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path)

    entries = load_manifest(manifest_path)
    manifest_by_url: Dict[str, ManifestEntry] = {e.original_url: e for e in entries}

    unverified_in_files: List[Tuple[str, str, str]] = []
    missing_from_manifest: List[Tuple[str, str]] = []

    for url, files in audit.static_assets.items():
        if url in manifest_by_url:
            status = manifest_by_url[url].status
            if status != "verified":
                for f in files:
                    unverified_in_files.append((url, f, status))
        else:
            for f in files:
                missing_from_manifest.append((url, f))

    manifest_failed = [e for e in entries if e.status == "failed"]
    manifest_pending = [e for e in entries if e.status in {"pending", "downloaded", "uploaded"}]
    manifest_verified = [e for e in entries if e.status == "verified"]

    print("\n" + "=" * 80)
    print("         CLOUDINARY MIGRATION AUDIT & RECONCILIATION REPORT")
    print("=" * 80)

    print("\n--- 1. STATIC ASSET INVENTORY (PRODUCTION CONTENT) ---")
    print(f"Total Production Static URLs Detected: {len(audit.static_assets)}")
    print(f"Total Production File Occurrences:     {sum(len(f) for f in audit.static_assets.values())}")
    print(f"Manifest Registered Assets:            {len(entries)}")
    print(f"  - Verified:                          {len(manifest_verified)}")
    print(f"  - Pending / In-Progress:             {len(manifest_pending)}")
    print(f"  - Failed:                            {len(manifest_failed)}")

    print("\n--- 2. RUNTIME DEPENDENCY INVENTORY (SDK, ENV VARS, PACKAGES) ---")
    print(f"Total Runtime Findings:                {len(audit.runtime_dependencies)}")
    pkg_deps = [d for d in audit.runtime_dependencies if d["category"] == "package_dependency"]
    sdk_calls = [d for d in audit.runtime_dependencies if d["category"] == "sdk_call"]
    env_vars = [d for d in audit.runtime_dependencies if d["category"] == "env_var"]
    print(f"  - Dependency Packages:               {len(pkg_deps)}")
    print(f"  - SDK / API Invocations:             {len(sdk_calls)}")
    print(f"  - Environment Variables:             {len(env_vars)}")
    for d in audit.runtime_dependencies[:10]:
        print(f"    * [{d['category']}] {d['file']}:{d['line']} -> {d['snippet']}")

    print("\n--- 3. DOCUMENTATION INVENTORY (HISTORICAL / EXAMPLES) ---")
    print(f"Total Documentation URLs:              {len(audit.documentation_assets)}")
    print(f"Total Documentation Occurrences:       {sum(len(f) for f in audit.documentation_assets.values())}")
    print("  (Historical docs/examples are distinguished from active production assets)")

    print("\n--- 4. POST-REWRITE RECONCILIATION GATE ---")
    is_clean = True

    if audit.static_assets:
        logger.warning(
            "Found %d Cloudinary URLs still present in production static files across %d occurrences.",
            len(audit.static_assets),
            sum(len(f) for f in audit.static_assets.values()),
        )
        is_clean = False

    if unverified_in_files:
        logger.error(
            "Found %d references in production files belonging to unverified manifest entries:",
            len(unverified_in_files),
        )
        for url, f, status in unverified_in_files[:10]:
            logger.error("  [%s] %s in %s", status, url, f)
        is_clean = False

    if missing_from_manifest:
        logger.error(
            "Found %d references in production files that are MISSING from manifest completely:",
            len(missing_from_manifest),
        )
        for url, f in missing_from_manifest[:10]:
            logger.error("  %s in %s", url, f)
        is_clean = False

    if manifest_failed:
        logger.error("Manifest contains %d entries in 'failed' status.", len(manifest_failed))
        for e in manifest_failed[:5]:
            logger.error("  Failed: %s (error: %s)", e.s3_key, e.error)
        is_clean = False

    if is_clean:
        logger.info("SUCCESS: 0 broken or unverified production references remain. Clean reconciliation!")
        return 0
    else:
        logger.error("RECONCILIATION FAILED: Unresolved production asset references remain.")
        return 1


# ==============================================================================
# CLI Entrypoint
# ==============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate static assets from Cloudinary to Amazon S3 + CloudFront.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    ops = parser.add_argument_group("Operations (select one or more)")
    ops.add_argument(
        "--inventory",
        action="store_true",
        help="Scan repository for Cloudinary URLs and produce/update manifest.",
    )
    ops.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions with strict zero-mutation guarantees (no network writes or file edits).",
    )
    ops.add_argument(
        "--upload",
        action="store_true",
        help="Download assets from Cloudinary, compute SHA-256, detect collisions, and upload to S3.",
    )
    ops.add_argument(
        "--verify",
        action="store_true",
        help="Verify uploaded objects in S3 (and CloudFront) by checking HeadObject and SHA-256.",
    )
    ops.add_argument(
        "--rewrite",
        action="store_true",
        help="Rewrite references in source files ONLY for verified manifest assets.",
    )
    ops.add_argument(
        "--reconcile",
        action="store_true",
        help="Compare repository references against manifest across scopes (exit 1 if unresolved).",
    )

    config = parser.add_argument_group("Configuration")
    config.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to migration manifest JSON file (default: docs/migrations/migration-manifest.json).",
    )
    config.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: auto-detected from script location).",
    )
    config.add_argument(
        "--scan-dir",
        type=Path,
        default=None,
        help="Subdirectory to scan/rewrite (default: entire repo root).",
    )
    config.add_argument(
        "--audit-scope",
        choices=["all", "static", "runtime", "docs"],
        default="all",
        help="Scope of audit scan (default: all).",
    )
    config.add_argument(
        "--test-mode",
        action="store_true",
        help="Enable test mode to permit test/mock hostnames for CloudFront base URL.",
    )
    config.add_argument(
        "--bucket",
        type=str,
        default=DEFAULT_BUCKET,
        help="Target AWS S3 bucket name.",
    )
    config.add_argument(
        "--region",
        type=str,
        default=DEFAULT_REGION,
        help="Target AWS region for S3.",
    )
    config.add_argument(
        "--asset-base-url",
        type=str,
        default=DEFAULT_CLOUDFRONT_BASE,
        help="Validated base URL for CloudFront distribution (e.g. https://d3staging.cloudfront.net).",
    )
    config.add_argument(
        "--target-url-type",
        choices=["cloudfront", "s3"],
        default="cloudfront",
        help="URL format to write during HTML rewriting.",
    )
    config.add_argument(
        "--force",
        action="store_true",
        help="Force re-processing of items even if previously completed or colliding.",
    )
    config.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items to process in upload/verify batch.",
    )
    config.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Network timeout for downloads in seconds.",
    )
    config.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts for downloads.",
    )
    config.add_argument(
        "--verify-cloudfront",
        action="store_true",
        help="Perform HTTP HEAD check against CloudFront edge during verification.",
    )
    config.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed verbose debug logging.",
    )

    return parser


def detect_repo_root() -> Path:
    """Detect repository root relative to script location."""
    script_dir = Path(__file__).resolve().parent
    if (script_dir.parent / "frontend").exists() or (script_dir.parent / "backend").exists():
        return script_dir.parent
    return Path.cwd()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    repo_root = (args.repo_root or detect_repo_root()).resolve()
    manifest_path = (args.manifest or (repo_root / DEFAULT_MANIFEST_REL)).resolve()
    test_mode = bool(args.test_mode or (os.getenv("TESTING") == "1"))

    # If no operation flag is given, display help
    has_op = any([
        args.inventory,
        args.dry_run,
        args.upload,
        args.verify,
        args.rewrite,
        args.reconcile,
    ])
    if not has_op:
        parser.print_help()
        return 0

    exit_code = 0

    # 1. Inventory
    if args.inventory:
        code = execute_inventory(
            repo_root=repo_root,
            manifest_path=manifest_path,
            bucket=args.bucket,
            region=args.region,
            cloudfront_base=args.asset_base_url,
            scan_dir=args.scan_dir,
            dry_run=args.dry_run,
            test_mode=test_mode,
            audit_scope=args.audit_scope,
        )
        if code != 0:
            return code

    # 2. Upload
    if args.upload:
        code = execute_upload(
            manifest_path=manifest_path,
            bucket=args.bucket,
            dry_run=args.dry_run,
            force=args.force,
            limit=args.limit,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )
        if code != 0:
            return code

    # 3. Verify
    if args.verify:
        code = execute_verify(
            manifest_path=manifest_path,
            bucket=args.bucket,
            verify_cloudfront=args.verify_cloudfront,
            dry_run=args.dry_run,
            force=args.force,
            limit=args.limit,
            test_mode=test_mode,
        )
        if code != 0:
            return code

    # 4. Rewrite
    if args.rewrite:
        code = execute_rewrite(
            repo_root=repo_root,
            manifest_path=manifest_path,
            target_url_type=args.target_url_type,
            scan_dir=args.scan_dir,
            dry_run=args.dry_run,
            test_mode=test_mode,
        )
        if code != 0:
            return code

    # 5. Reconcile
    if args.reconcile:
        code = execute_reconcile(
            repo_root=repo_root,
            manifest_path=manifest_path,
            scan_dir=args.scan_dir,
        )
        if code != 0:
            exit_code = code

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
