"""Unit tests for slowapi rate limiter configuration and key derivation."""

from unittest.mock import MagicMock
from fastapi import Request
from limiter import get_rate_limit_key


def test_get_rate_limit_key_authenticated_user_takes_precedence():
    """Verify get_rate_limit_key returns 'user:<user_id>' when rate_limit_user_id is present on request.state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = "abc-123-uuid"

    key = get_rate_limit_key(request)
    assert key == "user:abc-123-uuid"


def test_get_rate_limit_key_anonymous_ip_fallback():
    """Verify get_rate_limit_key falls back to 'ip:<remote_ip>' when no user_id is on request.state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.rate_limit_user_id = None
    request.client = MagicMock()
    request.client.host = "203.0.113.195"
    request.headers = {}

    key = get_rate_limit_key(request)
    assert key.startswith("ip:")
