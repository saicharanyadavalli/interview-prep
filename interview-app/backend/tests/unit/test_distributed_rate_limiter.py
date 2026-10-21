"""Unit tests for distributed rate limiting, proxy header parsing, and key derivation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

from fastapi import Request

from limiter import get_client_ip, get_rate_limit_key, resolve_rate_limit_storage_uri


def _build_mock_request(
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
    user_id: str | None = None,
) -> Request:
    """Build a mock Request object with configured headers and state."""
    req = MagicMock(spec=Request)
    req.headers = headers or {}
    req.client = MagicMock()
    req.client.host = client_host
    req.state = MagicMock()
    req.state.rate_limit_user_id = user_id
    return req


def test_resolve_rate_limit_storage_uri_explicit():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "rediss://:mypass@cache.aws:6379/1"}):
        assert resolve_rate_limit_storage_uri() == "rediss://:mypass@cache.aws:6379/1"


def test_resolve_rate_limit_storage_uri_from_cache_url():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "", "CACHE_URL": "redis://localhost:6379/0"}):
        assert resolve_rate_limit_storage_uri() == "redis://localhost:6379/0"


def test_resolve_rate_limit_storage_uri_fallback():
    with patch_env({"RATE_LIMIT_STORAGE_URI": "", "CACHE_URL": "", "REDIS_URL": "", "CACHE_HOST": "", "REDIS_HOST": ""}):
        assert resolve_rate_limit_storage_uri() == "memory://"


def test_get_client_ip_prioritizes_x_real_ip():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195", "x-forwarded-for": "198.51.100.1, 10.0.0.1"},
        client_host="10.0.0.2",
    )
    assert get_client_ip(req) == "203.0.113.195"


def test_get_client_ip_falls_back_to_x_forwarded_for():
    req = _build_mock_request(
        headers={"x-forwarded-for": "198.51.100.42, 10.0.0.1"},
        client_host="10.0.0.2",
    )
    assert get_client_ip(req) == "198.51.100.42"


def test_get_client_ip_falls_back_to_client_host():
    req = _build_mock_request(headers={}, client_host="192.168.1.100")
    assert get_client_ip(req) == "192.168.1.100"


def test_get_rate_limit_key_authenticated_user():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195"},
        user_id="user-uuid-1234",
    )
    assert get_rate_limit_key(req) == "user:user-uuid-1234"


def test_get_rate_limit_key_anonymous():
    req = _build_mock_request(
        headers={"x-real-ip": "203.0.113.195"},
        user_id=None,
    )
    assert get_rate_limit_key(req) == "ip:203.0.113.195"


class patch_env:
    def __init__(self, envs: dict[str, str]):
        self.envs = envs
        self.old: dict[str, str | None] = {}

    def __enter__(self):
        for k, v in self.envs.items():
            self.old[k] = os.environ.get(k)
            if v:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]

    def __exit__(self, *args):
        for k, v in self.old.items():
            if v is not None:
                os.environ[k] = v
            elif k in os.environ:
                del os.environ[k]
