#!/usr/bin/env python3
"""Amazon RDS User Profiles Avatar Reconciliation Utility.

Reconciles legacy Cloudinary avatar URLs stored in Amazon RDS PostgreSQL (`user_profiles`)
with new Amazon S3 and CloudFront asset delivery URLs.

Operations:
  --dry-run (default): Scan and preview candidates without database modification.
  --execute --confirm: Execute atomic transaction to update avatar URLs.
  --export-mapping <file.json>: Export audit mapping file for verification or rollback.
  --rollback <file.json> [--confirm]: Restore original avatar URLs from mapping file.

Safety Guardrails:
  - NEVER modifies Google (*.googleusercontent.com) or GitHub (*.githubusercontent.com) avatars.
  - NEVER modifies inline base64 data URIs (data:image/...) or empty/null avatars.
  - STRICTLY mutates ONLY avatar_url and updated_at; never touches email, username, name, or phone.
  - Requires explicit --confirm flag for live executions.
  - Fully transactional: rolls back all operations if any error occurs.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

# Ensure backend directory is in sys.path
script_dir = Path(__file__).parent.resolve()
app_dir = script_dir.parent.resolve()
backend_dir = app_dir / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# Attempt environment variable loading
try:
    from dotenv import load_dotenv

    if (app_dir / ".env").exists():
        load_dotenv(app_dir / ".env")
    elif (backend_dir / ".env").exists():
        load_dotenv(backend_dir / ".env")
    else:
        load_dotenv()
except ImportError:
    pass

try:
    from services import rds_client
except ImportError:
    rds_client = None

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("reconcile_db_avatars")

# -----------------------------------------------------------------------------
# CONSTANTS & CONTRACT DEFAULTS
# -----------------------------------------------------------------------------
DEFAULT_S3_BUCKET = "interview-prep-assets-808431466075-ap-south-2"
DEFAULT_S3_REGION = "ap-south-2"

PRESERVED_DOMAINS = (
    "googleusercontent.com",
    "githubusercontent.com",
    "avatars.githubusercontent.com",
)

SQL_UPDATE_AVATAR = (
    "UPDATE user_profiles SET avatar_url = %s, updated_at = now() WHERE id = %s;"
)

SQL_QUERY_CANDIDATES = (
    "SELECT id, email, username, name, phone, avatar_url, updated_at "
    "FROM user_profiles "
    "WHERE avatar_url ILIKE '%cloudinary%' "
    "ORDER BY id;"
)

SQL_QUERY_ALL = (
    "SELECT id, email, username, name, phone, avatar_url, updated_at "
    "FROM user_profiles "
    "ORDER BY id;"
)


# -----------------------------------------------------------------------------
# SAFETY CLASSIFIERS
# -----------------------------------------------------------------------------
def is_preserved_avatar(url: Optional[str]) -> bool:
    """Return True if avatar URL must be preserved and NEVER modified.

    Preserves:
      - None / empty string / whitespace
      - Inline base64 data URIs ('data:image/...')
      - Google profile avatars ('*.googleusercontent.com')
      - GitHub profile avatars ('*.githubusercontent.com')
    """
    if url is None:
        return True
    clean = str(url).strip()
    if not clean:
        return True

    lower = clean.lower()
    if lower.startswith("data:"):
        return True

    for domain in PRESERVED_DOMAINS:
        if domain in lower:
            return True

    return False


def is_cloudinary_avatar(url: Optional[str]) -> bool:
    """Return True if avatar is hosted on Cloudinary."""
    if not url:
        return False
    return "cloudinary" in str(url).strip().lower()


def should_migrate_avatar(url: Optional[str]) -> bool:
    """Determine whether an avatar URL qualifies for migration to S3/CloudFront.

    Strict guardrail:
      Must contain 'cloudinary' AND must NOT match any preserved patterns.
    """
    if is_preserved_avatar(url):
        return False
    return is_cloudinary_avatar(url)


# -----------------------------------------------------------------------------
# URL MAPPING GENERATION
# -----------------------------------------------------------------------------
def extract_avatar_filename(url: str) -> str:
    """Extract clean filename and extension from a Cloudinary URL or fallback to avatar.png."""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path:
            return "avatar.png"

        raw_name = path.split("/")[-1]
        # Remove query parameters or fragments if present
        raw_name = raw_name.split("?")[0].split("#")[0]

        if "." in raw_name:
            base, ext = raw_name.rsplit(".", 1)
            ext_clean = ext.lower()
            if ext_clean in ("jpg", "jpeg", "png", "webp", "gif", "svg"):
                return f"{base}.{ext_clean}"
            return f"{base}.png"
        return f"{raw_name}.png" if raw_name else "avatar.png"
    except Exception:
        return "avatar.png"


def build_mapped_avatar_url(
    old_url: str,
    user_id: str,
    asset_base_url: Optional[str] = None,
    s3_bucket: Optional[str] = None,
    s3_region: Optional[str] = None,
    manifest_mapping: Optional[Dict[str, str]] = None,
) -> str:
    """Construct destination CloudFront or S3 URL for a migrated avatar.

    Resolution order:
      1. Explicit manifest mapping if provided
      2. CloudFront ASSET_BASE_URL (env or arg) + key schema: avatars/{user_id}/{filename}
      3. Direct S3 URL fallback: https://{bucket}.s3.{region}.amazonaws.com/avatars/{user_id}/{filename}
    """
    # 1. Manifest lookup
    if manifest_mapping and old_url in manifest_mapping:
        return manifest_mapping[old_url]

    # Clean user ID string
    uid_str = str(user_id).strip()
    filename = extract_avatar_filename(old_url)
    s3_key = f"avatars/{uid_str}/{filename}"

    # 2. CloudFront / Custom Base URL
    base_url = (
        asset_base_url
        or os.getenv("ASSET_BASE_URL", "")
    ).strip().rstrip("/")

    if base_url:
        return f"{base_url}/{s3_key}"

    # 3. Direct S3 URL fallback
    bucket = (
        s3_bucket
        or os.getenv("S3_ASSETS_BUCKET", "")
        or DEFAULT_S3_BUCKET
    ).strip()
    region = (
        s3_region
        or os.getenv("S3_ASSETS_REGION", "")
        or DEFAULT_S3_REGION
    ).strip()

    return f"https://{bucket}.s3.{region}.amazonaws.com/{s3_key}"


# -----------------------------------------------------------------------------
# DATABASE OPERATIONS (TRANSACTION-AWARE)
# -----------------------------------------------------------------------------
def fetch_candidate_profiles(
    client: Any = None,
    scan_all: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch user profile rows from RDS.

    By default queries WHERE avatar_url ILIKE '%cloudinary%'.
    If scan_all=True, queries all profiles for complete inventory.
    """
    active_client = client or rds_client
    if not active_client:
        raise RuntimeError("RDS client is not available. Check DATABASE_URL or backend environment.")

    sql = SQL_QUERY_ALL if scan_all else SQL_QUERY_CANDIDATES
    rows = active_client.query(sql, fetch="all")
    return [dict(r) for r in (rows or [])]


@contextmanager
def acquire_db_connection(client: Any = None):
    """Context manager to acquire a database connection from rds_client or connection pool.

    Supports:
      - Direct connection objects (psycopg2 connection or mock connection with cursor & commit)
      - Client with get_connection() (RDSConnectionPoolManager)
      - Client with get_db_pool().get_connection() (rds_client module)
    """
    active_client = client if client is not None else rds_client
    if active_client is None:
        raise RuntimeError("RDS client is not available. Check DATABASE_URL or backend environment.")

    # 1. Direct connection passed (has cursor and commit, but not pool methods)
    if hasattr(active_client, "cursor") and not hasattr(active_client, "get_db_pool") and not hasattr(active_client, "get_connection"):
        yield active_client
        return

    # 2. Connection provider: prioritize get_db_pool (as in rds_client), fallback to get_connection
    conn_ctx = None
    if hasattr(active_client, "get_db_pool"):
        conn_ctx = active_client.get_db_pool().get_connection()
    elif hasattr(active_client, "get_connection"):
        conn_ctx = active_client.get_connection()
    elif hasattr(active_client, "cursor"):
        yield active_client
        return
    else:
        raise RuntimeError(f"Unable to acquire connection from database client: {active_client}")

    with conn_ctx as conn:
        yield conn


def execute_avatar_updates(
    updates: Sequence[Tuple[str, str]],
    client: Any = None,
) -> int:
    """Execute live avatar updates in an explicit, atomic transaction.

    Arguments:
      updates: list of (new_avatar_url, user_id) tuples.
      client: rds_client module, connection pool, or connection object.

    Safety:
      Uses SQL_UPDATE_AVATAR with strict parameterization.
      Rolls back the entire transaction if any update fails.
      Returns number of rows updated.
    """
    if not updates:
        return 0

    with acquire_db_connection(client=client) as conn:
        return _execute_updates_on_connection(conn, updates)


def _execute_updates_on_connection(
    conn: Any,
    updates: Sequence[Tuple[str, str]],
) -> int:
    """Internal helper to execute updates with explicit rollback on error."""
    orig_autocommit = getattr(conn, "autocommit", False)
    conn.autocommit = False
    updated_count = 0

    try:
        with conn.cursor() as cur:
            for new_url, user_id in updates:
                cur.execute(SQL_UPDATE_AVATAR, (new_url, str(user_id)))
                updated_count += 1
        conn.commit()
        return updated_count
    except Exception as exc:
        logger.error("Transaction failed during avatar updates: %s. Rolling back.", exc)
        try:
            conn.rollback()
        except Exception as rb_exc:
            logger.warning("Error during transaction rollback: %s", rb_exc)
        raise
    finally:
        try:
            conn.autocommit = orig_autocommit
        except Exception:
            pass


# -----------------------------------------------------------------------------
# MAPPING EXPORT & ROLLBACK
# -----------------------------------------------------------------------------
def export_mapping_file(
    filepath: Path | str,
    mappings: Sequence[Dict[str, Any]],
    asset_base_url: Optional[str] = None,
    s3_bucket: Optional[str] = None,
    s3_region: Optional[str] = None,
) -> Path:
    """Write reconciliation mapping to a JSON file for audit and rollback."""
    target_path = Path(filepath).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "metadata": {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "generator": "scripts/reconcile_db_avatars.py",
            "total_records": len(mappings),
            "asset_base_url": asset_base_url or os.getenv("ASSET_BASE_URL", ""),
            "s3_bucket": s3_bucket or os.getenv("S3_ASSETS_BUCKET", DEFAULT_S3_BUCKET),
            "s3_region": s3_region or os.getenv("S3_ASSETS_REGION", DEFAULT_S3_REGION),
        },
        "mappings": list(mappings),
    }

    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Successfully exported %d mapping records to %s", len(mappings), target_path)
    return target_path


def load_rollback_mappings(filepath: Path | str) -> List[Dict[str, Any]]:
    """Load and validate rollback mapping JSON file."""
    path = Path(filepath).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Rollback file not found at {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    raw_mappings = data.get("mappings") if isinstance(data, dict) else data

    if not isinstance(raw_mappings, list):
        raise ValueError(f"Invalid rollback file schema: expected list of mappings in {path}")

    valid_mappings: List[Dict[str, Any]] = []
    for idx, item in enumerate(raw_mappings):
        if not isinstance(item, dict):
            raise ValueError(f"Mapping item at index {idx} is not an object.")
        user_id = item.get("id") or item.get("user_id")
        old_url = item.get("old_avatar_url")
        if not user_id or old_url is None:
            raise ValueError(
                f"Mapping item at index {idx} missing required 'id' or 'old_avatar_url'."
            )
        valid_mappings.append({
            "id": str(user_id),
            "old_avatar_url": str(old_url),
            "new_avatar_url": item.get("new_avatar_url", ""),
            "email": item.get("email", ""),
        })

    return valid_mappings


def execute_rollback(
    filepath: Path | str,
    confirm: bool = False,
    client: Any = None,
) -> Dict[str, Any]:
    """Restore original Cloudinary URLs from a rollback mapping file.

    Safety:
      Requires confirm=True to execute live database mutations.
      Runs in transaction with automatic rollback on error.
    """
    records = load_rollback_mappings(filepath)
    stats = {
        "total_records": len(records),
        "executed": False,
        "restored": 0,
    }

    if not confirm:
        print_rollback_preview(records, filepath)
        return stats

    updates = [(r["old_avatar_url"], r["id"]) for r in records]
    restored_count = execute_avatar_updates(updates, client=client)
    stats["executed"] = True
    stats["restored"] = restored_count

    logger.info("Rollback complete. Successfully restored %d avatar URLs in RDS.", restored_count)
    return stats


# -----------------------------------------------------------------------------
# REPORTING & FORMATTING
# -----------------------------------------------------------------------------
def format_summary_table(mappings: Sequence[Dict[str, Any]]) -> str:
    """Format candidate mappings as an ASCII table."""
    if not mappings:
        return "No migratable Cloudinary avatars found."

    header = f"{'USER ID':<38} | {'CURRENT CLOUDINARY URL':<50} | {'MAPPED S3/CLOUDFRONT URL'}"
    separator = "-" * len(header)
    lines = [separator, header, separator]

    for m in mappings:
        uid = str(m["id"])
        old_u = str(m["old_avatar_url"])
        if len(old_u) > 48:
            old_u = old_u[:45] + "..."
        new_u = str(m["new_avatar_url"])
        lines.append(f"{uid:<38} | {old_u:<50} | {new_u}")

    lines.append(separator)
    return "\n".join(lines)


def print_rollback_preview(records: Sequence[Dict[str, Any]], filepath: Path | str) -> None:
    """Print dry-run preview of rollback operations."""
    print("=" * 80)
    print("                      AVATAR ROLLBACK PREVIEW (DRY-RUN)                       ")
    print("=" * 80)
    print(f"Rollback File:   {filepath}")
    print(f"Total Records:   {len(records)}")
    print("Action Required: Pass --confirm to execute live database restoration.")
    print("-" * 80)
    for r in records[:10]:
        print(f"User {r['id']}: restore avatar_url -> {r['old_avatar_url']}")
    if len(records) > 10:
        print(f"... and {len(records) - 10} more records.")
    print("=" * 80)


def print_execution_report(
    mode: str,
    scanned_count: int,
    candidate_mappings: Sequence[Dict[str, Any]],
    preserved_counts: Dict[str, int],
    export_path: Optional[Path | str] = None,
    executed_count: Optional[int] = None,
) -> None:
    """Print formatted reconciliation summary report."""
    print("\n" + "=" * 80)
    print(f"              DATABASE AVATAR RECONCILIATION REPORT ({mode.upper()})             ")
    print("=" * 80)
    print(f"Execution Mode:             {mode}")
    print(f"Total Profiles Scanned:     {scanned_count}")
    print(f"Cloudinary Candidates:      {len(candidate_mappings)}")
    if executed_count is not None:
        print(f"Records Mutated in RDS:     {executed_count}")
    print(f"Preserved Non-Cloudinary:   {sum(preserved_counts.values())}")
    print(f"  - Google Avatars:         {preserved_counts.get('google', 0)}")
    print(f"  - GitHub Avatars:         {preserved_counts.get('github', 0)}")
    print(f"  - Inline Base64 Data:     {preserved_counts.get('inline_data', 0)}")
    print(f"  - Empty / Null Avatars:   {preserved_counts.get('empty', 0)}")
    print(f"  - Other / Preserved:      {preserved_counts.get('other', 0)}")
    if export_path:
        print(f"Exported Mapping File:      {export_path}")
    print("=" * 80)


# -----------------------------------------------------------------------------
# MAIN RECONCILIATION WORKFLOW
# -----------------------------------------------------------------------------
def reconcile_avatars(
    mode: str = "dry-run",
    confirm: bool = False,
    export_path: Optional[Path | str] = None,
    manifest_path: Optional[Path | str] = None,
    asset_base_url: Optional[str] = None,
    s3_bucket: Optional[str] = None,
    s3_region: Optional[str] = None,
    scan_all: bool = False,
    client: Any = None,
) -> Dict[str, Any]:
    """Core reconciliation logic orchestrating candidate scan, URL mapping, and execution."""
    # Safety Check: --execute requires --confirm
    if mode == "execute" and not confirm:
        raise ValueError("CRITICAL: --execute requires explicit --confirm flag to perform database updates.")

    # Load optional manifest mappings
    manifest_map: Dict[str, str] = {}
    if manifest_path:
        mp = Path(manifest_path).resolve()
        if mp.is_file():
            try:
                m_data = json.loads(mp.read_text(encoding="utf-8"))
                manifest_map = m_data.get("url_mappings") or m_data.get("mappings") or {}
                logger.info("Loaded %d manifest mappings from %s", len(manifest_map), mp)
            except Exception as err:
                logger.warning("Could not read manifest file %s: %s", mp, err)

    # 1. Query candidate rows from RDS
    rows = fetch_candidate_profiles(client=client, scan_all=scan_all)

    candidate_mappings: List[Dict[str, Any]] = []
    preserved_counts: Dict[str, int] = {
        "google": 0,
        "github": 0,
        "inline_data": 0,
        "empty": 0,
        "other": 0,
    }

    for row in rows:
        uid = str(row["id"])
        avatar_url = row.get("avatar_url")

        # Classify and enforce preservation guardrails
        if avatar_url is None or str(avatar_url).strip() == "":
            preserved_counts["empty"] += 1
            continue

        raw_url = str(avatar_url).strip()
        lower_url = raw_url.lower()

        if lower_url.startswith("data:"):
            preserved_counts["inline_data"] += 1
            continue

        if "googleusercontent.com" in lower_url:
            preserved_counts["google"] += 1
            continue

        if "githubusercontent.com" in lower_url:
            preserved_counts["github"] += 1
            continue

        if not is_cloudinary_avatar(raw_url):
            preserved_counts["other"] += 1
            continue

        # Valid Cloudinary avatar to reconcile
        new_url = build_mapped_avatar_url(
            old_url=raw_url,
            user_id=uid,
            asset_base_url=asset_base_url,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            manifest_mapping=manifest_map,
        )

        candidate_mappings.append({
            "id": uid,
            "email": row.get("email", ""),
            "username": row.get("username", ""),
            "old_avatar_url": raw_url,
            "new_avatar_url": new_url,
        })

    # Print table of candidate mappings
    print("\n" + format_summary_table(candidate_mappings))

    # Optional export of mappings
    exported_file: Optional[Path] = None
    if export_path:
        exported_file = export_mapping_file(
            filepath=export_path,
            mappings=candidate_mappings,
            asset_base_url=asset_base_url,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
        )

    executed_count = None
    if mode == "execute" and confirm:
        updates = [(m["new_avatar_url"], m["id"]) for m in candidate_mappings]
        executed_count = execute_avatar_updates(updates, client=client)
        logger.info("Successfully migrated %d avatar URLs in RDS.", executed_count)

    print_execution_report(
        mode="EXECUTE" if (mode == "execute" and confirm) else "DRY-RUN",
        scanned_count=len(rows),
        candidate_mappings=candidate_mappings,
        preserved_counts=preserved_counts,
        export_path=exported_file,
        executed_count=executed_count,
    )

    return {
        "mode": mode,
        "scanned": len(rows),
        "candidates": len(candidate_mappings),
        "executed": executed_count if executed_count is not None else 0,
        "mappings": candidate_mappings,
        "preserved_counts": preserved_counts,
        "export_file": str(exported_file) if exported_file else None,
    }


# -----------------------------------------------------------------------------
# CLI ENTRYPOINT
# -----------------------------------------------------------------------------
def build_cli_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with all required migration and rollback flags."""
    parser = argparse.ArgumentParser(
        description="Amazon RDS User Profiles Avatar Reconciliation Tool (Cloudinary -> S3/CloudFront)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Preview candidate avatars and mappings without database modifications (default mode).",
    )
    mode_group.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute live database updates. Requires --confirm flag for safety.",
    )
    mode_group.add_argument(
        "--rollback",
        metavar="MAPPING_JSON",
        type=str,
        help="Restore original avatar URLs from an exported rollback mapping JSON file.",
    )

    parser.add_argument(
        "--confirm",
        action="store_true",
        default=False,
        help="Explicit confirmation required to perform live updates or live rollback.",
    )
    parser.add_argument(
        "--export-mapping",
        metavar="OUTPUT_JSON",
        type=str,
        help="Export candidate old-to-new URL mappings to a JSON file for audit or rollback.",
    )
    parser.add_argument(
        "--manifest",
        metavar="MANIFEST_JSON",
        type=str,
        help="Path to migration manifest JSON file (optional).",
    )
    parser.add_argument(
        "--asset-base-url",
        type=str,
        help="CloudFront asset delivery origin (defaults to ASSET_BASE_URL env var).",
    )
    parser.add_argument(
        "--s3-bucket",
        type=str,
        help=f"Target S3 bucket name (defaults to {DEFAULT_S3_BUCKET}).",
    )
    parser.add_argument(
        "--s3-region",
        type=str,
        help=f"Target AWS region (defaults to {DEFAULT_S3_REGION}).",
    )
    parser.add_argument(
        "--scan-all",
        action="store_true",
        default=False,
        help="Scan entire user_profiles table (instead of filtering by ILIKE '%%cloudinary%%').",
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        if args.rollback:
            logger.info("Starting rollback operation using mapping file: %s", args.rollback)
            execute_rollback(
                filepath=args.rollback,
                confirm=args.confirm,
            )
            return 0

        # Execute or Dry-Run
        mode = "execute" if args.execute else "dry-run"
        if mode == "execute" and not args.confirm:
            logger.error("Safety abort: --execute requires explicit --confirm flag to prevent accidental execution.")
            print("\n[ERROR] --execute requires explicit --confirm flag to modify production records in RDS.\n")
            return 1

        reconcile_avatars(
            mode=mode,
            confirm=args.confirm,
            export_path=args.export_mapping,
            manifest_path=args.manifest,
            asset_base_url=args.asset_base_url,
            s3_bucket=args.s3_bucket,
            s3_region=args.s3_region,
            scan_all=args.scan_all,
        )
        return 0
    except Exception as exc:
        logger.error("Reconciliation failed: %s", exc)
        print(f"\n[FATAL ERROR] {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
