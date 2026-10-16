"""Integration tests for /progress endpoints (update, stats summary, status, and delete)."""

from unittest.mock import patch
from fastapi.testclient import TestClient


def test_update_progress_solved_success(client: TestClient, mock_supabase):
    """Verify POST /progress/update sets is_solved to True."""
    payload = {
        "qnum": 1,
        "is_solved": True,
    }
    res = client.post("/progress/update", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["is_solved"] is True
    assert data["qnum"] == 1


def test_update_progress_by_question_id(client: TestClient, mock_supabase):
    """Verify POST /progress/update resolves question_id to qnum."""
    with patch("routes.progress.find_qnum_by_question_id", return_value=1):
        payload = {
            "question_id": "two-sum",
            "is_solved": True,
        }
        res = client.post("/progress/update", json=payload)
        assert res.status_code == 200
        assert res.json()["qnum"] == 1


def test_update_progress_missing_fields_returns_422(client: TestClient):
    """Verify POST /progress/update returns 422 when neither solved nor revisit provided."""
    payload = {"qnum": 1}
    res = client.post("/progress/update", json=payload)
    assert res.status_code == 422


def test_get_user_progress_full_and_summary(client: TestClient, mock_supabase):
    """Verify GET /progress/user returns user progress stats and topic breakdown."""
    mock_supabase.set_table_data("user_progress", [
        {"qnum": 1, "is_solved": True, "is_revisit": False, "updated_at": "2026-09-01T00:00:00Z"},
        {"qnum": 2, "is_solved": False, "is_revisit": True, "updated_at": "2026-09-01T00:00:00Z"},
    ])

    # Test full breakdown
    res = client.get("/progress/user")
    assert res.status_code == 200
    data = res.json()
    assert "stats" in data
    assert data["stats"]["total_attempted"] == 2
    assert data["stats"]["solved_count"] == 1
    assert data["stats"]["revisit_count"] == 1

    # Test summary_only=True
    res_summary = client.get("/progress/user?summary_only=true")
    assert res_summary.status_code == 200
    assert res_summary.json()["stats"]["total_attempted"] == 2


def test_get_question_progress_status(client: TestClient, mock_supabase):
    """Verify GET /progress/status/{qnum} returns status for single question."""
    mock_supabase.set_table_data("user_progress", [
        {"qnum": 1, "is_solved": True, "is_revisit": False}
    ])

    res = client.get("/progress/status/1")
    assert res.status_code == 200
    data = res.json()
    assert data["qnum"] == 1
    assert data["is_solved"] is True
    assert data["revisit"] is False


def test_clear_question_progress(client: TestClient, mock_supabase):
    """Verify DELETE /progress/{qnum} resets progress for question."""
    res = client.delete("/progress/1")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["qnum"] == 1


def test_clear_question_progress_invalid_qnum_returns_422(client: TestClient):
    """Verify DELETE /progress/{qnum} returns 422 when qnum <= 0."""
    res = client.delete("/progress/0")
    assert res.status_code == 422
