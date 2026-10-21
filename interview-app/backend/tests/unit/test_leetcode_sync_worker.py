"""Unit tests for the LeetCode synchronization pipeline background worker.

Tests SQS polling, message JSON parsing, repository/branch validation,
stale commit skipping, GitHub compare API handling, Git Tree API fallback,
problem parser/sync service integration, --dry-run mode, upstream file removal handling,
and SQS message deletion / error retention behavior.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

from services.leetcode_parser import ParsedApproach, ParsedProblem
from workers.leetcode_sync_worker import (
    LeetCodeSyncWorker,
    filter_and_prioritize_markdown_files,
)


@pytest.fixture
def sample_parsed_problem():
    return ParsedProblem(
        qnum=1,
        title="Two Sum",
        slug="two-sum",
        difficulty="Easy",
        topic_tags=["Array", "Hash Table"],
        description_md="Given an array of integers nums and an integer target...",
        approaches=[
            ParsedApproach(
                approach_index=1,
                title="Hash Map",
                intuition_md="Use a hash map for O(1) lookups.",
                time_complexity="$O(n)$",
                space_complexity="$O(n)$",
                explanation_md="Store complements in a dictionary.",
            )
        ],
        code_solutions={"python": "class Solution:\n    def twoSum(self): pass"},
    )


@pytest.fixture
def mock_sync_service():
    service = MagicMock()
    service.get_last_sync_sha.return_value = None
    service.sync_problem.return_value = {
        "status": "added",
        "qnum": 1,
        "title": "Two Sum",
        "details": "Inserted",
    }
    return service


@pytest.fixture
def mock_sqs_client():
    sqs = MagicMock()
    sqs.receive_message.return_value = {"Messages": []}
    sqs.delete_message.return_value = {}
    return sqs


@pytest.fixture
def worker(mock_sync_service, mock_sqs_client):
    return LeetCodeSyncWorker(
        aws_region="ap-south-2",
        queue_url="https://sqs.ap-south-2.amazonaws.com/123456789012/test-queue",
        source_repo="doocs/leetcode",
        source_branch="main",
        questions_path="solution",
        github_token="ghp_test_token_12345",
        sync_service=mock_sync_service,
        sqs_client=mock_sqs_client,
        visibility_timeout=300,
        wait_time_seconds=1,
    )


# -----------------------------------------------------------------------------
# 1. Path Filtering & Prioritization
# -----------------------------------------------------------------------------
class TestPathFiltering:
    def test_filter_and_prioritize_markdown_files(self):
        paths = [
            "solution/0000-0099/0001.Two Sum/README.md",
            "solution/0000-0099/0001.Two Sum/README_EN.md",
            "solution/0000-0099/0001.Two Sum/Solution.py",
            "solution/0000-0099/0002.Add Two Numbers/README.md",
            "solution/0000-0099/0003.Longest Substring/README_EN.md",
            "docs/architecture.png",
        ]
        result = filter_and_prioritize_markdown_files(paths)

        # 0001 should only have README_EN.md (README.md omitted)
        assert "solution/0000-0099/0001.Two Sum/README_EN.md" in result
        assert "solution/0000-0099/0001.Two Sum/README.md" not in result

        # 0002 has only README.md, so it must be kept
        assert "solution/0000-0099/0002.Add Two Numbers/README.md" in result

        # 0003 has only README_EN.md, kept
        assert "solution/0000-0099/0003.Longest Substring/README_EN.md" in result

        # Non-md files excluded
        assert "solution/0000-0099/0001.Two Sum/Solution.py" not in result
        assert "docs/architecture.png" not in result


# -----------------------------------------------------------------------------
# 2. Token Resolution
# -----------------------------------------------------------------------------
class TestTokenResolution:
    def test_direct_github_token(self):
        w = LeetCodeSyncWorker(github_token="my-token")
        assert w.resolve_token() == "my-token"

    def test_secrets_manager_token_resolution(self):
        secrets_client = MagicMock()
        secrets_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"github_token": "secret-resolved-token"})
        }
        w = LeetCodeSyncWorker(
            github_token="",
            github_token_secret_arn="arn:aws:secretsmanager:ap-south-2:1234:secret:test",
            secrets_client=secrets_client,
        )
        assert w.resolve_token() == "secret-resolved-token"
        secrets_client.get_secret_value.assert_called_once_with(
            SecretId="arn:aws:secretsmanager:ap-south-2:1234:secret:test"
        )


# -----------------------------------------------------------------------------
# 3. SQS Message Polling & Lifecycle
# -----------------------------------------------------------------------------
class TestSQSWorkerLifecycle:
    def test_run_once_empty_queue(self, worker, mock_sqs_client):
        mock_sqs_client.receive_message.return_value = {"Messages": []}
        received = worker.run_once()
        assert received is False
        mock_sqs_client.delete_message.assert_not_called()

    def test_run_once_processes_and_acks_message(
        self, worker, mock_sqs_client, mock_sync_service, sample_parsed_problem
    ):
        payload = {
            "delivery_id": "del-12345",
            "event": "push",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "before_sha": "1111111",
            "after_sha": "2222222",
            "changed_paths": ["solution/0000-0099/0001.Two Sum/README_EN.md"],
            "needs_investigation": False,
        }
        mock_sqs_client.receive_message.return_value = {
            "Messages": [
                {
                    "MessageId": "msg-001",
                    "ReceiptHandle": "receipt-token-123",
                    "Body": json.dumps(payload),
                }
            ]
        }

        with patch.object(worker, "fetch_file_content", return_value="# [1. Two Sum]\nBody") as mock_fetch:
            with patch("workers.leetcode_sync_worker.parse_leetcode_markdown", return_value=sample_parsed_problem):
                with patch("workers.leetcode_sync_worker.validate_problem", return_value=(True, "")):
                    success = worker.run_once()

        assert success is True
        mock_fetch.assert_called_once_with("solution/0000-0099/0001.Two Sum/README_EN.md", "2222222")
        mock_sync_service.record_sync_start.assert_called_once_with(
            delivery_id="del-12345",
            commit_sha="2222222",
            repo="doocs/leetcode",
            branch="main",
        )
        mock_sync_service.sync_problem.assert_called_once_with(sample_parsed_problem, dry_run=False)
        mock_sync_service.record_sync_completion.assert_called_once()
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-token-123",
        )

    def test_stale_commit_skips_processing_and_deletes_message(
        self, worker, mock_sqs_client, mock_sync_service
    ):
        mock_sync_service.get_last_sync_sha.return_value = "already-synced-sha"
        payload = {
            "delivery_id": "del-stale",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "already-synced-sha",
            "changed_paths": ["solution/0001.Two Sum/README_EN.md"],
        }
        message = {
            "MessageId": "msg-stale",
            "ReceiptHandle": "receipt-stale",
            "Body": json.dumps(payload),
        }

        handled = worker.process_message(message)
        assert handled is True
        mock_sync_service.sync_problem.assert_not_called()
        mock_sync_service.record_sync_start.assert_not_called()
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-stale",
        )

    def test_mismatched_repo_or_branch_skips_and_acks(
        self, worker, mock_sqs_client, mock_sync_service
    ):
        payload = {
            "delivery_id": "del-unrelated",
            "repository": "other-owner/other-repo",
            "ref": "refs/heads/feature-branch",
            "after_sha": "3333333",
            "changed_paths": ["solution/README.md"],
        }
        message = {
            "MessageId": "msg-other",
            "ReceiptHandle": "receipt-other",
            "Body": json.dumps(payload),
        }

        handled = worker.process_message(message)
        assert handled is True
        mock_sync_service.sync_problem.assert_not_called()
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-other",
        )


# -----------------------------------------------------------------------------
# 4. Dry Run Flag Mode
# -----------------------------------------------------------------------------
class TestDryRunMode:
    def test_dry_run_does_not_mutate_db_or_history(
        self, worker, mock_sqs_client, mock_sync_service, sample_parsed_problem
    ):
        payload = {
            "delivery_id": "del-dry",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "sha-dry",
            "changed_paths": ["solution/0001.Two Sum/README_EN.md"],
            "needs_investigation": False,
        }
        message = {
            "MessageId": "msg-dry",
            "ReceiptHandle": "receipt-dry",
            "Body": json.dumps(payload),
        }

        with patch.object(worker, "fetch_file_content", return_value="# markdown"):
            with patch("workers.leetcode_sync_worker.parse_leetcode_markdown", return_value=sample_parsed_problem):
                with patch("workers.leetcode_sync_worker.validate_problem", return_value=(True, "")):
                    worker.process_message(message, dry_run=True)

        # sync_problem should be called with dry_run=True
        mock_sync_service.sync_problem.assert_called_once_with(sample_parsed_problem, dry_run=True)
        # History metadata methods should NOT be called in dry run mode
        mock_sync_service.record_sync_start.assert_not_called()
        mock_sync_service.record_sync_completion.assert_not_called()
        # Message should still be deleted upon completion
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-dry",
        )


# -----------------------------------------------------------------------------
# 5. GitHub Compare API and Tree Fallback
# -----------------------------------------------------------------------------
class TestGitHubCompareAndTreeFallback:
    @patch("requests.get")
    def test_compare_commits_success(self, mock_requests_get, worker):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ahead",
            "files": [
                {"filename": "solution/0001.Two Sum/README_EN.md", "status": "modified"},
                {"filename": "solution/0002.Add Two Numbers/README.md", "status": "added"},
                {"filename": "solution/0003.Longest Substring/README_EN.md", "status": "removed"},
            ],
        }
        mock_requests_get.return_value = mock_resp

        added_or_mod, removed = worker.compare_commits("1111", "2222")
        assert "solution/0001.Two Sum/README_EN.md" in added_or_mod
        assert "solution/0002.Add Two Numbers/README.md" in added_or_mod
        assert "solution/0003.Longest Substring/README_EN.md" in removed

    @patch("requests.get")
    def test_compare_commits_fallback_on_large_diff(self, mock_requests_get, worker):
        # When compare returns >= 300 files
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "ahead",
            "files": [{"filename": f"solution/{i}/README.md", "status": "modified"} for i in range(300)],
        }
        mock_requests_get.return_value = mock_resp

        with patch.object(worker, "fetch_tree_files", return_value=["solution/tree-file.md"]) as mock_tree:
            added_or_mod, removed = worker.compare_commits("1111", "2222")
            mock_tree.assert_called_once_with("2222")
            assert added_or_mod == ["solution/tree-file.md"]
            assert removed == []

    @patch("requests.get")
    def test_compare_commits_fallback_on_api_error(self, mock_requests_get, worker):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_requests_get.return_value = mock_resp

        with patch.object(worker, "fetch_tree_files", return_value=["solution/from-tree.md"]) as mock_tree:
            added_or_mod, removed = worker.compare_commits("1111", "2222")
            mock_tree.assert_called_once_with("2222")
            assert added_or_mod == ["solution/from-tree.md"]

    @patch("requests.get")
    def test_fetch_tree_files_filters_questions_path(self, mock_requests_get, worker):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "tree": [
                {"path": "solution/0001.Two Sum/README_EN.md", "type": "blob"},
                {"path": "solution/0002.Add/README.md", "type": "blob"},
                {"path": "solution/0001.Two Sum", "type": "tree"},
                {"path": "docs/README.md", "type": "blob"},
            ]
        }
        mock_requests_get.return_value = mock_resp

        files = worker.fetch_tree_files("main")
        assert "solution/0001.Two Sum/README_EN.md" in files
        assert "solution/0002.Add/README.md" in files
        assert "docs/README.md" not in files


# -----------------------------------------------------------------------------
# 6. Upstream File Removal Handling
# -----------------------------------------------------------------------------
class TestUpstreamFileRemoval:
    def test_upstream_file_removal_logs_warning_and_preserves_rds(
        self, worker, mock_sqs_client, mock_sync_service
    ):
        payload = {
            "delivery_id": "del-remove",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "before_sha": "before-sha",
            "after_sha": "after-sha",
            "changed_paths": [],
            "needs_investigation": True,
        }
        message = {
            "MessageId": "msg-rm",
            "ReceiptHandle": "receipt-rm",
            "Body": json.dumps(payload),
        }

        with patch.object(
            worker,
            "compare_commits",
            return_value=([], ["solution/0001.Two Sum/README_EN.md"]),
        ):
            with patch("workers.leetcode_sync_worker.logger.warning") as mock_warn:
                worker.process_message(message)

        # Check exact warning logged
        mock_warn.assert_any_call(
            "Upstream question file removed: %s (preserving database record for safety)",
            "solution/0001.Two Sum/README_EN.md",
        )
        # Database mutation should NOT delete anything
        mock_sync_service.sync_problem.assert_not_called()
        # Message should be acknowledged
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-rm",
        )


# -----------------------------------------------------------------------------
# 7. Parser Validation Failure & Error Handling
# -----------------------------------------------------------------------------
class TestParserAndValidationFailure:
    def test_invalid_problem_markdown_increments_failure(
        self, worker, mock_sqs_client, mock_sync_service
    ):
        payload = {
            "delivery_id": "del-invalid",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "sha-invalid",
            "changed_paths": ["solution/bad_file.md"],
            "needs_investigation": False,
        }
        message = {
            "MessageId": "msg-invalid",
            "ReceiptHandle": "receipt-invalid",
            "Body": json.dumps(payload),
        }

        with patch.object(worker, "fetch_file_content", return_value="# Malformed Problem Header"):
            with patch("workers.leetcode_sync_worker.parse_leetcode_markdown", return_value=None):
                worker.process_message(message)

        mock_sync_service.sync_problem.assert_not_called()
        # Final completion should be recorded with status failed
        mock_sync_service.record_sync_completion.assert_called_once()
        call_kwargs = mock_sync_service.record_sync_completion.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["files_failed"] == 1


# -----------------------------------------------------------------------------
# 8. Exception Handling and SQS DLQ Preservation
# -----------------------------------------------------------------------------
class TestExceptionHandling:
    def test_unexpected_exception_does_not_delete_message(
        self, worker, mock_sqs_client
    ):
        payload = {
            "delivery_id": "del-crash",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "sha-crash",
            "changed_paths": ["solution/0001.Two Sum/README_EN.md"],
        }
        message = {
            "MessageId": "msg-crash",
            "ReceiptHandle": "receipt-crash",
            "Body": json.dumps(payload),
        }

        with patch.object(worker, "process_message_payload", side_effect=RuntimeError("Database fatal connection error")):
            result = worker.process_message(message)

        # process_message must return False
        assert result is False
        # Crucial requirement: SQS delete_message must NOT be called so message can redrive to DLQ
        mock_sqs_client.delete_message.assert_not_called()


# -----------------------------------------------------------------------------
# 9. CLI Full Sync & Commit Sync
# -----------------------------------------------------------------------------
class TestCLIWorkflows:
    def test_run_full_sync(self, worker):
        with patch.object(worker, "fetch_tree_files", return_value=["solution/0001.Two Sum/README_EN.md"]) as mock_tree:
            with patch.object(worker, "process_message_payload") as mock_payload:
                worker.run_full_sync(dry_run=True)

        mock_tree.assert_called_once_with("main")
        mock_payload.assert_called_once()
        payload = mock_payload.call_args[0][0]
        assert payload["event"] == "full_sync"
        assert payload["changed_paths"] == ["solution/0001.Two Sum/README_EN.md"]
        assert mock_payload.call_args[1]["dry_run"] is True

    def test_run_commit_sync(self, worker):
        with patch.object(worker, "process_message_payload") as mock_payload:
            worker.run_commit_sync("commit-abc-999", dry_run=False)

        mock_payload.assert_called_once()
        payload = mock_payload.call_args[0][0]
        assert payload["event"] == "manual_push"
        assert payload["after_sha"] == "commit-abc-999"
        assert payload["needs_investigation"] is True
        assert mock_payload.call_args[1]["dry_run"] is False
