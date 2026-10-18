"""Integration tests for /progress/folders custom folder endpoints."""

from fastapi.testclient import TestClient
from unittest.mock import patch


def test_get_custom_folders(client: TestClient, mock_supabase):
    """Verify GET /progress/folders returns user custom folders."""
    mock_supabase.set_table_data("user_custom_folders", [
        {"folder_name": "Favorites", "qnums": [1, 2, 3], "updated_at": "2026-10-18T00:00:00Z"},
        {"folder_name": "Must Revise", "qnums": [5], "updated_at": "2026-10-18T01:00:00Z"},
    ])

    with patch("routes.progress._ensure_folders_table"):
        res = client.get("/progress/folders")
        assert res.status_code == 200
        data = res.json()
        assert "folders" in data
        assert len(data["folders"]) == 2
        names = [f["name"] for f in data["folders"]]
        assert "Favorites" in names
        assert "Must Revise" in names


def test_add_question_to_custom_folder(client: TestClient, mock_supabase):
    """Verify POST /progress/folders/add-question adds question and prevents duplicates."""
    with patch("routes.progress._ensure_folders_table"), \
         patch("services.rds_client.query", return_value={"id": "abc", "qnums": [10, 20]}), \
         patch("services.rds_client.mutate", return_value=1):

        # Add duplicate
        res = client.post("/progress/folders/add-question", json={"folder_name": "Favorites", "qnum": 10})
        assert res.status_code == 200
        data = res.json()
        assert data["already_present"] is True

        # Add new question
        res_new = client.post("/progress/folders/add-question", json={"folder_name": "Favorites", "qnum": 30})
        assert res_new.status_code == 200
        data_new = res_new.json()
        assert data_new["already_present"] is False
        assert data_new["qnum"] == 30


def test_custom_folders_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify GET /progress/folders returns 401 for anonymous callers."""
    res = unauth_client.get("/progress/folders")
    assert res.status_code == 401
