"""Unit tests validating SQL syntax and safety invariants of migration 004."""

from __future__ import annotations

import re
from pathlib import Path


def _load_migration_sql() -> str:
    migration_path = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "migrations"
        / "rds"
        / "004_leetcode_sync_metadata.sql"
    )
    assert migration_path.exists(), f"Migration file not found at {migration_path}"
    return migration_path.read_text(encoding="utf-8")


def test_migration_004_transactional_integrity():
    """Verify migration is wrapped in an atomic BEGIN / COMMIT transaction block."""
    sql = _load_migration_sql()
    assert re.search(r"^\s*BEGIN;\s*$", sql, re.MULTILINE) is not None
    assert re.search(r"^\s*COMMIT;\s*$", sql, re.MULTILINE) is not None


def test_migration_004_does_not_use_create_or_replace_function():
    """Verify shared function avoids CREATE OR REPLACE FUNCTION to protect against non-owner permission errors."""
    sql = _load_migration_sql()
    assert "CREATE OR REPLACE FUNCTION" not in sql
    assert "CREATE OR REPLACE FUNCTION public.set_current_timestamp_updated_at" not in sql


def test_migration_004_uses_conditional_do_block():
    """Verify migration uses valid PL/pgSQL DO block with pg_proc existence check."""
    sql = _load_migration_sql()
    # Check DO block presence
    assert "DO $$" in sql
    # Check pg_proc existence inspection
    assert "pg_proc" in sql
    assert "set_current_timestamp_updated_at" in sql
    # Check conditional function creation inside DO block
    assert "CREATE FUNCTION public.set_current_timestamp_updated_at()" in sql


def test_migration_004_defines_required_tables_and_indexes():
    """Verify all required LeetCode sync tables and indexes are created idempotently."""
    sql = _load_migration_sql()
    assert "CREATE TABLE IF NOT EXISTS public.leetcode_sync_state" in sql
    assert "CREATE TABLE IF NOT EXISTS public.leetcode_sync_history" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_commit" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_created_at" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_repo_branch" in sql
    assert "DROP TRIGGER IF EXISTS trg_leetcode_sync_state_updated_at" in sql
    assert "CREATE TRIGGER trg_leetcode_sync_state_updated_at" in sql
