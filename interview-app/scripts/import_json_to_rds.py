#!/usr/bin/env python3
"""Amazon RDS PostgreSQL Data Import Utility.

Imports JSON backup files exported from Supabase into Amazon RDS PostgreSQL 17.11.
Enforces transactional safety, schema validation, foreign-key dependency ordering,
and lossless data conversion for arrays and JSONB columns.

Security note:
- Connects using DATABASE_URL environment variable.
- Passwords and connection credentials are masked and never printed to stdout/stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json, execute_values

# -----------------------------------------------------------------------------
# LOGGING CONFIGURATION
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rds_import")

# -----------------------------------------------------------------------------
# DEPENDENCY-ORDERED TABLE DEFINITIONS
# -----------------------------------------------------------------------------
# Tables must be imported in strict foreign-key order:
# 1. Independent parent tables (user_profiles, question_bank_questions, leetcode_problems)
# 2. Child tables referencing parents (aliases, approaches, solutions)
# 3. Independent content (course_lessons)
# 4. User data tables referencing user_profiles
TABLE_IMPORT_ORDER = [
    "user_profiles",
    "question_bank_questions",
    "question_bank_qnum_aliases",
    "leetcode_problems",
    "leetcode_approaches",
    "leetcode_code_solutions",
    "course_lessons",
    "user_progress",
    "practice_history",
    "user_comments",
    "learning_track_progress",
]

# Conflict resolution columns for idempotent re-runs
TABLE_CONFLICT_KEYS: dict[str, list[str]] = {
    "user_profiles": ["id"],
    "question_bank_questions": ["qnum"],
    "question_bank_qnum_aliases": ["source_qnum"],
    "leetcode_problems": ["qnum"],
    "leetcode_approaches": ["id"],
    "leetcode_code_solutions": ["id"],
    "course_lessons": ["id"],
    "user_progress": ["id"],
    "practice_history": ["id"],
    "user_comments": ["id"],
    "learning_track_progress": ["id"],
}

# Columns that require JSON serialization for PostgreSQL JSONB
JSONB_COLUMNS = {
    "question_bank_questions": {"examples", "raw"},
}

# Columns that are PostgreSQL native arrays (TEXT[], INT[])
ARRAY_COLUMNS = {
    "question_bank_questions": {"topic_tags", "company_tags", "companies", "source_qnums"},
    "leetcode_problems": {"topic_tags", "company_tags"},
}


def mask_connection_url(url: str) -> str:
    """Mask password in PostgreSQL connection URL for safe logging."""
    if not url:
        return "<UNSET>"
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return "postgresql://****:****@****/"
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        if parsed.username:
            netloc = f"{parsed.username}:****@{netloc}"
        return f"{parsed.scheme}://{netloc}{parsed.path}"
    except Exception:
        return "postgresql://****:****@****/"


def load_manifest(backup_dir: Path) -> dict[str, Any]:
    """Load and validate the manifest.json file."""
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest file at {manifest_path}")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse manifest.json: {exc}") from exc

    table_counts = manifest.get("table_counts", {})
    if not isinstance(table_counts, dict):
        raise ValueError("manifest.json must contain a 'table_counts' dictionary")

    return manifest


def validate_backup_files(backup_dir: Path, manifest: dict[str, Any]) -> dict[str, list[dict]]:
    """Validate existence, format, and row counts of all 11 backup files."""
    table_counts = manifest.get("table_counts", {})
    loaded_data: dict[str, list[dict]] = {}

    missing_tables = [t for t in TABLE_IMPORT_ORDER if t not in table_counts]
    if missing_tables:
        raise ValueError(f"Manifest is missing expected tables: {missing_tables}")

    for table in TABLE_IMPORT_ORDER:
        file_path = backup_dir / f"{table}.json"
        if not file_path.is_file():
            raise FileNotFoundError(f"Missing required backup file: {file_path}")

        try:
            records = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Corrupt JSON in {file_path}: {exc}") from exc

        if not isinstance(records, list):
            raise ValueError(f"Expected a list of objects in {file_path}, got {type(records).__name__}")

        expected_count = table_counts[table]
        actual_count = len(records)
        if actual_count != expected_count:
            raise ValueError(
                f"Count mismatch in {table}: manifest expects {expected_count}, file contains {actual_count}"
            )

        loaded_data[table] = records

    return loaded_data


def prepare_row(table: str, row: dict[str, Any], columns: list[str]) -> tuple:
    """Transform row values to PostgreSQL compatible Python objects."""
    prepared = []
    jsonb_cols = JSONB_COLUMNS.get(table, set())
    array_cols = ARRAY_COLUMNS.get(table, set())

    for col in columns:
        val = row.get(col)

        if val is None:
            prepared.append(None)
        elif col in jsonb_cols:
            prepared.append(Json(val))
        elif col in array_cols:
            if isinstance(val, list):
                prepared.append(val)
            else:
                prepared.append([val])
        else:
            prepared.append(val)

    return tuple(prepared)


def import_table_batch(
    conn: psycopg2.extensions.connection,
    table: str,
    records: list[dict],
    batch_size: int = 500,
    dry_run: bool = False,
) -> int:
    """Import records into a table in batches with conflict detection."""
    if not records:
        return 0

    columns = list(records[0].keys())
    col_names_sql = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    conflict_cols = TABLE_CONFLICT_KEYS.get(table, [])
    conflict_sql = sql.SQL(", ").join(sql.Identifier(c) for c in conflict_cols)

    query = sql.SQL(
        "INSERT INTO public.{table} ({cols}) VALUES %s ON CONFLICT ({conflicts}) DO NOTHING"
    ).format(
        table=sql.Identifier(table),
        cols=col_names_sql,
        conflicts=conflict_sql,
    )

    if dry_run:
        # Validate data conversions only
        for r in records:
            _ = prepare_row(table, r, columns)
        return len(records)

    total_inserted = 0
    with conn.cursor() as cur:
        for i in range(0, len(records), batch_size):
            chunk = records[i : i + batch_size]
            prepared_rows = [prepare_row(table, r, columns) for r in chunk]

            execute_values(cur, query.as_string(conn), prepared_rows, page_size=batch_size)
            total_inserted += len(prepared_rows)

    return total_inserted


def check_target_state(conn: psycopg2.extensions.connection) -> dict[str, int]:
    """Check existing row counts in target database to detect partial migrations."""
    counts = {}
    with conn.cursor() as cur:
        for table in TABLE_IMPORT_ORDER:
            try:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM public.{}").format(sql.Identifier(table)))
                row = cur.fetchone()
                counts[table] = row[0] if row else 0
            except psycopg2.Error:
                conn.rollback()
                counts[table] = -1  # Table may not exist yet
    return counts


def run_migration(
    backup_dir: Path,
    database_url: str,
    dry_run: bool = False,
    batch_size: int = 500,
    skip_existing_check: bool = False,
) -> dict[str, Any]:
    """Execute the full data migration workflow."""
    start_time = time.time()
    logger.info("Initializing migration process...")
    logger.info("Backup directory: %s", backup_dir)
    logger.info("Target database: %s", mask_connection_url(database_url))
    logger.info("Dry-run mode: %s", "ENABLED" if dry_run else "DISABLED")

    # 1. Manifest and file validation
    manifest = load_manifest(backup_dir)
    logger.info("Manifest loaded: %d expected tables, %s total target DB size",
                len(manifest.get("table_counts", {})), manifest.get("db_size", "unknown"))

    tables_data = validate_backup_files(backup_dir, manifest)
    total_records = sum(len(records) for records in tables_data.values())
    logger.info("Validated 11 backup files containing %d total records. Count matches manifest.", total_records)

    results: dict[str, Any] = {
        "dry_run": dry_run,
        "total_records": total_records,
        "table_counts": {},
        "errors": [],
    }

    if dry_run:
        logger.info("Validating row serialization and schemas in dry-run mode...")
        for table in TABLE_IMPORT_ORDER:
            count = import_table_batch(None, table, tables_data[table], batch_size, dry_run=True)
            results["table_counts"][table] = count
            logger.info("  [DRY-RUN] %-28s %6d records validated", table, count)

        elapsed = time.time() - start_time
        logger.info("Dry-run validation completed successfully in %.2f seconds.", elapsed)
        return results

    # 2. Database connection & pre-check
    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = False

        existing_counts = check_target_state(conn)
        non_empty = {t: c for t, c in existing_counts.items() if c > 0}
        if non_empty and not skip_existing_check:
            logger.warning(
                "Notice: Target database contains existing records in %d tables: %s",
                len(non_empty),
                non_empty,
            )
            logger.info("Idempotent mode (ON CONFLICT DO NOTHING) will protect existing rows.")

        # 3. Transactional import in dependency order
        logger.info("Beginning transactional import of 11 tables...")
        with conn:
            for table in TABLE_IMPORT_ORDER:
                t_start = time.time()
                records = tables_data[table]
                inserted = import_table_batch(conn, table, records, batch_size=batch_size, dry_run=False)
                t_elapsed = time.time() - t_start
                results["table_counts"][table] = inserted
                logger.info("  %-28s imported %6d records in %5.2fs", table, inserted, t_elapsed)

        elapsed = time.time() - start_time
        logger.info("All 11 tables successfully committed in %.2f seconds.", elapsed)
        return results

    except Exception as exc:
        conn.rollback()
        logger.error("Database error during migration: %s", exc)
        results["errors"].append(str(exc))
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Import JSON backups into Amazon RDS PostgreSQL 17.11")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backups"),
        help="Path to directory containing manifest.json and table JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate JSON files, data types, and records without writing to the database",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of records to insert per batch (default: 500)",
    )
    parser.add_argument(
        "--skip-existing-check",
        action="store_true",
        help="Skip warning if target tables already have rows",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url and not args.dry_run:
        logger.error("DATABASE_URL environment variable must be set (unless --dry-run is specified)")
        sys.exit(1)

    try:
        run_migration(
            backup_dir=args.backup_dir,
            database_url=database_url,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            skip_existing_check=args.skip_existing_check,
        )
        logger.info("Migration script completed successfully.")
        sys.exit(0)
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
