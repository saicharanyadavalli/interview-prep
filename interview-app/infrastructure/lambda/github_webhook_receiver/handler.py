"""AWS Lambda function handling incoming GitHub webhooks for LeetCode pipeline.

Validates GitHub HMAC-SHA256 signatures using secrets retrieved from AWS Secrets Manager,
inspects commit payloads for question changes, and enqueues relevant updates to Amazon SQS.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

# Configure structured JSON logger
logger = logging.getLogger("github_webhook_receiver")
logger.setLevel(logging.INFO)

# Global in-memory cache for Secrets Manager secret
_CACHED_SECRET: str | None = None
_SECRET_FETCHED_AT: float = 0.0
DEFAULT_CACHE_TTL_SECONDS: int = 300  # 5 minutes

# Cached AWS clients
_SQS_CLIENT: Any = None
_SECRETS_CLIENT: Any = None


def reset_secret_cache() -> None:
    """Reset in-memory secret cache for testing."""
    global _CACHED_SECRET, _SECRET_FETCHED_AT
    _CACHED_SECRET = None
    _SECRET_FETCHED_AT = 0.0


def reset_clients() -> None:
    """Reset cached AWS SDK clients for testing."""
    global _SQS_CLIENT, _SECRETS_CLIENT
    _SQS_CLIENT = None
    _SECRETS_CLIENT = None


def get_sqs_client() -> Any:
    """Return a cached or newly initialized SQS client."""
    global _SQS_CLIENT
    if _SQS_CLIENT is None:
        _SQS_CLIENT = boto3.client("sqs")
    return _SQS_CLIENT


def get_secrets_client() -> Any:
    """Return a cached or newly initialized Secrets Manager client."""
    global _SECRETS_CLIENT
    if _SECRETS_CLIENT is None:
        _SECRETS_CLIENT = boto3.client("secretsmanager")
    return _SECRETS_CLIENT


def make_response(status_code: int, body_data: dict[str, Any]) -> dict[str, Any]:
    """Format an API Gateway HTTP API (payload format 2.0) response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body_data),
    }


def get_header(headers: dict[str, Any] | None, header_name: str) -> str | None:
    """Case-insensitive header lookup."""
    if not headers or not isinstance(headers, dict):
        return None
    target = header_name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return None


def get_webhook_secret(
    secrets_client: Any = None,
    ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
) -> str:
    """Retrieve webhook secret from AWS Secrets Manager with in-memory caching.

    Never logs secret contents.
    """
    global _CACHED_SECRET, _SECRET_FETCHED_AT

    now = time.time()
    if _CACHED_SECRET is not None and (now - _SECRET_FETCHED_AT) < ttl_seconds:
        return _CACHED_SECRET

    secret_id = os.environ.get("WEBHOOK_SECRET_ARN") or os.environ.get("WEBHOOK_SECRET_NAME")
    if not secret_id:
        raise ValueError("Missing WEBHOOK_SECRET_ARN or WEBHOOK_SECRET_NAME environment variable")

    client = secrets_client or get_secrets_client()
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except (ClientError, BotoCoreError) as exc:
        logger.error(
            json.dumps({
                "action": "get_secret",
                "status": "failed",
                "error_type": type(exc).__name__,
            })
        )
        raise

    if "SecretString" in response:
        raw_secret = response["SecretString"]
        try:
            parsed = json.loads(raw_secret)
            if isinstance(parsed, dict):
                # Handle secret stored as JSON key-value
                secret_value = (
                    parsed.get("webhook_secret")
                    or parsed.get("secret")
                    or parsed.get("github_webhook_secret")
                    or raw_secret
                )
            else:
                secret_value = raw_secret
        except (json.JSONDecodeError, TypeError):
            secret_value = raw_secret
    elif "SecretBinary" in response:
        secret_value = response["SecretBinary"].decode("utf-8")
    else:
        raise ValueError("Secret response missing both SecretString and SecretBinary")

    _CACHED_SECRET = str(secret_value).strip()
    _SECRET_FETCHED_AT = now
    return _CACHED_SECRET


def verify_signature(body_bytes: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify GitHub HMAC-SHA256 signature using constant-time comparison.

    Never logs secret or signature.
    """
    if not signature_header or not secret:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    received_digest = signature_header[len(prefix):].strip()
    expected_digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_digest, received_digest)


def inspect_commits(
    payload: dict[str, Any],
    questions_path: str,
) -> tuple[bool, list[str], bool]:
    """Inspect commits in push payload for question path modifications.

    Returns:
        (has_question_changes, matching_paths, needs_investigation)
    """
    is_truncated = payload.get("truncated") is True
    commits = payload.get("commits")

    # If truncated or commits missing/empty (e.g. force push or large commit range),
    # flag for worker investigation so tree comparison is performed.
    if is_truncated or commits is None or len(commits) == 0:
        # Check if head_commit has any paths we can at least observe
        candidate_paths: list[str] = []
        head_commit = payload.get("head_commit")
        if isinstance(head_commit, dict):
            for key in ("added", "modified", "removed"):
                for p in head_commit.get(key, []):
                    if isinstance(p, str):
                        candidate_paths.append(p)
        matching = [p for p in candidate_paths if p.startswith(questions_path)]
        return bool(matching), matching, True

    all_changed_paths: list[str] = []
    for commit in commits:
        if not isinstance(commit, dict):
            continue
        for key in ("added", "modified", "removed"):
            for p in commit.get(key, []):
                if isinstance(p, str):
                    all_changed_paths.append(p)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_paths: list[str] = []
    for p in all_changed_paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)

    matching_paths = [p for p in unique_paths if p.startswith(questions_path)]
    has_question_changes = len(matching_paths) > 0

    return has_question_changes, matching_paths, False


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Entry point for API Gateway HTTP API v2 GitHub webhook requests."""
    headers = event.get("headers") or {}
    delivery_id = get_header(headers, "x-github-delivery") or "unknown"
    event_type = get_header(headers, "x-github-event")

    # 1. Validate X-GitHub-Event header presence
    if not event_type:
        logger.warning(
            json.dumps({
                "action": "validate_event",
                "status": "missing_event_header",
                "delivery_id": delivery_id,
            })
        )
        return make_response(400, {"error": "Missing X-GitHub-Event header"})

    # 2. Extract and decode body bytes
    raw_body = event.get("body", "")
    if raw_body is None:
        raw_body = ""

    is_base64 = event.get("isBase64Encoded", False)
    if is_base64:
        try:
            body_bytes = base64.b64decode(raw_body)
        except Exception:
            logger.warning(
                json.dumps({
                    "action": "decode_body",
                    "status": "invalid_base64",
                    "delivery_id": delivery_id,
                })
            )
            return make_response(400, {"error": "Invalid base64 payload body"})
    else:
        body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body

    # 3. Retrieve webhook secret and verify HMAC-SHA256 signature
    signature_header = get_header(headers, "x-hub-signature-256")
    if not signature_header:
        logger.warning(
            json.dumps({
                "action": "verify_signature",
                "status": "missing_signature",
                "delivery_id": delivery_id,
            })
        )
        return make_response(401, {"error": "Missing X-Hub-Signature-256 header"})

    try:
        secret = get_webhook_secret()
    except Exception as exc:
        logger.error(
            json.dumps({
                "action": "retrieve_secret",
                "status": "error",
                "delivery_id": delivery_id,
                "error_type": type(exc).__name__,
            })
        )
        return make_response(500, {"error": "Internal server error retrieving secret"})

    if not verify_signature(body_bytes, signature_header, secret):
        logger.warning(
            json.dumps({
                "action": "verify_signature",
                "status": "invalid_signature",
                "delivery_id": delivery_id,
            })
        )
        return make_response(401, {"error": "Invalid signature"})

    # 4. Parse JSON payload
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        logger.warning(
            json.dumps({
                "action": "parse_payload",
                "status": "malformed_json",
                "delivery_id": delivery_id,
            })
        )
        return make_response(400, {"error": "Malformed JSON payload"})

    if not isinstance(payload, dict):
        return make_response(400, {"error": "Payload must be a JSON object"})

    # 5. Handle GitHub ping event
    if event_type == "ping":
        hook_id = payload.get("hook_id")
        logger.info(
            json.dumps({
                "action": "ping_received",
                "delivery_id": delivery_id,
                "hook_id": hook_id,
            })
        )
        return make_response(200, {"message": "pong", "hook_id": hook_id})

    # 6. Ignore non-push events
    if event_type != "push":
        logger.info(
            json.dumps({
                "action": "ignore_event",
                "event": event_type,
                "delivery_id": delivery_id,
            })
        )
        return make_response(200, {"message": "ignored event type", "event": event_type})

    # 7. Validate repository match
    configured_repo = os.environ.get("CONFIGURED_REPO", "doocs/leetcode")
    repo_data = payload.get("repository") or {}
    repo_full_name = repo_data.get("full_name") if isinstance(repo_data, dict) else None

    if repo_full_name != configured_repo:
        logger.info(
            json.dumps({
                "action": "ignore_repository",
                "delivery_id": delivery_id,
                "repository": repo_full_name,
                "expected": configured_repo,
            })
        )
        return make_response(
            200,
            {"message": "ignored repository", "repository": repo_full_name},
        )

    # 8. Validate branch/ref match
    configured_branch = os.environ.get("CONFIGURED_BRANCH", "refs/heads/main")
    # Normalize branch configuration (e.g. 'main' -> 'refs/heads/main')
    normalized_configured_branch = (
        configured_branch
        if configured_branch.startswith("refs/heads/")
        else f"refs/heads/{configured_branch}"
    )

    ref = payload.get("ref") or ""
    if ref != normalized_configured_branch and ref != configured_branch:
        logger.info(
            json.dumps({
                "action": "ignore_branch",
                "delivery_id": delivery_id,
                "ref": ref,
                "expected": normalized_configured_branch,
            })
        )
        return make_response(200, {"message": "ignored ref", "ref": ref})

    # 9. Ignore branch deletions
    if payload.get("deleted") is True:
        logger.info(
            json.dumps({
                "action": "ignore_deletion",
                "delivery_id": delivery_id,
                "ref": ref,
            })
        )
        return make_response(200, {"message": "branch deletion ignored"})

    # 10. Inspect paths
    questions_path = os.environ.get("QUESTIONS_PATH", "solution/")
    has_question_changes, matching_paths, needs_investigation = inspect_commits(
        payload, questions_path
    )

    # If there are explicit commits, none of which touch questions_path, and not truncated
    if not needs_investigation and not has_question_changes:
        logger.info(
            json.dumps({
                "action": "no_questions_affected",
                "delivery_id": delivery_id,
                "ref": ref,
            })
        )
        return make_response(200, {"message": "no questions affected"})

    # 11. Prepare SQS message payload
    sqs_queue_url = os.environ.get("SQS_QUEUE_URL")
    if not sqs_queue_url:
        logger.error(
            json.dumps({
                "action": "enqueue_message",
                "status": "missing_sqs_queue_url",
                "delivery_id": delivery_id,
            })
        )
        return make_response(500, {"error": "SQS_QUEUE_URL environment variable is not configured"})

    before_sha = payload.get("before") or ""
    after_sha = payload.get("after") or ""
    if not after_sha and isinstance(payload.get("head_commit"), dict):
        after_sha = payload.get("head_commit", {}).get("id", "")

    timestamp = datetime.now(timezone.utc).isoformat()

    message_body = {
        "delivery_id": delivery_id,
        "event": "push",
        "repository": repo_full_name or configured_repo,
        "ref": ref,
        "before_sha": before_sha,
        "after_sha": after_sha,
        "changed_paths": matching_paths,
        "needs_investigation": needs_investigation,
        "timestamp": timestamp,
    }

    sqs_client = get_sqs_client()
    try:
        sqs_response = sqs_client.send_message(
            QueueUrl=sqs_queue_url,
            MessageBody=json.dumps(message_body),
        )
        message_id = sqs_response.get("MessageId", "unknown")
        logger.info(
            json.dumps({
                "action": "message_enqueued",
                "delivery_id": delivery_id,
                "message_id": message_id,
                "needs_investigation": needs_investigation,
                "changed_count": len(matching_paths),
            })
        )
    except (ClientError, BotoCoreError) as exc:
        logger.error(
            json.dumps({
                "action": "enqueue_message",
                "status": "failed",
                "delivery_id": delivery_id,
                "error_type": type(exc).__name__,
            })
        )
        return make_response(500, {"error": "Failed to enqueue message to SQS"})

    return make_response(202, {"message": "queued", "delivery_id": delivery_id})
