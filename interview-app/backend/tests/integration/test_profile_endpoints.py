"""Integration tests for /profile user management and avatar upload endpoints."""

import io
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image


def _generate_valid_png(width: int = 32, height: int = 32) -> bytes:
    """Generate valid PNG bytes with Pillow."""
    buf = io.BytesIO()
    img = Image.new("RGBA", (width, height), (15, 118, 110, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


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


def test_get_my_profile_auto_creates_missing_profile(client: TestClient, mock_supabase, mock_user):
    """Verify GET /profile/me auto-creates a profile row when none exists."""
    mock_supabase.set_table_data("user_profiles", [])

    res = client.get("/profile/me")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == mock_user["id"]
    assert data["email"] == mock_user["email"]


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


def test_update_my_profile_username_collision_returns_409(client: TestClient, mock_supabase, mock_user):
    """Verify PUT /profile/me returns 409 when the chosen username is already taken by another user."""
    # Another user exists with the username 'already_taken'
    mock_supabase.set_table_data("user_profiles", [
        {
            "id": "other-user-9999",
            "username": "already_taken",
            "email": "other@example.com",
        },
        {
            "id": mock_user["id"],
            "username": "current_user",
            "email": mock_user["email"],
        }
    ])

    payload = {"username": "already_taken"}
    res = client.put("/profile/me", json=payload)
    assert res.status_code == 409
    assert "already taken" in res.json()["detail"]


def test_update_my_profile_invalid_phone_returns_422(client: TestClient):
    """Verify PUT /profile/me returns 422 for phone with letters or invalid length."""
    res = client.put("/profile/me", json={"phone": "123-abc-7890"})
    assert res.status_code == 422


def test_update_my_profile_invalid_name_returns_422(client: TestClient):
    """Verify PUT /profile/me returns 422 for name with script injection characters."""
    res = client.put("/profile/me", json={"name": "<script>alert(1)</script>"})
    assert res.status_code == 422


def test_upload_avatar_valid_image_success(client: TestClient, mock_cloudinary, mock_supabase):
    """Verify POST /profile/avatar/upload accepts valid PNG and updates profile."""
    valid_png = _generate_valid_png(32, 32)

    with patch("routes.profile._configure_cloudinary", return_value=(True, "interview-prep/avatars")):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert "avatar_url" in data
        assert data["storage"] == "cloudinary"


def test_upload_avatar_inline_fallback_when_cloudinary_not_configured(client: TestClient, mock_supabase):
    """Verify POST /profile/avatar/upload uses inline data URL when Cloudinary is not configured."""
    valid_png = _generate_valid_png(16, 16)

    with patch("routes.profile._configure_cloudinary", return_value=(False, "interview-prep/avatars")):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["storage"] == "inline"
        assert data["avatar_url"].startswith("data:image/png;base64,")


def test_upload_avatar_empty_file_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects empty files with 400."""
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_upload_avatar_non_image_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects non-image text files with 400."""
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("notes.txt", b"plain text content", "text/plain")},
    )
    assert res.status_code == 400
    assert "Invalid image format" in res.json()["detail"] or "image" in res.json()["detail"]


def test_upload_avatar_spoofed_extension_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects text file disguised as .png."""
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("evil.png", b"this is not an image", "image/png")},
    )
    assert res.status_code == 400
    assert "Invalid" in res.json()["detail"] or "Corrupted" in res.json()["detail"]


def test_upload_avatar_corrupt_data_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects truncated or corrupt image bytes."""
    corrupt_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("corrupt.png", corrupt_png, "image/png")},
    )
    assert res.status_code == 400
    assert "Corrupted" in res.json()["detail"] or "Invalid" in res.json()["detail"]


def test_upload_avatar_oversized_file_fails_400(client: TestClient):
    """Verify POST /profile/avatar/upload rejects images larger than 5MB."""
    oversized_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)
    res = client.post(
        "/profile/avatar/upload",
        files={"file": ("large.png", oversized_bytes, "image/png")},
    )
    assert res.status_code == 400


def test_upload_avatar_cloudinary_failure_returns_502(client: TestClient, mock_supabase):
    """Verify POST /profile/avatar/upload returns 502 when Cloudinary raises an error."""
    valid_png = _generate_valid_png(32, 32)

    with patch("routes.profile._configure_cloudinary", return_value=(True, "interview-prep/avatars")), \
         patch("cloudinary.uploader.upload", side_effect=RuntimeError("Cloudinary connection reset")):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 502
        assert "storage service failed" in res.json()["detail"].lower()
