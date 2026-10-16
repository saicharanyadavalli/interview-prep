"""Integration tests for /assistant/ask endpoint."""

import json
from unittest.mock import patch
from fastapi.testclient import TestClient


def test_ask_assistant_in_scope_streams_sse_response(client: TestClient, mock_gemini_stream):
    """Verify POST /assistant/ask streams SSE data chunks for in-scope DSA doubts."""
    payload = {
        "interview_question": "Two Sum: Given array and target, find two indices.",
        "user_doubt": "How to optimize time complexity from O(n^2) to O(n)?",
        "conversation_history": [],
    }

    res = client.post("/assistant/ask", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    body = res.text
    assert "data: " in body
    assert "hash table" in body or "Consider" in body


def test_ask_assistant_out_of_scope_streams_redirection(client: TestClient):
    """Verify POST /assistant/ask streams polite redirection when user asks off-topic."""
    payload = {
        "interview_question": "Two Sum",
        "user_doubt": "What is the weather like in Tokyo right now?",
        "conversation_history": [],
    }

    res = client.post("/assistant/ask", json=payload)
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]

    body = res.text
    assert "DSA" in body or "interview" in body


def test_ask_assistant_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify POST /assistant/ask returns 401 when no auth credentials provided."""
    payload = {
        "interview_question": "Two Sum",
        "user_doubt": "Explain approach",
        "conversation_history": [],
    }

    res = unauth_client.post("/assistant/ask", json=payload)
    assert res.status_code == 401


def test_ask_assistant_invalid_payload_returns_422(client: TestClient):
    """Verify POST /assistant/ask rejects empty doubt or invalid schema with 422."""
    payload = {
        "interview_question": "",  # min_length=1
        "user_doubt": "",
    }
    res = client.post("/assistant/ask", json=payload)
    assert res.status_code == 422
