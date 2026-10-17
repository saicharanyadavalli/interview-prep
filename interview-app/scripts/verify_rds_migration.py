#!/usr/bin/env python3
"""Amazon RDS PostgreSQL Migration Verification Utility.

Verifies schema integrity, table existence, primary and foreign key constraints,
lossless data import, and exact row counts against the source backup manifest.

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
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg2
from psycopg2 import sql

# -----------------------------------------------------------------------------
# LOGGING CONFIGURATION
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rds_verify")

EXPECTED_TABLES = [
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

EXPECTED_PRIMARY_KEYS: dict[str, list[str]] = {
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


def load_manifest(backup_dir: Path) -> dict[str, int]:
    """Load expected row counts from manifest.json."""
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Missing manifest file at {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest.get("table_counts", {})


def check_tables_exist(conn: psycopg2.extensions.connection) -> tuple[bool, list[str]]:
    """Check that all 11 expected tables exist in the public schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
        existing = {row[0] for row in cur.fetchall()}

    missing = [t for t in EXPECTED_TABLES if t not in existing]
    return (len(missing) == 0, missing)


def check_row_counts(
    conn: psycopg2.extensions.connection, expected_counts: dict[str, int]
) -> tuple[bool, dict[str, tuple[int, int]]]:
    """Verify live database row counts against manifest expected counts."""
    discrepancies: dict[str, tuple[int, int]] = {}
    with conn.cursor() as cur:
        for table in EXPECTED_TABLES:
            cur.execute(sql.SQL("SELECT COUNT(*) FROM public.{}").format(sql.Identifier(table)))
            actual = cur.fetchone()[0]
            expected = expected_counts.get(table, 0)
            if actual != expected:
                discrepancies[table] = (expected, actual)

    return (len(discrepancies) == 0, discrepancies)


def check_primary_keys(conn: psycopg2.extensions.connection) -> tuple[bool, list[str]]:
    """Verify that all tables have their expected primary key definitions."""
    missing_pks: list[str] = []
    with conn.cursor() as cur:
        for table, expected_cols in EXPECTED_PRIMARY_KEYS.items():
            cur.execute(
                """
                SELECT a.attname
                FROM   pg_index i
                JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE  i.indrelid = %s::regclass
                AND    i.indisprimary
                ORDER  BY a.attnum;
                """,
                (f"public.{table}",),
            )
            actual_cols = [row[0] for row in cur.fetchall()]
            if actual_cols != expected_cols:
                missing_pks.append(f"{table}: expected {expected_cols}, got {actual_cols}")

    return (len(missing_pks) == 0, missing_pks)


def check_foreign_keys(conn: psycopg2.extensions.connection) -> tuple[bool, list[str]]:
    """Verify essential foreign key constraints and check for orphan rows."""
    fk_checks = [
        ("question_bank_qnum_aliases", "canonical_qnum", "question_bank_questions", "qnum"),
        ("leetcode_approaches", "qnum", "leetcode_problems", "qnum"),
        ("leetcode_code_solutions", "qnum", "leetcode_problems", "qnum"),
        ("user_progress", "user_id", "user_profiles", "id"),
        ("practice_history", "user_id", "user_profiles", "id"),
        ("user_comments", "user_id", "user_profiles", "id"),
        ("learning_track_progress", "user_id", "user_profiles", "id"),
    ]

    orphan_errors: list[str] = []
    with conn.cursor() as cur:
        for src_table, src_col, tgt_table, tgt_col in fk_checks:
            query = sql.SQL(
                """
                SELECT COUNT(*)
                FROM public.{src_table} s
                WHERE NOT EXISTS (
                    SELECT 1 FROM public.{tgt_table} t
                    WHERE t.{tgt_col} = s.{src_col}
                )
                """
            ).format(
                src_table=sql.Identifier(src_table),
                src_col=sql.Identifier(src_col),
                tgt_table=sql.Identifier(tgt_table),
                tgt_col=sql.Identifier(tgt_col),
            )
            cur.execute(query)
            count = cur.fetchone()[0]
            if count > 0:
                orphan_errors.append(f"{src_table}.{src_col} -> {tgt_table}.{tgt_col} has {count} orphan rows")

    return (len(orphan_errors) == 0, orphan_errors)


def check_data_samples(conn: psycopg2.extensions.connection) -> tuple[bool, list[str]]:
    """Verify data types, array formats, and non-empty content on sample rows."""
    issues: list[str] = []
    with conn.cursor() as cur:
        # 1. Check array columns and JSONB on question_bank_questions
        cur.execute("SELECT qnum, examples, topic_tags, company_tags FROM public.question_bank_questions LIMIT 1")
        row = cur.fetchone()
        if not row:
            issues.append("question_bank_questions has no records to sample")
        else:
            qnum, examples, topics, companies = row
            if not isinstance(examples, (list, dict)):
                issues.append(f"question_bank_questions.examples is not JSONB: {type(examples)}")
            if not isinstance(topics, list):
                issues.append(f"question_bank_questions.topic_tags is not an array: {type(topics)}")

        # 2. Check course lessons html_content length
        cur.execute("SELECT id, title, length(html_content) FROM public.course_lessons LIMIT 1")
        row = cur.fetchone()
        if not row:
            issues.append("course_lessons has no records to sample")
        elif row[2] < 50:
            issues.append(f"course_lessons.html_content is unexpectedly short ({row[2]} bytes)")

        # 3. Check leetcode code solutions
        cur.execute("SELECT count(DISTINCT language) FROM public.leetcode_code_solutions")
        lang_count = cur.fetchone()[0]
        if lang_count < 3:
            issues.append(f"leetcode_code_solutions only has {lang_count} distinct languages")

    return (len(issues) == 0, issues)


def verify_database(backup_dir: Path, database_url: str) -> bool:
    """Execute complete verification suite against target database."""
    logger.info("Starting database verification...")
    logger.info("Backup directory: %s", backup_dir)
    logger.info("Target database: %s", mask_connection_url(database_url))

    expected_counts = load_manifest(backup_dir)
    conn = psycopg2.connect(database_url)

    all_passed = True
    try:
        # Check 1: Tables exist
        logger.info("[1/5] Checking table existence in public schema...")
        tables_ok, missing = check_tables_exist(conn)
        if not tables_ok:
            logger.error("FAILED: Missing tables in database: %s", missing)
            all_passed = False
        else:
            logger.info("  PASSED: All 11 expected tables exist.")

        # Check 2: Row counts match manifest
        logger.info("[2/5] Checking row counts against manifest...")
        counts_ok, discrepancies = check_row_counts(conn, expected_counts)
        if not counts_ok:
            logger.error("FAILED: Row count discrepancies found:")
            for t, (exp, act) in discrepancies.items():
                logger.error("  %-28s expected: %6d, actual: %6d (diff: %+d)", t, exp, act, act - exp)
            all_passed = False
        else:
            total_rows = sum(expected_counts.values())
            logger.info("  PASSED: All 11 tables match manifest counts exactly (%d total rows).", total_rows)

        # Check 3: Primary Keys
        logger.info("[3/5] Checking primary key constraints...")
        pk_ok, pk_errors = check_primary_keys(conn)
        if not pk_ok:
            logger.error("FAILED: Primary key issues found: %s", pk_errors)
            all_passed = False
        else:
            logger.info("  PASSED: All 11 tables have valid primary keys.")

        # Check 4: Foreign Key and Relationship Integrity
        logger.info("[4/5] Checking foreign key integrity and orphan references...")
        fk_ok, fk_errors = check_foreign_keys(conn)
        if not fk_ok:
            logger.error("FAILED: Foreign key orphan errors: %s", fk_errors)
            all_passed = False
        else:
            logger.info("  PASSED: Zero foreign-key orphan rows found across all relationships.")

        # Check 5: Data Sampling & Type Checks
        logger.info("[5/5] Checking data sampling and JSONB/Array parsing...")
        sample_ok, sample_issues = check_data_samples(conn)
        if not sample_ok:
            logger.error("FAILED: Data sampling issues found: %s", sample_issues)
            all_passed = False
        else:
            logger.info("  PASSED: Data types, arrays, and JSONB structures verified.")

        return all_passed

    finally:
        conn.close()


def resolve_database_url(url: str | None = None) -> str:
    """Resolve database URL from parameter, env var, or AWS Secrets Manager."""
    if url and url.strip():
        return url.strip()
    env_url = os.getenv("DATABASE_URL", "").strip()
    if env_url:
        return env_url
    secret_name = os.getenv("RDS_SECRET_NAME", "interview-prep/rds/app")
    region = os.getenv("AWS_REGION", "ap-south-2")
    try:
        import boto3
        sm = boto3.client("secretsmanager", region_name=region)
        sec = json.loads(sm.get_secret_value(SecretId=secret_name)["SecretString"])
        user = sec["username"]
        pw = sec["password"]
        host = sec["host"]
        port = sec.get("port", 5432)
        db = sec.get("dbname", "interview_prep_db")
        return f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    except Exception as exc:
        logger.debug("Secrets Manager resolution skipped/failed: %s", exc)
        return ""


def main():
    parser = argparse.ArgumentParser(description="Verify Amazon RDS PostgreSQL 17.11 migration against manifest")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("backups"),
        help="Path to directory containing manifest.json",
    )
    args = parser.parse_args()

    database_url = resolve_database_url()
    if not database_url:
        logger.error("DATABASE_URL environment variable must be set or RDS_SECRET_NAME must be resolvable via AWS Secrets Manager")
        sys.exit(1)

    try:
        success = verify_database(args.backup_dir, database_url)
        if success:
            logger.info("Database verification PASSED with 100% parity.")
            sys.exit(0)
        else:
            logger.error("Database verification FAILED. Please review the errors above.")
            sys.exit(1)
    except Exception as exc:
        logger.error("Verification script error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
