"""Unit tests for courses_service course retrieval, SQL seed data, and progress tracking."""

from unittest.mock import patch, MagicMock
from services.courses_service import (
    COURSE_CATALOG,
    _normalize_track_id,
    get_sql_seed_tables,
    fetch_all_courses,
    fetch_course_by_slug,
    record_lesson_completion,
    fetch_course_user_progress,
)


def test_normalize_track_id():
    """Verify course slug normalization handles aliases."""
    assert _normalize_track_id("sql") == "sql-course"
    assert _normalize_track_id("sql-tutorial") == "sql-course"
    assert _normalize_track_id("system_design") == "system-design"
    assert _normalize_track_id("genai_system_design") == "genai-system-design"
    assert _normalize_track_id("ood") == "object-oriented-design"


def test_get_sql_seed_tables_structure():
    """Verify get_sql_seed_tables provides seed schemas and rows for SQL practice tables."""
    tables = get_sql_seed_tables()
    table_names = {t["name"] for t in tables}
    assert "Movies" in table_names
    assert "Boxoffice" in table_names
    assert "Buildings" in table_names
    assert "Employees" in table_names
    assert "Cities" in table_names

    for t in tables:
        assert "schema_sql" in t
        assert "insert_sql" in t
        assert len(t["columns"]) > 0
        assert len(t["rows"]) > 0


def test_fetch_all_courses_returns_catalog(mock_supabase):
    """Verify fetch_all_courses returns all 6 published courses."""
    courses = fetch_all_courses(user_id=None)
    assert len(courses) == 6
    slugs = [c["slug"] for c in courses]
    assert "system-design" in slugs
    assert "sql-course" in slugs


def test_fetch_course_by_slug_sql_course_fallback():
    """Verify fetch_course_by_slug returns SQL course lessons structure."""
    course = fetch_course_by_slug("sql-course", user_id=None)
    assert course is not None
    assert course["slug"] == "sql-course"
    assert len(course["lessons"]) > 0


def test_record_lesson_completion_updates_progress(mock_supabase):
    """Verify record_lesson_completion tracks completion and returns progress percentage."""
    user_id = "test-user-uuid"
    res = record_lesson_completion(user_id, "sql-course", "select_queries_introduction", completed=True)
    assert res["success"] is True
    assert res["completed"] is True
    assert res["course_slug"] == "sql-course"

    prog = fetch_course_user_progress(user_id, "sql-course")
    assert prog is not None
    assert "select_queries_introduction" in prog["completed_lesson_slugs"]
