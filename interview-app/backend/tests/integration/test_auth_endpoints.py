"""Integration tests for /auth/session and authentication dependencies."""

from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient

from routes.auth import get_current_user, get_optional_current_user


def test_create_session_success(unauth_client: TestClient, mock_user: dict, mock_supabase):
    """Verify POST /auth/session validates token and returns user profile."""
    with patch("routes.auth.verify_supabase_token", return_value=mock_user):
        res = unauth_client.post(
            "/auth/session",
            json={"access_token": "valid-token-string-at-least-10-chars"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == mock_user["id"]
        assert data["email"] == mock_user["email"]
        assert data["username"] == mock_user["username"]


def test_create_session_invalid_token_returns_401(unauth_client: TestClient):
    """Verify POST /auth/session returns 401 when token verification fails."""
    with patch("routes.auth.verify_supabase_token", return_value=None):
        res = unauth_client.post(
            "/auth/session",
            json={"access_token": "invalid-token-string-12345"},
        )
        assert res.status_code == 401
        assert "Invalid or expired token" in res.json()["detail"]


def test_create_session_extra_fields_returns_422(unauth_client: TestClient):
    """Verify POST /auth/session rejects unexpected payload fields."""
    res = unauth_client.post(
        "/auth/session",
        json={
            "access_token": "valid-token-string-at-least-10-chars",
            "role": "admin",  # forbidden
        },
    )
    assert res.status_code == 422


# ── Auth Dependency Tests ────────────────────────────────────────────────────

def test_get_current_user_missing_header_raises_401():
    """Verify get_current_user raises 401 when Authorization header is missing."""
    import pytest
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=None)
    assert exc.value.status_code == 401


def test_get_current_user_non_bearer_header_raises_401():
    """Verify get_current_user raises 401 when Authorization does not start with Bearer."""
    import pytest
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization="Basic dXNlcjpwYXNz")
    assert exc.value.status_code == 401


def test_get_optional_current_user_missing_returns_none():
    """Verify get_optional_current_user returns None instead of raising on missing auth."""
    assert get_optional_current_user(authorization=None) is None
    assert get_optional_current_user(authorization="InvalidHeader") is None
