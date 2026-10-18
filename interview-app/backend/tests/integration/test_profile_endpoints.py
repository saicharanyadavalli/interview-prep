"""Integration tests for /profile user management and avatar upload endpoints."""

import io
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from PIL import Image

from services import s3_storage_service
from services.s3_storage_service import S3StorageError


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


def test_upload_avatar_valid_image_success(client: TestClient, mock_supabase, mock_user):
    """Verify POST /profile/avatar/upload accepts valid PNG and updates profile with S3 CloudFront URL."""
    valid_png = _generate_valid_png(32, 32)
    expected_url = f"https://d123456abcdef8.cloudfront.net/avatars/{mock_user['id']}/sample-avatar.png"

    with patch(
        "services.s3_storage_service.upload_avatar",
        return_value={
            "url": expected_url,
            "key": f"avatars/{mock_user['id']}/sample-avatar.png",
            "bucket": "interview-prep-assets-808431466075-ap-south-2",
        },
    ):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["avatar_url"] == expected_url
        assert data["storage"] == "s3"
        assert data["key"] == f"avatars/{mock_user['id']}/sample-avatar.png"
        assert data["bucket"] == "interview-prep-assets-808431466075-ap-south-2"


def test_upload_avatar_end_to_end_persists_to_rds(client: TestClient, mock_supabase, mock_user):
    """Verify POST /profile/avatar/upload end-to-end puts object to S3 and updates RDS user_profiles."""
    valid_png = _generate_valid_png(32, 32)
    mock_s3 = MagicMock()

    with patch.object(s3_storage_service, "get_s3_client", return_value=mock_s3):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["storage"] == "s3"
        assert "avatar_url" in data
        assert mock_user["id"] in data["avatar_url"]
        assert mock_s3.put_object.call_count == 1

        # Verify GET /profile/me returns updated avatar_url
        me_res = client.get("/profile/me")
        assert me_res.status_code == 200
        assert me_res.json()["avatar_url"] == data["avatar_url"]


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


def test_upload_avatar_s3_storage_failure_returns_503(client: TestClient, mock_supabase):
    """Verify POST /profile/avatar/upload returns 503 fail-clean when S3 upload fails."""
    valid_png = _generate_valid_png(32, 32)

    with patch(
        "services.s3_storage_service.upload_avatar",
        side_effect=S3StorageError("S3 connection reset"),
    ):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 503
        assert "storage service failed" in res.json()["detail"].lower()


def test_upload_avatar_unexpected_failure_returns_500(client: TestClient, mock_supabase):
    """Verify POST /profile/avatar/upload returns 500 when an unexpected exception occurs."""
    valid_png = _generate_valid_png(32, 32)

    with patch("services.s3_storage_service.upload_avatar", side_effect=RuntimeError("System memory error")):
        res = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", valid_png, "image/png")},
        )
        assert res.status_code == 500
        assert "failed to upload avatar" in res.json()["detail"].lower()
