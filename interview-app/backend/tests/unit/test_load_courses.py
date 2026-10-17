"""Unit tests for scripts.load_courses utility."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

import sys
backend_dir = Path(__file__).resolve().parent.parent.parent
scripts_dir = backend_dir.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from load_courses import load_courses, validate_lesson_data


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


def test_validate_lesson_data_valid_structure():
    """Verify validate_lesson_data returns no errors for well-formed lesson records."""
    lessons = [
        {"order": 1, "title": "Lesson 1"},
        {"order": 2, "title": "Lesson 2"},
    ]
    errors = validate_lesson_data(lessons)
    assert errors == []


def test_validate_lesson_data_detects_duplicate_order_and_empty_title():
    """Verify validate_lesson_data detects duplicate orders and missing/empty titles."""
    lessons = [
        {"order": 1, "title": "Lesson 1"},
        {"order": 1, "title": ""},  # duplicate order and empty title
        {"order": "invalid", "title": "Lesson 3"},  # non-integer order
    ]
    errors = validate_lesson_data(lessons)
    assert len(errors) == 3
    assert any("Duplicate order 1" in e for e in errors)
    assert any("missing or empty title" in e for e in errors)
    assert any("invalid or missing 'order'" in e for e in errors)


def test_load_courses_dry_run_does_not_mutate_rds(tmp_path):
    """Verify dry_run=True logs actions and does not invoke rds_client.mutate."""
    sample_data = [
        {"order": 1, "title": "Lesson 1", "content_markdown": "Test"},
        {"order": 2, "title": "Lesson 2", "content_markdown": "Test 2"},
    ]
    test_json = tmp_path / "test_lessons.json"
    test_json.write_text(json.dumps(sample_data), encoding="utf-8")

    with patch("load_courses.rds_client.mutate") as mock_mutate:
        result = load_courses(json_path=test_json, track_ids=("sql-course",), dry_run=True)
        assert result["synced"] == 2
        assert result["failed"] == 0
        assert mock_mutate.call_count == 0


def test_load_courses_validate_only_mode(tmp_path):
    """Verify validate_only=True returns valid status without mutating database."""
    sample_data = [
        {"order": 1, "title": "Valid Lesson 1"},
    ]
    test_json = tmp_path / "test_lessons.json"
    test_json.write_text(json.dumps(sample_data), encoding="utf-8")

    with patch("load_courses.rds_client.mutate") as mock_mutate:
        result = load_courses(json_path=test_json, validate_only=True)
        assert result["synced"] == 1
        assert result["failed"] == 0
        assert mock_mutate.call_count == 0


def test_load_courses_malformed_json_raises_value_error(tmp_path):
    """Verify malformed JSON in course file raises ValueError."""
    test_json = tmp_path / "malformed.json"
    test_json.write_text("{ not valid json: }", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed JSON in course file"):
        load_courses(json_path=test_json)
