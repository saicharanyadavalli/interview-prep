"""Unit tests for scripts.load_courses utility."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import sys
backend_dir = Path(__file__).resolve().parent.parent.parent
scripts_dir = backend_dir.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from load_courses import load_courses


def test_load_courses_missing_file_raises_error(tmp_path):
    """Verify load_courses raises FileNotFoundError for non-existent json path."""
    with pytest.raises(FileNotFoundError):
        load_courses(json_path=tmp_path / "missing.json")


def test_load_courses_success_with_mock_rds(tmp_path):
    """Verify load_courses parses json and calls rds_client.mutate for each track and lesson."""
    sample_data = [
        {"slug": "intro", "order": 1, "title": "Intro Lesson", "content_markdown": "# Intro", "tasks": ["Task 1"]},
        {"slug": "where", "order": 2, "title": "Where Lesson", "content_markdown": "# Where", "tasks": ["Task 2"]},
    ]
    test_json = tmp_path / "test_lessons.json"
    test_json.write_text(json.dumps(sample_data), encoding="utf-8")

    with patch("load_courses.rds_client.mutate") as mock_mutate:
        result = load_courses(json_path=test_json, track_ids=("sql-course",))
        assert result["synced"] == 2
        assert result["failed"] == 0
        assert result["total"] == 2
        assert mock_mutate.call_count == 2

        # Check call arguments
        sql_query, sql_params = mock_mutate.call_args_list[0][0]
        assert "INSERT INTO course_lessons" in sql_query
        assert sql_params[0] == "sql-course"
        assert sql_params[1] == 1
        assert sql_params[2] == "Intro Lesson"


def test_load_courses_partial_failure_continues_processing(tmp_path):
    """Verify load_courses tracks failures without aborting remaining lessons."""
    sample_data = [
        {"slug": "l1", "order": 1, "title": "Lesson 1", "content_markdown": ""},
        {"slug": "l2", "order": 2, "title": "Lesson 2", "content_markdown": ""},
    ]
    test_json = tmp_path / "test_lessons.json"
    test_json.write_text(json.dumps(sample_data), encoding="utf-8")

    # Fail first call, succeed on second
    with patch("load_courses.rds_client.mutate", side_effect=[Exception("Lock timeout"), 1]):
        result = load_courses(json_path=test_json, track_ids=("sql-course",))
        assert result["synced"] == 1
        assert result["failed"] == 1
        assert result["total"] == 2
