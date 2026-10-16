"""Unit tests for Supabase client factory and JWT token verification."""

import os
from unittest.mock import MagicMock, patch
from services.supabase_client import verify_supabase_token, get_supabase_client


def test_verify_supabase_token_disable_auth_mode():
    """Verify verify_supabase_token returns test user dictionary when DISABLE_AUTH='true'."""
    with patch.dict(os.environ, {"DISABLE_AUTH": "true"}):
        user = verify_supabase_token("any-token-string")
        assert user is not None
        assert user["email"] == "testuser@example.com"
        assert "id" in user


def test_verify_supabase_token_valid_jwt_parsing():
    """Verify verify_supabase_token extracts user id and metadata from Supabase client."""
    mock_auth_response = MagicMock()
    mock_auth_response.user.id = "user-real-id-999"
    mock_auth_response.user.email = "realuser@example.com"
    mock_auth_response.user.user_metadata = {
        "username": "realuser",
        "full_name": "Real User",
        "avatar_url": "https://example.com/pic.png",
    }

    mock_client = MagicMock()
    mock_client.auth.get_user.return_value = mock_auth_response

    with patch.dict(os.environ, {"DISABLE_AUTH": "false"}), \
         patch("services.supabase_client.get_supabase_client", return_value=mock_client):
        user = verify_supabase_token("valid-jwt-token")
        assert user is not None
        assert user["id"] == "user-real-id-999"
        assert user["email"] == "realuser@example.com"
        assert user["username"] == "realuser"


def test_verify_supabase_token_invalid_jwt_returns_none():
    """Verify verify_supabase_token returns None on auth exception."""
    mock_client = MagicMock()
    mock_client.auth.get_user.side_effect = Exception("Invalid JWT token")

    with patch.dict(os.environ, {"DISABLE_AUTH": "false"}), \
         patch("services.supabase_client.get_supabase_client", return_value=mock_client):
        user = verify_supabase_token("bad-jwt-token")
        assert user is None
