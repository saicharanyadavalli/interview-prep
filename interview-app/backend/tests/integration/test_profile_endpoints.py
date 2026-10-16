"""Integration tests for /profile user management and avatar upload endpoints."""

from unittest.mock import patch
from fastapi.testclient import TestClient


def test_get_my_profile_returns_profile(client: TestClient, mock_supabase, mock_user):
    """Verify GET /profile/me returns current user profile."""
    mock_supabase.set_table_data("user_profiles", [{
        "id": mock_user["id"],
        "email": mock_user["email"],
        "username": mock_user["username"],
        "name": mock_user["name"],
        "phone": "1234567890",
        "avatar_url": "https://example.com/pic.png",
    }])

    res = client.get("/profile/me")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == mock_user["id"]
    assert data["email"] == mock_user["email"]
    assert data["username"] == mock_user["username"]


def test_update_my_profile_success(client: TestClient, mock_supabase, mock_user):
    """Verify PUT /profile/me updates editable user fields."""
    mock_supabase.set_table_data("user_profiles", [{
        "id": mock_user["id"],
        "email": mock_user["email"],
        "username": "updated_user",
        "name": "Updated Name",
        "phone": "9876543210",
        "avatar_url": "https://example.com/new.png",
    }])

    payload = {
        "username": "updated_user",
        "name": "Updated Name",
        "phone": "9876543210",
    }
    res = client.put("/profile/me", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "updated_user"
    assert data["name"] == "Updated Name"


def test_update_my_profile_empty_payload_returns_400(client: TestClient):
    """Verify PUT /profile/me returns 400 when no fields are supplied."""
    res = client.put("/profile/me", json={})
    assert res.status_code == 400


def test_upload_avatar_valid_image_success(client: TestClient, mock_cloudinary, mock_supabase):
    """Verify POST /profile/avatar/upload accepts valid PNG and updates profile."""
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    with patch("routes.profile._configure_cloudinary", return_value=(True, "interview-prep/avatars")):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", fake_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert "avatar_url" in data
        assert data["storage"] == "cloudinary"


def test_upload_avatar_non_image_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects non-image text files with 400."""
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
    )
    assert res.status_code == 400
    assert "Only image files" in res.json()["detail"] or "Invalid" in res.json()["detail"]


def test_upload_avatar_oversized_file_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects images larger than 5MB."""
    oversized_bytes = b"\x89PNG" + b"0" * (6 * 1024 * 1024)
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("large.png", oversized_bytes, "image/png")},
    )
    assert res.status_code == 400
