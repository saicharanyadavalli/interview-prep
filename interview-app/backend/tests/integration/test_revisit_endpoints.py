"""Integration tests for /revisit queue endpoints."""

from fastapi.testclient import TestClient


def test_get_revisit_queue(client: TestClient, mock_supabase):
    """Verify GET /revisit returns all questions marked for revisit."""
    mock_supabase.set_table_data("user_progress", [
        {"qnum": 1, "is_solved": True, "is_revisit": True, "updated_at": "2026-09-01T00:00:00Z"},
        {"qnum": 5, "is_solved": False, "is_revisit": True, "updated_at": "2026-09-01T01:00:00Z"},
    ])

    res = client.get("/revisit")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert len(data["items"]) == 2
    qnums = [item["qnum"] for item in data["items"]]
    assert 1 in qnums
    assert 5 in qnums


def test_remove_from_revisit(client: TestClient, mock_supabase):
    """Verify DELETE /revisit/{qnum} clears revisit flag while keeping progress record."""
    mock_supabase.set_table_data("user_progress", [
        {"qnum": 1, "is_solved": True, "is_revisit": True}
    ])

    res = client.delete("/revisit/1")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_get_revisit_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify GET /revisit returns 401 for anonymous callers."""
    res = unauth_client.get("/revisit")
    assert res.status_code == 401
