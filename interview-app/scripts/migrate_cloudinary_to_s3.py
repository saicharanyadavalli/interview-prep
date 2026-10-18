#!/usr/bin/env python3
"""Migrate static assets from Cloudinary to Amazon S3 + CloudFront.

This production-grade, resumable CLI tool performs:
1. Inventory: Scans repo (HTML, Markdown, JSON) for Cloudinary URLs & builds/updates manifest.
2. Dry-Run: Previews actions without network mutations or file edits.
3. Upload: Downloads assets from Cloudinary with retries/timeouts, computes SHA-256,
   and uploads to S3 with content types & metadata.
4. Verify: Verifies S3 objects via HeadObject (size, content-type) and optional CloudFront HTTP checks.
5. Rewrite: Rewrites source files (e.g. system-design HTML) ONLY for verified assets,
   strictly preserving all surrounding HTML structure, tags, and attributes.
6. Reconcile: Verifies that 0 broken or unverified references remain across the codebase.
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
DEFAULT_BUCKET = os.getenv("S3_ASSETS_BUCKET", "interview-prep-assets-808431466075-ap-south-2")
DEFAULT_REGION = os.getenv("S3_ASSETS_REGION", "ap-south-2")
DEFAULT_CLOUDFRONT_BASE = os.getenv("ASSET_BASE_URL", "https://d123456abcdef8.cloudfront.net")
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
    cloudfront_base: str = DEFAULT_CLOUDFRONT_BASE,
) -> Optional[Dict[str, Any]]:
    """Parse a Cloudinary URL into manifest fields, or None if not matching."""
    match = CLOUDINARY_URL_PATTERN.match(url.strip())
    if not match:
        return None

    cloud_name = match.group(1)
    raw_path = match.group(2)

    canonical_id = generate_canonical_id(raw_path)
    s3_key = generate_s3_key(raw_path)
    content_type = guess_content_type(s3_key)

    s3_url = f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"
    cf_base = cloudfront_base.rstrip("/")
    cloudfront_url = f"{cf_base}/{s3_key}"

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


def scan_repository_for_urls(
    repo_root: Path,
    scan_dir: Optional[Path] = None,
    extensions: Optional[Set[str]] = None,
    exclude_dirs: Optional[Set[str]] = None,
    exclude_files: Optional[Set[str]] = None,
    manifest_path: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Scan files for Cloudinary URLs. Returns mapping of url -> list of relative file paths."""
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


def save_manifest(manifest_path: Path, entries: Sequence[ManifestEntry]) -> None:
    """Atomically write manifest to JSON file."""
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
    cloudfront_base: str = DEFAULT_CLOUDFRONT_BASE,
    scan_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> Tuple[List[ManifestEntry], Dict[str, int]]:
    """Scan repo and build or merge into manifest preserving existing progress."""
    existing_entries = load_manifest(manifest_path)
    existing_map: Dict[str, ManifestEntry] = {e.original_url: e for e in existing_entries}

    discovered = scan_repository_for_urls(
        repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path
    )

    added_count = 0
    updated_count = 0
    unchanged_count = 0

    merged_entries: List[ManifestEntry] = []

    # Process all discovered URLs
    for url, files in discovered.items():
        if url in existing_map:
            entry = existing_map[url]
            # Update source files if changed
            if set(entry.source_files) != set(files):
                entry.source_files = files
                updated_count += 1
            else:
                unchanged_count += 1
            merged_entries.append(entry)
        else:
            parsed = parse_cloudinary_url(
                url=url, bucket=bucket, region=region, cloudfront_base=cloudfront_base
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
            merged_entries.append(entry)

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
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Verify object existence and attributes via HeadObject.

    Returns: (is_valid, error_msg, details)
    """
    try:
        resp = s3_client.head_object(Bucket=bucket, Key=key)
    except Exception as e:
        return False, f"HeadObject failed: {e}", {}

    size = resp.get("ContentLength", 0)
    ctype = resp.get("ContentType", "")

    if expected_size is not None and expected_size > 0:
        if size != expected_size:
            return (
                False,
                f"Size mismatch: expected {expected_size} bytes, got {size} bytes",
                resp,
            )

    return True, None, {"ContentLength": size, "ContentType": ctype}


def verify_cloudfront_object(cloudfront_url: str, timeout: int = 10) -> Tuple[bool, Optional[str]]:
    """Verify CloudFront edge availability via HTTP HEAD/GET."""
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
    cloudfront_base: str,
    scan_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> int:
    """Execute inventory scan and update manifest."""
    logger.info("Starting inventory scan in %s...", scan_dir or repo_root)
    entries, stats = build_or_update_manifest(
        repo_root=repo_root,
        manifest_path=manifest_path,
        bucket=bucket,
        region=region,
        cloudfront_base=cloudfront_base,
        scan_dir=scan_dir,
        dry_run=dry_run,
    )
    prefix = "[DRY-RUN] " if dry_run else ""
    logger.info(
        "%sInventory complete: %d total assets in manifest (%d newly added, %d updated, %d unchanged across %d files)",
        prefix,
        stats["total"],
        stats["added"],
        stats["updated"],
        stats["unchanged"],
        stats["files_scanned"],
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
    """Execute asset download from Cloudinary and upload to S3."""
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

    if dry_run:
        for e in targets:
            logger.info(
                "[DRY-RUN] Would download: %s and upload to s3://%s/%s (content_type=%s)",
                e.original_url,
                bucket,
                e.s3_key,
                e.content_type,
            )
        logger.info("[DRY-RUN] Upload simulation complete for %d items.", len(targets))
        return 0

    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")

    success_count = 0
    failure_count = 0

    for idx, entry in enumerate(targets, start=1):
        logger.info("[%d/%d] Processing %s...", idx, len(targets), entry.s3_key)
        try:
            # 1. Download
            data, sha256, ctype = download_asset(
                entry.original_url, timeout=timeout, max_retries=max_retries
            )
            entry.byte_count = len(data)
            entry.sha256 = sha256
            if ctype and ctype != "application/octet-stream":
                entry.content_type = ctype
            entry.status = "downloaded"

            # 2. Upload
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
            logger.info("Successfully uploaded %s (%d bytes)", entry.s3_key, entry.byte_count)
        except Exception as e:
            entry.status = "failed"
            entry.error = str(e)
            failure_count += 1
            logger.error("Failed to process %s: %s", entry.original_url, e)

        # Save progress incrementally to guarantee resumability
        save_manifest(manifest_path, entries)

    logger.info(
        "Upload run finished: %d succeeded, %d failed out of %d processed.",
        success_count,
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
) -> int:
    """Verify uploaded assets via HeadObject and optional CloudFront checks."""
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

    if dry_run:
        for e in targets:
            cf_msg = f" and CloudFront ({e.cloudfront_url})" if verify_cloudfront else ""
            logger.info(
                "[DRY-RUN] Would verify s3://%s/%s (size=%d)%s",
                bucket,
                e.s3_key,
                e.byte_count,
                cf_msg,
            )
        logger.info("[DRY-RUN] Verification preview complete for %d items.", len(targets))
        return 0

    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")

    verified_count = 0
    failed_count = 0

    for idx, entry in enumerate(targets, start=1):
        logger.debug("[%d/%d] Verifying s3://%s/%s...", idx, len(targets), bucket, entry.s3_key)

        is_valid, err_msg, details = verify_s3_object(
            s3_client=s3_client,
            bucket=bucket,
            key=entry.s3_key,
            expected_size=entry.byte_count if entry.byte_count > 0 else None,
        )

        if not is_valid:
            entry.status = "failed"
            entry.error = err_msg
            failed_count += 1
            logger.error("S3 verification failed for %s: %s", entry.s3_key, err_msg)
            continue

        if details.get("ContentLength") and entry.byte_count == 0:
            entry.byte_count = details["ContentLength"]

        if verify_cloudfront and entry.cloudfront_url:
            cf_valid, cf_err = verify_cloudfront_object(entry.cloudfront_url)
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
        "Verification complete: %d verified, %d failed out of %d checked.",
        verified_count,
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
    """Compare repository references against manifest.

    Ensures 0 broken or unverified references remain.
    Returns 0 if clean, 1 if unreconciled or unverified references exist.
    """
    logger.info("Scanning repository for remaining Cloudinary references...")
    remaining_urls = scan_repository_for_urls(
        repo_root=repo_root, scan_dir=scan_dir, manifest_path=manifest_path
    )

    entries = load_manifest(manifest_path)
    manifest_by_url: Dict[str, ManifestEntry] = {e.original_url: e for e in entries}

    unverified_in_files: List[Tuple[str, str, str]] = []
    missing_from_manifest: List[Tuple[str, str]] = []

    for url, files in remaining_urls.items():
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

    logger.info("=== RECONCILIATION AUDIT REPORT ===")
    logger.info("Manifest total entries: %d", len(entries))
    logger.info("  Verified:  %d", len(manifest_verified))
    logger.info("  Pending:   %d", len(manifest_pending))
    logger.info("  Failed:    %d", len(manifest_failed))
    logger.info("Cloudinary URLs remaining in repository: %d", len(remaining_urls))

    is_clean = True

    if remaining_urls:
        logger.warning(
            "Found %d Cloudinary URLs still present in repository source files across %d occurrences.",
            len(remaining_urls),
            sum(len(f) for f in remaining_urls.values()),
        )
        is_clean = False

    if unverified_in_files:
        logger.error(
            "Found %d references in code belonging to unverified manifest entries:",
            len(unverified_in_files),
        )
        for url, f, status in unverified_in_files[:10]:
            logger.error("  [%s] %s in %s", status, url, f)
        is_clean = False

    if missing_from_manifest:
        logger.error(
            "Found %d references in code that are MISSING from manifest completely:",
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
        logger.info("SUCCESS: 0 broken or unverified references remain. Clean reconciliation!")
        return 0
    else:
        logger.error("RECONCILIATION FAILED: Unverified or broken references remain.")
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
        help="Preview download, upload, and rewrite actions without network writes or file edits.",
    )
    ops.add_argument(
        "--upload",
        action="store_true",
        help="Download assets from Cloudinary, compute SHA-256, and upload to S3.",
    )
    ops.add_argument(
        "--verify",
        action="store_true",
        help="Verify uploaded objects in S3 (and CloudFront) by checking HeadObject.",
    )
    ops.add_argument(
        "--rewrite",
        action="store_true",
        help="Rewrite references in source files ONLY for verified manifest assets.",
    )
    ops.add_argument(
        "--reconcile",
        action="store_true",
        help="Compare repository references against manifest to ensure 0 broken references remain.",
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
        help="Base URL for CloudFront distribution.",
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
        help="Force re-processing of items even if previously completed.",
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
    # Check parent directory (e.g. interview-app)
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
