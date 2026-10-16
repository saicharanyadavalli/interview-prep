"""Integration tests for /comments user notes endpoints."""

from unittest.mock import patch
from fastapi.testclient import TestClient


def test_add_comment_success(client: TestClient, mock_supabase):
    """Verify POST /comments/add saves a new question comment."""
    payload = {
        "qnum": 1,
        "comment_text": "Remember to handle edge case of empty list.",
    }
    res = client.post("/comments/add", json=payload)
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_add_comment_by_question_id(client: TestClient, mock_supabase):
    """Verify POST /comments/add resolves question_id to qnum."""
    with patch("routes.comments.find_qnum_by_question_id", return_value=1):
        payload = {
            "question_id": "two-sum",
            "comment_text": "Great problem for two-pointer practice.",
        }
        res = client.post("/comments/add", json=payload)
        assert res.status_code == 200
        assert res.json()["success"] is True


def test_get_comments_for_question(client: TestClient, mock_supabase):
    """Verify GET /comments/{qnum} returns all user comments for that question."""
    mock_supabase.set_table_data("user_comments", [
        {"id": "cmt-1", "qnum": 1, "comment_text": "Note 1", "created_at": "2026-09-01T00:00:00Z"},
        {"id": "cmt-2", "qnum": 1, "comment_text": "Note 2", "created_at": "2026-09-01T01:00:00Z"},
    ])

    res = client.get("/comments/1")
    assert res.status_code == 200
    data = res.json()
    assert "comments" in data
    assert len(data["comments"]) == 2
    assert data["comments"][0]["comment_text"] == "Note 1"


def test_delete_comment_success(client: TestClient, mock_supabase):
    """Verify DELETE /comments/{comment_id} deletes user comment."""
    res = client.delete("/comments/cmt-1")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_comments_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify /comments endpoints enforce authentication."""
    res = unauth_client.get("/comments/1")
    assert res.status_code == 401
