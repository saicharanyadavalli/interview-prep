"""Unit tests for the LeetCode GitHub webhook receiver AWS Lambda handler."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

# Add the lambda directory to sys.path so we can import handler
LAMBDA_DIR = Path(__file__).resolve().parents[3] / "infrastructure" / "lambda" / "github_webhook_receiver"
if str(LAMBDA_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDA_DIR))

import handler


TEST_SECRET = "super-secret-webhook-key-12345"
TEST_REPO = "doocs/leetcode"
TEST_BRANCH = "refs/heads/main"
TEST_QUEUE_URL = "https://sqs.ap-south-2.amazonaws.com/123456789012/interview-prep-leetcode-sync-queue-personal"


def compute_signature(payload_bytes: bytes, secret: str = TEST_SECRET) -> str:
    """Helper to compute GitHub HMAC-SHA256 signature header."""
    digest = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_event(
    body: dict[str, Any] | str,
    event_type: str = "push",
    delivery_id: str = "delivery-test-uuid-111",
    signature: str | None = None,
    is_base64: bool = False,
    include_signature: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Construct an API Gateway HTTP API v2 payload event."""
    if isinstance(body, dict):
        raw_str = json.dumps(body)
    else:
        raw_str = body

    raw_bytes = raw_str.encode("utf-8")

    if signature is None and include_signature:
        sig_header = compute_signature(raw_bytes, TEST_SECRET)
    elif not include_signature:
        sig_header = None
    else:
        sig_header = signature

    if is_base64:
        encoded_body = base64.b64encode(raw_bytes).decode("ascii")
    else:
        encoded_body = raw_str

    headers = {
        "content-type": "application/json",
        "x-github-delivery": delivery_id,
        "x-github-event": event_type,
    }
    if sig_header:
        headers["x-hub-signature-256"] = sig_header

    if extra_headers:
        headers.update(extra_headers)

    return {
        "version": "2.0",
        "routeKey": "POST /github/webhook",
        "rawPath": "/github/webhook",
        "headers": headers,
        "body": encoded_body,
        "isBase64Encoded": is_base64,
    }


@pytest.fixture(autouse=True)
def setup_lambda_env(monkeypatch):
    """Ensure consistent environment variables and reset caches for every test."""
    monkeypatch.setenv("WEBHOOK_SECRET_ARN", "arn:aws:secretsmanager:ap-south-2:123456789012:secret:test-secret")
    monkeypatch.setenv("SQS_QUEUE_URL", TEST_QUEUE_URL)
    monkeypatch.setenv("CONFIGURED_REPO", TEST_REPO)
    monkeypatch.setenv("CONFIGURED_BRANCH", TEST_BRANCH)
    monkeypatch.setenv("QUESTIONS_PATH", "solution/")

    handler.reset_secret_cache()
    handler.reset_clients()

    # Default Secrets Manager mock returning TEST_SECRET
    mock_secrets_client = MagicMock()
    mock_secrets_client.get_secret_value.return_value = {
        "SecretString": TEST_SECRET
    }
    monkeypatch.setattr(handler, "get_secrets_client", lambda: mock_secrets_client)

    # Default SQS mock returning success
    mock_sqs_client = MagicMock()
    mock_sqs_client.send_message.return_value = {"MessageId": "msg-uuid-999"}
    monkeypatch.setattr(handler, "get_sqs_client", lambda: mock_sqs_client)

    yield


# ── HMAC Signature Tests ──────────────────────────────────────────────────────

def test_verify_signature_valid():
    """Verify valid HMAC-SHA256 signatures pass verification."""
    body = b'{"hello": "world"}'
    sig = compute_signature(body, TEST_SECRET)
    assert handler.verify_signature(body, sig, TEST_SECRET) is True


def test_verify_signature_invalid():
    """Verify altered body or incorrect secret fails signature check."""
    body = b'{"hello": "world"}'
    wrong_sig = compute_signature(b'{"hello": "tampered"}', TEST_SECRET)
    assert handler.verify_signature(body, wrong_sig, TEST_SECRET) is False

    wrong_key_sig = compute_signature(body, "wrong-key")
    assert handler.verify_signature(body, wrong_key_sig, TEST_SECRET) is False


def test_verify_signature_missing_or_malformed():
    """Verify missing, empty, or malformed prefix signature headers return False."""
    body = b'{"hello": "world"}'
    assert handler.verify_signature(body, None, TEST_SECRET) is False
    assert handler.verify_signature(body, "", TEST_SECRET) is False
    assert handler.verify_signature(body, "invalidprefix12345", TEST_SECRET) is False
    assert handler.verify_signature(body, "sha1=abcdef", TEST_SECRET) is False


# ── Secret Retrieval & Caching Tests ──────────────────────────────────────────

def test_get_webhook_secret_caching():
    """Verify Secrets Manager is called once and cached across subsequent calls."""
    mock_secrets = MagicMock()
    mock_secrets.get_secret_value.return_value = {"SecretString": "cached-secret-val"}

    # First call retrieves from client
    s1 = handler.get_webhook_secret(mock_secrets)
    assert s1 == "cached-secret-val"
    assert mock_secrets.get_secret_value.call_count == 1

    # Second call uses in-memory cache
    s2 = handler.get_webhook_secret(mock_secrets)
    assert s2 == "cached-secret-val"
    assert mock_secrets.get_secret_value.call_count == 1

    # After reset, fetches fresh
    handler.reset_secret_cache()
    s3 = handler.get_webhook_secret(mock_secrets)
    assert s3 == "cached-secret-val"
    assert mock_secrets.get_secret_value.call_count == 2


def test_get_webhook_secret_json_string():
    """Verify secret is extracted if stored as a JSON object with key webhook_secret."""
    mock_secrets = MagicMock()
    mock_secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({"webhook_secret": "extracted-from-json"})
    }
    secret = handler.get_webhook_secret(mock_secrets)
    assert secret == "extracted-from-json"


def test_get_webhook_secret_binary():
    """Verify secret stored as SecretBinary is properly decoded."""
    mock_secrets = MagicMock()
    mock_secrets.get_secret_value.return_value = {
        "SecretBinary": b"binary-secret-val"
    }
    secret = handler.get_webhook_secret(mock_secrets)
    assert secret == "binary-secret-val"


# ── GitHub Event Handling Tests ───────────────────────────────────────────────

def test_ping_event():
    """Verify ping events respond with 200 pong and hook_id without enqueueing to SQS."""
    mock_sqs = MagicMock()
    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(
            body={"zen": "Non-blocking is better than blocking.", "hook_id": 987654},
            event_type="ping",
        )
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "pong"
        assert body["hook_id"] == 987654
        mock_sqs.send_message.assert_not_called()


def test_ignored_non_push_event():
    """Verify events other than ping and push return 200 ignored."""
    mock_sqs = MagicMock()
    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(
            body={"action": "opened", "issue": {"id": 1}},
            event_type="issues",
        )
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "ignored event type"
        assert body["event"] == "issues"
        mock_sqs.send_message.assert_not_called()


def test_push_event_with_matching_solution_files():
    """Verify push events touching solution/ directory are enqueued to SQS."""
    mock_sqs = MagicMock()
    mock_sqs.send_message.return_value = {"MessageId": "sqs-msg-123"}

    payload = {
        "ref": "refs/heads/main",
        "before": "0000000000000000000000000000000000000001",
        "after": "0000000000000000000000000000000000000002",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [
            {
                "id": "commit-1",
                "added": ["solution/0001.two-sum.py", "solution/0002.add-two-numbers.py"],
                "modified": ["README.md"],
                "removed": [],
            }
        ],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push", delivery_id="deliv-abc")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["message"] == "queued"
        assert body["delivery_id"] == "deliv-abc"

        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == TEST_QUEUE_URL
        sent_msg = json.loads(call_kwargs["MessageBody"])
        assert sent_msg["delivery_id"] == "deliv-abc"
        assert sent_msg["event"] == "push"
        assert sent_msg["repository"] == "doocs/leetcode"
        assert sent_msg["ref"] == "refs/heads/main"
        assert sent_msg["before_sha"] == "0000000000000000000000000000000000000001"
        assert sent_msg["after_sha"] == "0000000000000000000000000000000000000002"
        assert "solution/0001.two-sum.py" in sent_msg["changed_paths"]
        assert "solution/0002.add-two-numbers.py" in sent_msg["changed_paths"]
        assert "README.md" not in sent_msg["changed_paths"]
        assert sent_msg["needs_investigation"] is False
        assert "timestamp" in sent_msg


def test_push_event_with_non_matching_files():
    """Verify push events that do not touch solution/ are ignored and not enqueued."""
    mock_sqs = MagicMock()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [
            {
                "id": "commit-1",
                "added": ["docs/architecture.md"],
                "modified": ["README.md", ".github/workflows/ci.yml"],
                "removed": [],
            }
        ],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "no questions affected"
        mock_sqs.send_message.assert_not_called()


def test_push_event_with_truncated_commits():
    """Verify push events with truncated=True are enqueued with needs_investigation=True."""
    mock_sqs = MagicMock()
    mock_sqs.send_message.return_value = {"MessageId": "msg-truncated-1"}

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "doocs/leetcode"},
        "truncated": True,
        "commits": [],
        "head_commit": {
            "id": "head-sha-777",
            "added": ["solution/0100.same-tree.py"],
        },
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["message"] == "queued"

        mock_sqs.send_message.assert_called_once()
        sent_msg = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert sent_msg["needs_investigation"] is True
        assert sent_msg["after_sha"] == "head-sha-777"
        assert "solution/0100.same-tree.py" in sent_msg["changed_paths"]


def test_push_event_with_empty_commits():
    """Verify force push / empty commit range sets needs_investigation=True and enqueues."""
    mock_sqs = MagicMock()
    mock_sqs.send_message.return_value = {"MessageId": "msg-empty-commits"}

    payload = {
        "ref": "refs/heads/main",
        "before": "sha-old",
        "after": "sha-new",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 202
        body = json.loads(response["body"])
        assert body["message"] == "queued"

        mock_sqs.send_message.assert_called_once()
        sent_msg = json.loads(mock_sqs.send_message.call_args[1]["MessageBody"])
        assert sent_msg["needs_investigation"] is True
        assert sent_msg["before_sha"] == "sha-old"
        assert sent_msg["after_sha"] == "sha-new"


def test_repository_mismatch():
    """Verify events from unexpected repositories are ignored without enqueueing."""
    mock_sqs = MagicMock()
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "unauthorized/random-repo"},
        "commits": [{"added": ["solution/0001.two-sum.py"]}],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "ignored repository"
        mock_sqs.send_message.assert_not_called()


def test_branch_mismatch():
    """Verify pushes to unmonitored branches are ignored without enqueueing."""
    mock_sqs = MagicMock()
    payload = {
        "ref": "refs/heads/feature/dark-mode",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [{"added": ["solution/0001.two-sum.py"]}],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "ignored ref"
        mock_sqs.send_message.assert_not_called()


def test_branch_deletion_ignored():
    """Verify branch deletion notifications are ignored without enqueueing."""
    mock_sqs = MagicMock()
    payload = {
        "ref": "refs/heads/main",
        "deleted": True,
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "branch deletion ignored"
        mock_sqs.send_message.assert_not_called()


# ── Error & Edge Case Tests ───────────────────────────────────────────────────

def test_missing_signature_header_returns_401():
    """Verify request without X-Hub-Signature-256 header returns HTTP 401."""
    event = build_event(
        body={"some": "payload"},
        include_signature=False,
    )
    response = handler.lambda_handler(event)
    assert response["statusCode"] == 401
    assert "Missing X-Hub-Signature-256" in json.loads(response["body"])["error"]


def test_invalid_signature_returns_401():
    """Verify invalid HMAC signature returns HTTP 401."""
    event = build_event(
        body={"some": "payload"},
        signature="sha256=0000000000000000000000000000000000000000000000000000000000000000",
    )
    response = handler.lambda_handler(event)
    assert response["statusCode"] == 401
    assert "Invalid signature" in json.loads(response["body"])["error"]


def test_missing_event_header_returns_400():
    """Verify request without X-GitHub-Event header returns HTTP 400."""
    event = build_event(body={"some": "payload"})
    event["headers"].pop("x-github-event", None)
    response = handler.lambda_handler(event)
    assert response["statusCode"] == 400
    assert "Missing X-GitHub-Event" in json.loads(response["body"])["error"]


def test_malformed_json_body_returns_400():
    """Verify non-JSON payload returns HTTP 400."""
    raw_bad_json = "this is definitely not valid json"
    event = build_event(
        body=raw_bad_json,
        signature=compute_signature(raw_bad_json.encode("utf-8")),
    )
    response = handler.lambda_handler(event)
    assert response["statusCode"] == 400
    assert "Malformed JSON payload" in json.loads(response["body"])["error"]


def test_base64_encoded_payload():
    """Verify isBase64Encoded payloads are decoded and handled properly."""
    mock_sqs = MagicMock()
    mock_sqs.send_message.return_value = {"MessageId": "b64-msg-1"}

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [{"added": ["solution/0001.two-sum.py"]}],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(
            body=payload,
            event_type="push",
            is_base64=True,
        )
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 202
        mock_sqs.send_message.assert_called_once()


def test_sqs_failure_returns_500():
    """Verify SQS client error returns HTTP 500 without crashing."""
    mock_sqs = MagicMock()
    mock_sqs.send_message.side_effect = ClientError(
        {"Error": {"Code": "ServiceUnavailable", "Message": "SQS is down"}},
        "SendMessage",
    )

    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "doocs/leetcode"},
        "commits": [{"added": ["solution/0001.two-sum.py"]}],
    }

    with patch.object(handler, "get_sqs_client", return_value=mock_sqs):
        event = build_event(body=payload, event_type="push")
        response = handler.lambda_handler(event)

        assert response["statusCode"] == 500
        assert "Failed to enqueue message" in json.loads(response["body"])["error"]


def test_secrets_manager_failure_returns_500(monkeypatch):
    """Verify Secrets Manager failure returns HTTP 500 without leaking secrets."""
    mock_secrets = MagicMock()
    mock_secrets.get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}},
        "GetSecretValue",
    )
    monkeypatch.setattr(handler, "get_secrets_client", lambda: mock_secrets)

    event = build_event(body={"some": "data"})
    response = handler.lambda_handler(event)

    assert response["statusCode"] == 500
    assert "retrieving secret" in json.loads(response["body"])["error"]
