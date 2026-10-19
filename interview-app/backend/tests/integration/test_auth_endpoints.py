"""Integration tests for /auth/session, /auth/login, and authentication dependencies."""

from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

import os
from routes.auth import get_current_user, get_optional_current_user
from services.cognito_auth import CognitoAuthError, InvalidTokenUseError, InvalidTokenError


@pytest.fixture(autouse=True)
def auth_endpoints_test_env():
    """Ensure clean Cognito test environment variables for auth endpoint tests."""
    old_env = {
        k: os.environ.get(k)
        for k in (
            "TESTING",
            "COGNITO_REGION",
            "COGNITO_USER_POOL_ID",
            "COGNITO_CLIENT_ID",
            "DISABLE_AUTH",
            "ENVIRONMENT",
            "APP_ENV",
            "ENV",
        )
    }
    os.environ["TESTING"] = "1"
    os.environ["COGNITO_REGION"] = "ap-south-2"
    os.environ["COGNITO_USER_POOL_ID"] = "ap-south-2_testPoolId"
    os.environ["COGNITO_CLIENT_ID"] = "test-client-id-123"
    os.environ["DISABLE_AUTH"] = "false"
    for k in ("ENVIRONMENT", "APP_ENV", "ENV"):
        os.environ.pop(k, None)

    yield

    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]


def test_create_session_success(unauth_client: TestClient, mock_user: dict, mock_supabase):
    """Verify POST /auth/session validates token and returns user profile."""
    mock_claims = {
        "sub": mock_user["id"],
        "email": mock_user["email"],
        "username": mock_user["username"],
        "token_use": "access",
    }
    with patch("routes.auth.verify_cognito_token", return_value=mock_claims), \
         patch("routes.auth.resolve_user_identity", return_value=mock_user):
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
    with patch("routes.auth.verify_cognito_token", side_effect=CognitoAuthError("Invalid signature")):
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
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=None)
    assert exc.value.status_code == 401


def test_get_current_user_non_bearer_header_raises_401():
    """Verify get_current_user raises 401 when Authorization does not start with Bearer."""
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization="Basic dXNlcjpwYXNz")
    assert exc.value.status_code == 401


def test_get_current_user_with_id_token_raises_401():
    """Verify get_current_user rejects ID tokens (token_use='id') and raises 401."""
    with patch("routes.auth.verify_cognito_token", side_effect=InvalidTokenUseError("Protected API endpoints strictly require token_use='access'.")):
        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization="Bearer eyJraWQiOiJpZFRva2VuIn0...")
        assert exc.value.status_code == 401
        assert "token_use='access'" in str(exc.value.detail)


def test_get_current_user_with_invalid_token_raises_401():
    """Verify get_current_user immediately raises 401 with no legacy fallback on invalid token."""
    with patch("routes.auth.verify_cognito_token", side_effect=InvalidTokenError("Token signature verification failed")):
        with pytest.raises(HTTPException) as exc:
            get_current_user(authorization="Bearer corrupted-token")
        assert exc.value.status_code == 401


def test_get_optional_current_user_missing_returns_none():
    """Verify get_optional_current_user returns None instead of raising on missing auth."""
    assert get_optional_current_user(authorization=None) is None
    assert get_optional_current_user(authorization="InvalidHeader") is None


def test_create_session_database_failure_returns_503(unauth_client: TestClient, mock_user: dict):
    """Verify POST /auth/session fails fast with 503 instead of fabricating success when RDS fails."""
    mock_claims = {
        "sub": mock_user["id"],
        "email": mock_user["email"],
        "username": mock_user["username"],
        "token_use": "access",
    }
    with patch("routes.auth.verify_cognito_token", return_value=mock_claims), \
         patch("routes.auth.resolve_user_identity", side_effect=Exception("RDS Connection Refused")):
        res = unauth_client.post(
            "/auth/session",
            json={"access_token": "valid-token-string-at-least-10-chars"},
        )
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"].lower()


def test_create_session_ambiguous_email_conflict_returns_503(unauth_client: TestClient, mock_user: dict):
    """Verify POST /auth/session fails safely with 503 when ambiguous email match occurs."""
    mock_claims = {
        "sub": "some-sub",
        "email": "ambiguous@example.com",
        "token_use": "access",
    }
    with patch("routes.auth.verify_cognito_token", return_value=mock_claims), \
         patch("routes.auth.resolve_user_identity", side_effect=ValueError("Ambiguous identity linking rejected: Multiple existing user profiles (2) match email.")):
        res = unauth_client.post(
            "/auth/session",
            json={"access_token": "valid-token-string-at-least-10-chars"},
        )
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"].lower()


def test_disable_auth_in_production_raises_500(monkeypatch):
    """Verify get_current_user strictly blocks DISABLE_AUTH in production environment."""
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer any-token")
    assert exc_info.value.status_code == 500
    assert "forbidden in production" in str(exc_info.value.detail).lower()


# ── Username Privacy, Availability & Secure Cognito Login Tests ──────────────────

def test_login_with_username_success(unauth_client: TestClient):
    """Verify POST /auth/login resolves username to email in RDS and authenticates via Cognito USER_PASSWORD_AUTH."""
    mock_profile = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "alpha@example.com",
        "username": "alpha_coder",
        "name": "Alpha Coder",
        "avatar_url": "",
    }
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "mock-access-token",
            "RefreshToken": "valid-refresh-token",
            "IdToken": "valid-id-token",
            "ExpiresIn": 3600,
        }
    }

    def mock_query(sql, params=None, fetch="all"):
        if "WHERE LOWER(username) = LOWER(%s)" in sql:
            return {"email": "alpha@example.com"}
        if "FROM user_identities" in sql:
            return {"user_id": "12345678-1234-1234-1234-123456789012", "email": "alpha@example.com"}
        if "FROM user_profiles" in sql:
            return mock_profile if fetch == "one" else [mock_profile]
        return None

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client), \
         patch("routes.auth.rds_client.query", side_effect=mock_query), \
         patch("routes.auth.rds_client.mutate", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "alpha_coder", "password": "SecurePassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"] == "mock-access-token"
        assert data["refresh_token"] == "valid-refresh-token"
        assert data["user"]["id"] == "12345678-1234-1234-1234-123456789012"
        assert data["user"]["username"] == "alpha_coder"

        mock_cognito_client.initiate_auth.assert_called_once_with(
            ClientId="test-client-id-123",
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": "alpha@example.com",
                "PASSWORD": "SecurePassword123!",
            },
        )


def test_login_with_email_success(unauth_client: TestClient):
    """Verify POST /auth/login authenticates email directly via Cognito without querying RDS username."""
    mock_profile = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "beta@example.com",
        "username": "beta_coder",
        "name": "Beta Coder",
        "avatar_url": "",
    }
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "mock-access-token",
            "RefreshToken": "valid-refresh-token",
            "IdToken": "valid-id-token",
            "ExpiresIn": 3600,
        }
    }

    queries = []

    def mock_query(sql, params=None, fetch="all"):
        queries.append((sql, params))
        if "FROM user_identities" in sql:
            return {"user_id": "12345678-1234-1234-1234-123456789012", "email": "beta@example.com"}
        if "FROM user_profiles" in sql:
            return mock_profile if fetch == "one" else [mock_profile]
        return None

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client), \
         patch("routes.auth.rds_client.query", side_effect=mock_query), \
         patch("routes.auth.rds_client.mutate", return_value=None):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "beta@example.com", "password": "SecurePassword123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["access_token"] == "mock-access-token"
        assert data["user"]["id"] == "12345678-1234-1234-1234-123456789012"

        # RDS query should NOT be called for username lookup
        for sql, _ in queries:
            assert "WHERE username = %s" not in sql
            assert "WHERE LOWER(username) = LOWER(%s)" not in sql

        mock_cognito_client.initiate_auth.assert_called_once_with(
            ClientId="test-client-id-123",
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": "beta@example.com",
                "PASSWORD": "SecurePassword123!",
            },
        )


def test_login_invalid_password_returns_401(unauth_client: TestClient):
    """Verify POST /auth/login returns uniform 401 when Cognito returns NotAuthorizedException."""
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "NotAuthorizedException", "Message": "Incorrect username or password."}},
        "initiate_auth",
    )

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client), \
         patch("routes.auth.rds_client.query", return_value={"email": "alpha@example.com"}):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "alpha_coder", "password": "WrongPassword"},
        )
        assert res.status_code == 401
        assert "Invalid email/username or password" in res.json()["detail"]


def test_login_user_not_found_returns_401(unauth_client: TestClient):
    """Verify POST /auth/login returns uniform 401 when Cognito returns UserNotFoundException."""
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "UserNotFoundException", "Message": "User does not exist."}},
        "initiate_auth",
    )

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "nonexistent@example.com", "password": "AnyPassword123!"},
        )
        assert res.status_code == 401
        assert "Invalid email/username or password" in res.json()["detail"]


def test_login_user_not_confirmed_returns_403(unauth_client: TestClient):
    """Verify POST /auth/login returns 403 with needs_confirmation: true on UserNotConfirmedException."""
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.side_effect = ClientError(
        {"Error": {"Code": "UserNotConfirmedException", "Message": "User is not confirmed."}},
        "initiate_auth",
    )

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client), \
         patch("routes.auth.rds_client.query", return_value={"email": "unconfirmed@example.com"}):
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "unconfirmed@example.com", "password": "Password123!"},
        )
        assert res.status_code == 403
        body = res.json()
        assert "User is not confirmed" in body["detail"]
        assert body["needs_confirmation"] is True


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


def test_disable_auth_in_staging_raises_500(monkeypatch):
    """Verify get_current_user strictly blocks DISABLE_AUTH in staging environment."""
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer any-token")
    assert exc_info.value.status_code == 500
    assert "forbidden in production/staging" in str(exc_info.value.detail).lower()


def test_login_cryptographically_verifies_id_token(unauth_client: TestClient):
    """Verify POST /auth/login verifies ID token using verify_cognito_id_token instead of unverified decode."""
    mock_profile = {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "verified@example.com",
        "username": "verified_coder",
        "name": "Verified Coder",
        "avatar_url": "",
    }
    mock_cognito_client = MagicMock()
    mock_cognito_client.initiate_auth.return_value = {
        "AuthenticationResult": {
            "AccessToken": "mock-access-token",
            "RefreshToken": "valid-refresh-token",
            "IdToken": "mock-id-token",
            "ExpiresIn": 3600,
        }
    }

    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            return {"user_id": "12345678-1234-1234-1234-123456789012", "email": "verified@example.com"}
        if "FROM user_profiles" in sql:
            return mock_profile if fetch == "one" else [mock_profile]
        return None

    with patch("routes.auth.boto3.client", return_value=mock_cognito_client), \
         patch("routes.auth.rds_client.query", side_effect=mock_query), \
         patch("routes.auth.rds_client.mutate", return_value=None), \
         patch("routes.auth.verify_cognito_id_token") as mock_verify_id:
        mock_verify_id.return_value = {
            "sub": "12345678-1234-1234-1234-123456789012",
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified Coder",
        }
        res = unauth_client.post(
            "/auth/login",
            json={"identifier": "verified@example.com", "password": "Password123!"},
        )
        assert res.status_code == 200
        mock_verify_id.assert_called_once_with("mock-id-token")


def test_create_session_with_id_token_merges_claims(unauth_client: TestClient, mock_user: dict):
    """Verify POST /auth/session merges verified ID token claims into claims before resolving identity."""
    mock_access_claims = {
        "sub": "google-sub-123",
        "token_use": "access",
    }
    mock_id_claims = {
        "sub": "google-sub-123",
        "email": "googleuser@gmail.com",
        "email_verified": True,
        "name": "Google User",
        "preferred_username": "googler",
        "picture": "https://avatar.url/pic.jpg",
    }
    captured_claims = {}

    def mock_resolve(claims, provider="cognito"):
        captured_claims.update(claims)
        return {
            "id": "11111111-2222-3333-4444-555555555555",
            "email": claims["email"],
            "username": claims.get("preferred_username"),
            "name": claims.get("name"),
            "avatar_url": claims.get("picture"),
        }

    with patch("routes.auth.verify_cognito_token", return_value=mock_access_claims), \
         patch("routes.auth.verify_cognito_id_token", return_value=mock_id_claims), \
         patch("routes.auth.resolve_user_identity", side_effect=mock_resolve):
        res = unauth_client.post(
            "/auth/session",
            json={
                "access_token": "valid-access-token-12345",
                "id_token": "valid-id-token-67890",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "googleuser@gmail.com"
        assert data["username"] == "googler"
        assert data["name"] == "Google User"
        assert data["avatar_url"] == "https://avatar.url/pic.jpg"
        assert captured_claims["email_verified"] is True
        assert captured_claims["preferred_username"] == "googler"


def test_create_session_with_invalid_id_token_returns_401(unauth_client: TestClient):
    """Verify POST /auth/session returns 401 when ID token cryptographic verification fails."""
    mock_access_claims = {"sub": "sub-123", "token_use": "access"}

    with patch("routes.auth.verify_cognito_token", return_value=mock_access_claims), \
         patch("routes.auth.verify_cognito_id_token", side_effect=CognitoAuthError("Invalid signature")):
        res = unauth_client.post(
            "/auth/session",
            json={
                "access_token": "valid-access-token-12345",
                "id_token": "corrupt-id-token-99999",
            },
        )
        assert res.status_code == 401
        assert "Invalid or expired ID token" in res.json()["detail"]


def test_provision_user_profile_success(unauth_client: TestClient):
    """Verify POST /auth/provision pre-provisions new user profile and links identity."""
    mutations = []

    def mock_query(sql, params=None, fetch="one"):
        # Username not taken, email does not exist yet
        return None

    def mock_mutate(sql, params=None):
        mutations.append((sql, params))
        return 1

    with patch("routes.auth.rds_client.query", side_effect=mock_query), \
         patch("routes.auth.rds_client.mutate", side_effect=mock_mutate):
        res = unauth_client.post(
            "/auth/provision",
            json={
                "email": "newbie@example.com",
                "username": "newbie",
                "name": "New User",
                "user_id": "12345678-1234-1234-1234-123456789012",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "newbie@example.com"
        assert data["username"] == "newbie"
        assert data["name"] == "New User"
        assert data["id"] == "12345678-1234-1234-1234-123456789012"
        assert len(mutations) == 2
        assert "INSERT INTO user_profiles" in mutations[0][0]
        assert "INSERT INTO user_identities" in mutations[1][0]


def test_provision_user_profile_idempotent_existing_preserves_username(unauth_client: TestClient):
    """Verify POST /auth/provision is idempotent and does not overwrite existing valid username."""
    mutations = []

    def mock_query(sql, params=None, fetch="one"):
        if "LOWER(username) = LOWER(%s)" in sql:
            return {"id": "uuid-1", "email": "existing@example.com"}
        if "LOWER(email) = LOWER(%s)" in sql:
            return {
                "id": "uuid-1",
                "email": "existing@example.com",
                "username": "original_uname",
                "name": "Original Name",
                "phone": "",
                "avatar_url": "",
            }
        return None

    with patch("routes.auth.rds_client.query", side_effect=mock_query), \
         patch("routes.auth.rds_client.mutate", side_effect=lambda s, p: mutations.append((s, p)) or 1):
        res = unauth_client.post(
            "/auth/provision",
            json={
                "email": "existing@example.com",
                "username": "different_uname",
                "name": "Updated Name",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["username"] == "original_uname"
        assert data["name"] == "Original Name"


def test_provision_user_profile_username_taken_returns_409(unauth_client: TestClient):
    """Verify POST /auth/provision returns 409 Conflict when username belongs to another email."""
    def mock_query(sql, params=None, fetch="one"):
        if "LOWER(username) = LOWER(%s)" in sql:
            return {"id": "other-uuid", "email": "other@example.com"}
        return None

    with patch("routes.auth.rds_client.query", side_effect=mock_query):
        res = unauth_client.post(
            "/auth/provision",
            json={
                "email": "me@example.com",
                "username": "taken_handle",
                "name": "My Name",
            },
        )
        assert res.status_code == 409
        assert "already taken" in res.json()["detail"].lower()


def test_provision_user_profile_rejects_extra_fields(unauth_client: TestClient):
    """Verify POST /auth/provision rejects forbidden fields like password or role."""
    res = unauth_client.post(
        "/auth/provision",
        json={
            "email": "safe@example.com",
            "username": "safeuser",
            "password": "Password123!",  # strictly forbidden!
        },
    )
    assert res.status_code == 422


