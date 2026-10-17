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


def test_create_session_database_failure_returns_503(unauth_client: TestClient, mock_user: dict):
    """Verify POST /auth/session fails fast with 503 instead of fabricating success when RDS fails."""
    with patch("routes.auth.verify_supabase_token", return_value=mock_user), \
         patch("routes.auth.rds_client.mutate", side_effect=Exception("RDS Connection Refused")):
        res = unauth_client.post(
            "/auth/session",
            json={"access_token": "valid-token-string-at-least-10-chars"},
        )
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"].lower()


def test_disable_auth_in_production_raises_500(monkeypatch):
    """Verify get_current_user strictly blocks DISABLE_AUTH in production environment."""
    import pytest
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer any-token")
    assert exc_info.value.status_code == 500
    assert "forbidden in production" in str(exc_info.value.detail).lower()


# ── Username Privacy, Availability & Secure Login Tests ────────────────────────

def test_login_with_username_success(unauth_client: TestClient):
    """Verify POST /auth/login resolves username to email in RDS and returns tokens."""
    mock_auth_res = {
        "access_token": "valid-access-token",
        "refresh_token": "valid-refresh-token",
        "user": {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "alpha@example.com",
            "username": "alpha_coder",
            "name": "Alpha Coder",
            "avatar_url": "",
        },
    }
    mock_profile = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "alpha@example.com",
        "username": "alpha_coder",
        "name": "Alpha Coder",
        "avatar_url": "",
    }
    with patch("routes.auth.rds_client.query", side_effect=[{"email": "alpha@example.com"}, mock_profile]), \
         patch("routes.auth.authenticate_user_credentials", return_value=mock_auth_res), \
         patch("routes.auth.rds_client.mutate", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "alpha_coder", "password": "SecurePassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"] == "valid-access-token"
        assert data["refresh_token"] == "valid-refresh-token"
        assert data["user"]["id"] == "12345678-1234-1234-1234-123456789012"
        assert data["user"]["username"] == "alpha_coder"


def test_login_with_email_success(unauth_client: TestClient):
    """Verify POST /auth/login authenticates email directly without querying RDS username."""
    mock_auth_res = {
        "access_token": "valid-access-token",
        "refresh_token": "valid-refresh-token",
        "user": {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "beta@example.com",
            "username": "beta_coder",
            "name": "Beta Coder",
            "avatar_url": "",
        },
    }
    mock_profile = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "beta@example.com",
        "username": "beta_coder",
        "name": "Beta Coder",
        "avatar_url": "",
    }
    with patch("routes.auth.rds_client.query", return_value=mock_profile) as mock_rds, \
         patch("routes.auth.authenticate_user_credentials", return_value=mock_auth_res), \
         patch("routes.auth.rds_client.mutate", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "beta@example.com", "password": "SecurePassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"] == "valid-access-token"
        # RDS query should only be called for fetching user profile by ID, not for username lookup
        for call_args in mock_rds.call_args_list:
            assert "WHERE username = %s" not in call_args[0][0]


def test_login_invalid_password_returns_401(unauth_client: TestClient):
    """Verify POST /auth/login returns uniform 401 when password check fails."""
    with patch("routes.auth.rds_client.query", return_value={"email": "alpha@example.com"}), \
         patch("routes.auth.authenticate_user_credentials", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "alpha_coder", "password": "WrongPassword"},
        )
        assert res.status_code == 401
        assert "Invalid email/username or password" in res.json()["detail"]


def test_login_nonexistent_username_returns_401(unauth_client: TestClient):
    """Verify POST /auth/login returns uniform 401 for unknown user without exposing user existence."""
    with patch("routes.auth.rds_client.query", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "nonexistent_coder", "password": "AnyPassword123!"},
        )
        assert res.status_code == 401
        assert "Invalid email/username or password" in res.json()["detail"]


def test_login_rds_error_returns_503(unauth_client: TestClient):
    """Verify POST /auth/login returns 503 when RDS fails during username resolution."""
    with patch("routes.auth.rds_client.query", side_effect=Exception("RDS timeout")):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "alpha_coder", "password": "AnyPassword123!"},
        )
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"].lower()


def test_resolve_username_deprecated_returns_404(unauth_client: TestClient):
    """Verify public POST /auth/resolve-username is disabled and returns 404 to protect user privacy."""
    res = unauth_client.post(
        "/auth/resolve-username",
        json={"username": "alpha_coder"},
    )
    assert res.status_code == 404
    assert "deprecated" in res.json()["detail"].lower()


def test_check_username_available(unauth_client: TestClient):
    """Verify GET /auth/check-username returns available=True when username is free."""
    with patch("routes.auth.rds_client.query", return_value=None):
        res = unauth_client.get("/auth/check-username?username=brand_new_user")
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is True
        assert data["username"] == "brand_new_user"


def test_check_username_taken(unauth_client: TestClient):
    """Verify GET /auth/check-username returns available=False when username is already taken."""
    with patch("routes.auth.rds_client.query", return_value={"id": "existing-uuid"}):
        res = unauth_client.get("/auth/check-username?username=taken_user")
        assert res.status_code == 200
        data = res.json()
        assert data["available"] is False
        assert data["username"] == "taken_user"


def test_check_username_database_error_fails_closed_503(unauth_client: TestClient):
    """Verify GET /auth/check-username fails closed with 503 on database errors."""
    with patch("routes.auth.rds_client.query", side_effect=Exception("DB connection dropped")):
        res = unauth_client.get("/auth/check-username?username=any_user")
        assert res.status_code == 503
        assert "unable to verify username availability" in res.json()["detail"].lower()


def test_check_username_too_short_returns_422(unauth_client: TestClient):
    """Verify GET /auth/check-username enforces minimum length of 3 chars."""
    res = unauth_client.get("/auth/check-username?username=ab")
    assert res.status_code == 422
