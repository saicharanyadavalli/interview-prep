"""Integration tests for all /courses endpoints."""

from fastapi.testclient import TestClient


def test_list_courses_unauthenticated(unauth_client: TestClient, mock_supabase):
    """Verify GET /courses lists all courses for anonymous callers."""
    res = unauth_client.get("/courses")
    assert res.status_code == 200
    courses = res.json()
    assert len(courses) == 6
    assert any(c["slug"] == "sql-course" for c in courses)


def test_get_course_detail_sql_course(unauth_client: TestClient):
    """Verify GET /courses/{slug} returns course details and lessons."""
    res = unauth_client.get("/courses/sql-course")
    assert res.status_code == 200
    data = res.json()
    assert data["slug"] == "sql-course"
    assert "lessons" in data
    assert len(data["lessons"]) > 0


def test_get_course_detail_not_found(unauth_client: TestClient):
    """Verify GET /courses/{slug} returns 404 for unknown course."""
    res = unauth_client.get("/courses/non-existent-slug")
    assert res.status_code == 404


def test_get_course_seed_tables(unauth_client: TestClient):
    """Verify GET /courses/{slug}/seed-tables returns SQL seed definitions."""
    res = unauth_client.get("/courses/sql-course/seed-tables")
    assert res.status_code == 200
    data = res.json()
    assert data["course_slug"] == "sql-course"
    assert len(data["tables"]) > 0
    table_names = [t["name"] for t in data["tables"]]
    assert "Movies" in table_names


def test_get_lesson_detail(unauth_client: TestClient):
    """Verify GET /courses/{course_slug}/lessons/{lesson_slug} returns lesson markdown and navigation."""
    res = unauth_client.get("/courses/sql-course/lessons/select_queries_introduction")
    assert res.status_code == 200
    data = res.json()
    assert data["slug"] == "select_queries_introduction"
    assert "content_markdown" in data


def test_complete_lesson_authenticated(client: TestClient, mock_supabase):
    """Verify POST /courses/{course_slug}/lessons/{lesson_slug}/complete records completion."""
    res = client.post(
        "/courses/sql-course/lessons/select_queries_introduction/complete",
        json={"completed": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["completed"] is True
    assert "course_progress" in data


def test_get_course_progress_authenticated(client: TestClient, mock_supabase):
    """Verify GET /courses/{course_slug}/progress returns user completion list."""
    # First mark a lesson complete
    client.post(
        "/courses/sql-course/lessons/select_queries_introduction/complete",
        json={"completed": True},
    )

    res = client.get("/courses/sql-course/progress")
    assert res.status_code == 200
    data = res.json()
    assert data["course_slug"] == "sql-course"
    assert "completed_lesson_slugs" in data
    assert "select_queries_introduction" in data["completed_lesson_slugs"]
