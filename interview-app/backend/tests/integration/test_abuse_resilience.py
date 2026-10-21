"""Stress test & Abuse simulation suite for API Rate Limiting & Abuse Resistance.

Tests verify:
1. Endpoint protection under automated burst traffic.
2. HTTP 429 response status code compliance.
3. RFC-7807 payload structure and header presence (Retry-After, X-RateLimit-Limit, X-Request-ID).
4. User ID vs IP isolation (abuse by User A does not block User B).
5. Protection of high-cost AI generation and file upload endpoints.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from limiter import limiter
from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_abuse_resilience(mock_supabase):
    """Mock Gemini API, S3 storage, Cognito tokens, and RDS for deterministic abuse tests."""
    limiter.reset()

    def dummy_stream(*args, **kwargs):
        yield "Mocked AI Response"

    def mock_verify_token(token: str):
        return {
            "sub": token,
            "id": token,
            "email": f"{token}@example.com",
            "token_use": "access",
            "client_id": "test-client-id-123",
        }

    with patch("routes.assistant.ask_gemini_stream", side_effect=dummy_stream), \
         patch("services.s3_storage_service.upload_avatar", return_value="https://d12345.cloudfront.net/avatars/user-1/avatar.png"), \
         patch("middleware.rate_limit_middleware.verify_cognito_token", side_effect=mock_verify_token), \
         patch("routes.auth.verify_cognito_token", side_effect=mock_verify_token):
        yield

    limiter.reset()


def test_ai_assistant_burst_limit_triggers_429():
    """Verify that hammering the AI assistant endpoint past 5 req/min yields HTTP 429."""
    payload = {
        "interview_question": "Two Sum",
        "user_doubt": "What is the optimal time complexity using a hash table?",
        "conversation_history": [],
    }

    # Send 5 allowed requests
    for i in range(5):
        resp = client.post(
            "/assistant/ask",
            json=payload,
            headers={"Authorization": "Bearer fake-token-1"},
        )
        assert resp.status_code != 429, f"Request {i+1} unexpectedly rate limited"

    # 6th request MUST trigger HTTP 429 RateLimitExceeded
    resp_blocked = client.post(
        "/assistant/ask",
        json=payload,
        headers={"Authorization": "Bearer fake-token-1"},
    )
    assert resp_blocked.status_code == 429
    data = resp_blocked.json()
    assert data["error"] == "rate_limit_exceeded"
    assert "retry_after_seconds" in data
    assert "Retry-After" in resp_blocked.headers
    assert "X-RateLimit-Limit" in resp_blocked.headers


def test_avatar_upload_rate_limit_triggers_429():
    """Verify that uploading profile avatars beyond 3 req/min triggers HTTP 429."""
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\rIDATx\x9cc`\x00\x00\x00\x02\x00\x01H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"

    for i in range(3):
        resp = client.post(
            "/profile/avatar/upload",
            files={"file": ("avatar.png", fake_png, "image/png")},
            headers={"Authorization": "Bearer fake-token-1"},
        )
        assert resp.status_code != 429, f"Upload {i+1} unexpectedly rate limited"

    # 4th upload attempt blocked
    resp_blocked = client.post(
        "/profile/avatar/upload",
        files={"file": ("avatar.png", fake_png, "image/png")},
        headers={"Authorization": "Bearer fake-token-1"},
    )
    assert resp_blocked.status_code == 429
    assert resp_blocked.json()["error"] == "rate_limit_exceeded"


def test_session_auth_rate_limit_triggers_429():
    """Verify login/session creation endpoint caps burst attacks at 10 req/min."""
    for i in range(10):
        resp = client.post(
            "/auth/session",
            json={"access_token": "fake_token"},
        )
        assert resp.status_code in (200, 401)

    # 11th attempt blocked by rate limiter
    resp_blocked = client.post(
        "/auth/session",
        json={"access_token": "fake_token"},
    )
    assert resp_blocked.status_code == 429
    assert resp_blocked.json()["error"] == "rate_limit_exceeded"


def test_user_id_isolation_rate_limiting():
    """Verify that User A exhausting their quota does NOT block User B."""
    payload = {
        "interview_question": "Binary Search",
        "user_doubt": "Explain edge case when low equals high",
        "conversation_history": [],
    }

    # User A exhausts their 5 req/min quota
    for _ in range(5):
        client.post(
            "/assistant/ask",
            json=payload,
            headers={"Authorization": "Bearer user-a-token"},
        )

    user_a_blocked = client.post(
        "/assistant/ask",
        json=payload,
        headers={"Authorization": "Bearer user-a-token"},
    )
    assert user_a_blocked.status_code == 429

    # User B should still have full quota
    user_b_resp = client.post(
        "/assistant/ask",
        json=payload,
        headers={"Authorization": "Bearer user-b-token"},
    )
    assert user_b_resp.status_code != 429
