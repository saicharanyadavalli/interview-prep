"""Integration tests for /learning-tracks and legacy /system-design endpoints."""

from unittest.mock import patch
from fastapi.testclient import TestClient


def test_get_learning_tracks_metadata(client: TestClient):
    """Verify GET /learning-tracks returns all 5 tracks."""
    res = client.get("/learning-tracks")
    assert res.status_code == 200
    data = res.json()
    assert "tracks" in data
    assert len(data["tracks"]) == 5
    track_ids = [t["track_id"] for t in data["tracks"]]
    assert "system-design" in track_ids
    assert "genai-system-design" in track_ids


def test_get_learning_track_progress(client: TestClient, mock_supabase):
    """Verify GET /learning-tracks/{track_id}/progress returns step list and percentage."""
    mock_supabase.set_table_data("learning_track_progress", [
        {"step_no": 1, "completed": True, "updated_at": "2026-09-01T00:00:00Z"},
    ])

    res = client.get("/learning-tracks/system-design/progress")
    assert res.status_code == 200
    data = res.json()
    assert data["track_id"] == "system-design"
    assert data["total_steps"] == 30
    assert data["completed_steps"] == 1
    assert len(data["steps"]) == 30
    assert data["steps"][0]["completed"] is True


def test_update_learning_track_progress(client: TestClient, mock_supabase):
    """Verify POST /learning-tracks/{track_id}/progress updates step completion."""
    payload = {"step_no": 2, "completed": True}
    res = client.post("/learning-tracks/system-design/progress", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["step_no"] == 2
    assert data["completed"] is True


def test_update_learning_track_progress_invalid_step(client: TestClient):
    """Verify POST /learning-tracks/{track_id}/progress rejects step_no out of range."""
    payload = {"step_no": 999, "completed": True}
    res = client.post("/learning-tracks/system-design/progress", json=payload)
    assert res.status_code == 422


def test_get_learning_track_lesson_content(client: TestClient, mock_supabase):
    """Verify GET /learning-tracks/{track_id}/lessons/{step_no} returns lesson HTML."""
    mock_supabase.set_table_data("course_lessons", [
        {"track_id": "system-design", "step_no": 1, "title": "Scale From Zero", "html_content": "<h1>Lesson</h1>"}
    ])

    res = client.get("/learning-tracks/system-design/lessons/1")
    assert res.status_code == 200
    data = res.json()
    assert data["track_id"] == "system-design"
    assert data["step_no"] == 1
    assert data["html_content"] == "<h1>Lesson</h1>"


def test_legacy_system_design_progress_endpoints(client: TestClient, mock_supabase):
    """Verify backward-compatible GET & POST /system-design/progress endpoints."""
    # GET legacy
    res_get = client.get("/system-design/progress")
    assert res_get.status_code == 200
    assert "steps" in res_get.json()

    # POST legacy
    res_post = client.post("/system-design/progress", json={"step_no": 1, "completed": True})
    assert res_post.status_code == 200
    assert res_post.json()["step_no"] == 1
