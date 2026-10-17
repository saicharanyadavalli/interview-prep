"""Unit and integration test suite for RDS PostgreSQL migration scripts."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to sys.path
import sys
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_json_to_rds import (
    TABLE_IMPORT_ORDER,
    TABLE_CONFLICT_KEYS,
    JSONB_COLUMNS,
    ARRAY_COLUMNS,
    load_manifest,
    validate_backup_files,
    prepare_row,
    mask_connection_url,
    run_migration,
)
from verify_rds_migration import (
    EXPECTED_TABLES,
    EXPECTED_PRIMARY_KEYS,
)

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "backups"


class TestManifestAndValidation:
    """Tests for manifest loading and backup file verification."""

    def test_load_manifest_valid(self):
        """Verify load_manifest parses manifest.json correctly."""
        manifest = load_manifest(BACKUP_DIR)
        assert "table_counts" in manifest
        assert len(manifest["table_counts"]) == 11
        assert manifest["table_counts"]["user_profiles"] == 13
        assert manifest["table_counts"]["question_bank_questions"] == 1081

    def test_load_manifest_missing_file_raises(self, tmp_path):
        """Verify FileNotFoundError is raised when manifest is missing."""
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path)

    def test_load_manifest_invalid_json(self, tmp_path):
        """Verify ValueError is raised when manifest has invalid JSON."""
        bad_manifest = tmp_path / "manifest.json"
        bad_manifest.write_text("invalid json content", encoding="utf-8")
        with pytest.raises(ValueError):
            load_manifest(tmp_path)

    def test_validate_backup_files_success(self):
        """Verify all 11 backup files exist and match manifest counts."""
        manifest = load_manifest(BACKUP_DIR)
        data = validate_backup_files(BACKUP_DIR, manifest)
        assert len(data) == 11
        assert sum(len(rows) for rows in data.values()) == 26910

    def test_validate_backup_files_count_mismatch(self, tmp_path):
        """Verify ValueError is raised if a file contains fewer rows than manifest."""
        manifest = {"table_counts": {t: 5 for t in TABLE_IMPORT_ORDER}}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for t in TABLE_IMPORT_ORDER:
            # Create files with only 2 rows instead of 5
            (tmp_path / f"{t}.json").write_text(json.dumps([{"id": 1}, {"id": 2}]), encoding="utf-8")

        with pytest.raises(ValueError, match="Count mismatch"):
            validate_backup_files(tmp_path, manifest)

    def test_validate_backup_files_missing_table_file(self, tmp_path):
        """Verify FileNotFoundError is raised when a required backup file is missing."""
        manifest = {"table_counts": {t: 1 for t in TABLE_IMPORT_ORDER}}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        # Only create 1 file, leaving 10 missing
        (tmp_path / "user_profiles.json").write_text(json.dumps([{"id": "1"}]), encoding="utf-8")

        with pytest.raises(FileNotFoundError):
            validate_backup_files(tmp_path, manifest)


class TestDataMarshallingAndSecurity:
    """Tests for safe data marshalling and connection masking."""

    def test_mask_connection_url(self):
        """Verify password is never exposed in masked URL."""
        secret_url = "postgresql://test_user:synthetic_dummy_pw@db.example.invalid:5432/interview_prep_test_db"
        masked = mask_connection_url(secret_url)
        assert "synthetic_dummy_pw" not in masked
        assert "****" in masked
        assert "test_user" in masked
        assert "db.example.invalid:5432" in masked
        assert "interview_prep_test_db" in masked

    def test_mask_connection_url_empty_or_invalid(self):
        """Verify empty and invalid URLs are handled safely."""
        assert mask_connection_url("") == "<UNSET>"
        assert mask_connection_url("not a url") == "postgresql://****:****@****/"

    def test_prepare_row_jsonb_and_arrays(self):
        """Verify JSONB columns are wrapped in Json adapter and arrays are preserved."""
        table = "question_bank_questions"
        sample_row = {
            "qnum": 1,
            "question_id": "q1",
            "problem_name": "Two Sum",
            "difficulty": "Easy",
            "examples": [{"input": "[2,7,11,15], 9", "output": "[0,1]"}],
            "topic_tags": ["Array", "Hash Table"],
            "raw": {"meta": "val"},
            "primary_company": "Amazon",
            "companies": ["Amazon", "Google"],
            "company_count": 2,
            "source_qnums": [1, 2],
            "statement_text": "Sample text",
        }
        cols = ["qnum", "examples", "topic_tags", "raw", "companies", "source_qnums", "statement_text"]
        result = prepare_row(table, sample_row, cols)

        assert len(result) == len(cols)
        assert result[0] == 1  # qnum
        # examples is Json adapter
        assert hasattr(result[1], "adapted")
        # topic_tags is list
        assert result[2] == ["Array", "Hash Table"]
        # raw is Json adapter
        assert hasattr(result[3], "adapted")
        # companies is list
        assert result[4] == ["Amazon", "Google"]
        # source_qnums is list
        assert result[5] == [1, 2]
        # statement_text is str
        assert result[6] == "Sample text"

    def test_prepare_row_null_handling(self):
        """Verify None values remain None."""
        table = "leetcode_problems"
        row = {"qnum": 1, "rating": None, "title": "Test"}
        result = prepare_row(table, row, ["qnum", "rating", "title"])
        assert result[1] is None


class TestDryRunExecution:
    """Tests for dry-run validation without database writes."""

    def test_run_migration_dry_run_success(self):
        """Verify dry-run mode completes validation for all 26,910 rows."""
        res = run_migration(
            backup_dir=BACKUP_DIR,
            database_url="",
            dry_run=True,
        )
        assert res["dry_run"] is True
        assert res["total_records"] == 26910
        assert len(res["table_counts"]) == 11
        assert res["table_counts"]["user_profiles"] == 13
        assert res["table_counts"]["leetcode_code_solutions"] == 15747
        assert len(res["errors"]) == 0


class TestSchemaConstraintsAndDependencies:
    """Tests checking dependency order and constraint coverage."""

    def test_dependency_order_completeness(self):
        """Verify all expected tables are in import order and have conflict keys."""
        assert set(TABLE_IMPORT_ORDER) == set(EXPECTED_TABLES)
        for t in TABLE_IMPORT_ORDER:
            assert t in TABLE_CONFLICT_KEYS
            assert len(TABLE_CONFLICT_KEYS[t]) >= 1
            assert t in EXPECTED_PRIMARY_KEYS

    def test_foreign_key_dependency_hierarchy(self):
        """Ensure parent tables precede child tables in TABLE_IMPORT_ORDER."""
        # user_profiles must precede all user activity tables
        user_idx = TABLE_IMPORT_ORDER.index("user_profiles")
        for user_child in ["user_progress", "practice_history", "user_comments", "learning_track_progress"]:
            child_idx = TABLE_IMPORT_ORDER.index(user_child)
            assert user_idx < child_idx, f"{user_child} must be imported after user_profiles"

        # question_bank_questions must precede aliases
        qb_idx = TABLE_IMPORT_ORDER.index("question_bank_questions")
        alias_idx = TABLE_IMPORT_ORDER.index("question_bank_qnum_aliases")
        assert qb_idx < alias_idx

        # leetcode_problems must precede approaches and solutions
        lc_idx = TABLE_IMPORT_ORDER.index("leetcode_problems")
        app_idx = TABLE_IMPORT_ORDER.index("leetcode_approaches")
        sol_idx = TABLE_IMPORT_ORDER.index("leetcode_code_solutions")
        assert lc_idx < app_idx
        assert lc_idx < sol_idx
