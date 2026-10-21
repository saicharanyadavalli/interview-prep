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
    CommitStaleness,
    LeetCodeSyncWorker,
    filter_and_prioritize_markdown_files,
    is_candidate_question_file,
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
    def test_is_candidate_question_file_filters_non_problem_markdown(self):
        assert is_candidate_question_file("solution/README.md") is False
        assert is_candidate_question_file("solution/README_EN.md") is False
        assert is_candidate_question_file("solution/template.md") is False
        assert is_candidate_question_file("solution/0000-0099/README.md") is False
        assert is_candidate_question_file("solution/0000-0099/README_EN.md") is False
        assert is_candidate_question_file("solution/CONTRIBUTING.md") is False
        assert is_candidate_question_file("docs/architecture.md") is False

        # Legitimate question solutions
        assert is_candidate_question_file("solution/0000-0099/0001.Two Sum/README.md") is True
        assert is_candidate_question_file("solution/0000-0099/0001.Two Sum/README_EN.md") is True
        assert is_candidate_question_file("solution/0001.Two Sum/README_EN.md") is True
        assert is_candidate_question_file("solution/0001 - Two Sum.md") is True

    def test_filter_and_prioritize_markdown_files(self):
        paths = [
            "solution/README.md",
            "solution/template.md",
            "solution/0000-0099/README.md",
            "solution/0000-0099/0001.Two Sum/README.md",
            "solution/0000-0099/0001.Two Sum/README_EN.md",
            "solution/0000-0099/0001.Two Sum/Solution.py",
            "solution/0000-0099/0002.Add Two Numbers/README.md",
            "solution/0000-0099/0003.Longest Substring/README_EN.md",
            "docs/architecture.png",
        ]
        result = filter_and_prioritize_markdown_files(paths)

        # Non-problem files excluded
        assert "solution/README.md" not in result
        assert "solution/template.md" not in result
        assert "solution/0000-0099/README.md" not in result

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
                result = worker.process_message(message)

        assert result is False
        mock_sync_service.sync_problem.assert_not_called()
        # Final completion should be recorded with status failed
        mock_sync_service.record_sync_completion.assert_called_once()
        call_kwargs = mock_sync_service.record_sync_completion.call_args[1]
        assert call_kwargs["status"] == "failed"
        assert call_kwargs["files_failed"] == 1
        mock_sqs_client.delete_message.assert_not_called()


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
        concrete_sha = "abcdef0123456789abcdef0123456789abcdef01"
        with patch.object(worker, "resolve_commit_sha", return_value=concrete_sha) as mock_resolve:
            with patch.object(worker, "fetch_tree_files", return_value=["solution/0000-0099/0001.Two Sum/README_EN.md"]) as mock_tree:
                with patch.object(worker, "process_message_payload", return_value=True) as mock_payload:
                    result = worker.run_full_sync(dry_run=True)

        assert result is True
        mock_resolve.assert_called_once_with("main")
        mock_tree.assert_called_once_with(concrete_sha)
        mock_payload.assert_called_once()
        payload = mock_payload.call_args[0][0]
        assert payload["event"] == "full_sync"
        assert payload["after_sha"] == concrete_sha
        assert payload["changed_paths"] == ["solution/0000-0099/0001.Two Sum/README_EN.md"]
        assert mock_payload.call_args[1]["dry_run"] is True

    def test_run_full_sync_fails_when_branch_unresolvable(self, worker):
        with patch.object(worker, "resolve_commit_sha", return_value=None) as mock_resolve:
            with patch.object(worker, "fetch_tree_files") as mock_tree:
                result = worker.run_full_sync(dry_run=False)

        assert result is False
        mock_resolve.assert_called_once_with("main")
        mock_tree.assert_not_called()

    def test_run_commit_sync(self, worker):
        concrete_sha = "1234567890abcdef1234567890abcdef12345678"
        with patch.object(worker, "resolve_commit_sha", return_value=concrete_sha) as mock_resolve:
            with patch.object(worker, "process_message_payload", return_value=True) as mock_payload:
                result = worker.run_commit_sync("short-sha", dry_run=False)

        assert result is True
        mock_resolve.assert_called_once_with("short-sha")
        mock_payload.assert_called_once()
        payload = mock_payload.call_args[0][0]
        assert payload["event"] == "manual_push"
        assert payload["after_sha"] == concrete_sha
        assert payload["needs_investigation"] is True
        assert mock_payload.call_args[1]["dry_run"] is False


# -----------------------------------------------------------------------------
# 10. Commit Resolution & Staleness Tests
# -----------------------------------------------------------------------------
class TestCommitResolutionAndStaleness:
    def test_resolve_40_char_sha_returns_immediately(self, worker):
        sha = "a" * 40
        assert worker.resolve_commit_sha(sha) == sha

    @patch("requests.get")
    def test_resolve_branch_queries_commits_api(self, mock_get, worker):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"sha": "b" * 40}
        mock_get.return_value = mock_resp

        resolved = worker.resolve_commit_sha("main")
        assert resolved == "b" * 40
        mock_get.assert_called_once()
        assert "commits/main" in mock_get.call_args[0][0]

    def test_identical_sha_is_stale(self, worker):
        assert worker.is_commit_stale("abc", "abc") is True

    @patch("requests.get")
    def test_ancestor_commit_is_stale_when_last_synced_is_ahead(self, mock_get, worker):
        # Compare API: base=incoming, head=last_synced. If head is 'ahead', incoming is older -> stale
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ahead"}
        mock_get.return_value = mock_resp

        assert worker.is_commit_stale("commit-old", "commit-new") is True

    @patch("requests.get")
    def test_newer_commit_is_not_stale_when_last_synced_is_behind(self, mock_get, worker):
        # Compare API: base=incoming, head=last_synced. If head is 'behind', incoming is newer -> not stale
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "behind"}
        mock_get.return_value = mock_resp

        assert worker.is_commit_stale("commit-newer", "commit-older") is False

    @patch("requests.get")
    def test_compare_api_error_returns_undetermined(self, mock_get, worker):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        staleness = worker.check_commit_staleness("commit-incoming", "commit-synced")
        assert staleness == CommitStaleness.UNDETERMINED
        # is_commit_stale backward-compatible helper returns False
        assert worker.is_commit_stale("commit-incoming", "commit-synced") is False

    @patch("requests.get")
    def test_compare_api_error_prevents_processing_and_checkpoint_regression(
        self, mock_get, worker, mock_sqs_client, mock_sync_service
    ):
        """Regression test: When GitHub Compare API returns HTTP 500, worker must NOT process old commit,

        must NOT delete message from SQS (allowing retry), and must NOT advance or regress the checkpoint.
        """
        mock_sync_service.get_last_sync_sha.return_value = "newest-commit-sha-40chars111111111111111"
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "GitHub API Outage"
        mock_get.return_value = mock_resp

        payload = {
            "delivery_id": "del-500-outage",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "older-commit-sha-40chars2222222222222222",
            "changed_paths": ["solution/0001.Two Sum/README_EN.md"],
        }
        message = {
            "MessageId": "msg-500",
            "ReceiptHandle": "receipt-500",
            "Body": json.dumps(payload),
        }

        result = worker.process_message(message)

        # 1. Message processing reports failure
        assert result is False

        # 2. SQS message is NOT acknowledged so visibility timeout expires for retry
        mock_sqs_client.delete_message.assert_not_called()

        # 3. Problem sync is NOT executed
        mock_sync_service.sync_problem.assert_not_called()

        # 4. Checkpoint is NOT updated (record_sync_completion never called)
        mock_sync_service.record_sync_completion.assert_not_called()


# -----------------------------------------------------------------------------
# 11. Partial Success Prevention & DLQ Redrive Tests
# -----------------------------------------------------------------------------
class TestPartialSuccessPrevention:
    def test_mixed_successful_and_failed_files_prevents_ack_and_leaves_in_sqs(
        self, worker, mock_sqs_client, mock_sync_service, sample_parsed_problem
    ):
        """Mixed file outcomes must mark completion as failed, NOT update checkpoint, and NOT delete SQS message."""
        payload = {
            "delivery_id": "del-mixed",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "c0ffee1234567890c0ffee1234567890c0ffee12",
            "changed_paths": [
                "solution/0000-0099/0001.Two Sum/README_EN.md",
                "solution/0000-0099/0002.Add Two Numbers/README_EN.md",
            ],
            "needs_investigation": False,
        }
        message = {
            "MessageId": "msg-mixed",
            "ReceiptHandle": "receipt-mixed",
            "Body": json.dumps(payload),
        }

        # First file succeeds, second file fails to parse
        def _fake_fetch(path, sha):
            return "# Problem Content"

        def _fake_parse(content, filename_or_path=""):
            if "0001.Two Sum" in filename_or_path:
                return sample_parsed_problem
            return None  # Parsing fails for problem 2

        with patch.object(worker, "fetch_file_content", side_effect=_fake_fetch):
            with patch("workers.leetcode_sync_worker.parse_leetcode_markdown", side_effect=_fake_parse):
                with patch("workers.leetcode_sync_worker.validate_problem", return_value=(True, "")):
                    result = worker.process_message(message)

        # Must report failure for message handling
        assert result is False

        # SQS message MUST NOT be deleted so it remains eligible for retry and DLQ redrive
        mock_sqs_client.delete_message.assert_not_called()

        # Database audit log must record failure
        mock_sync_service.record_sync_completion.assert_called_once()
        comp_kwargs = mock_sync_service.record_sync_completion.call_args[1]
        assert comp_kwargs["status"] == "failed"
        assert comp_kwargs["files_added"] == 1
        assert comp_kwargs["files_failed"] == 1


# -----------------------------------------------------------------------------
# 12. Duplicate Delivery Handling
# -----------------------------------------------------------------------------
class TestDuplicateDeliveryHandling:
    def test_duplicate_delivery_already_successful_skips_and_acks(
        self, worker, mock_sqs_client, mock_sync_service
    ):
        mock_sync_service.get_delivery_status.return_value = "success"
        payload = {
            "delivery_id": "del-dup-success",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "sha-dup",
            "changed_paths": ["solution/0000-0099/0001.Two Sum/README_EN.md"],
        }
        message = {
            "MessageId": "msg-dup",
            "ReceiptHandle": "receipt-dup",
            "Body": json.dumps(payload),
        }

        result = worker.process_message(message)
        assert result is True
        mock_sync_service.sync_problem.assert_not_called()
        mock_sync_service.record_sync_start.assert_not_called()
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-dup",
        )

    def test_retry_of_previously_failed_delivery_reprocesses(
        self, worker, mock_sqs_client, mock_sync_service, sample_parsed_problem
    ):
        mock_sync_service.get_delivery_status.return_value = "failed"
        payload = {
            "delivery_id": "del-retry-after-fail",
            "repository": "doocs/leetcode",
            "ref": "refs/heads/main",
            "after_sha": "sha-retry",
            "changed_paths": ["solution/0000-0099/0001.Two Sum/README_EN.md"],
        }
        message = {
            "MessageId": "msg-retry",
            "ReceiptHandle": "receipt-retry",
            "Body": json.dumps(payload),
        }

        with patch.object(worker, "fetch_file_content", return_value="# markdown"):
            with patch("workers.leetcode_sync_worker.parse_leetcode_markdown", return_value=sample_parsed_problem):
                with patch("workers.leetcode_sync_worker.validate_problem", return_value=(True, "")):
                    result = worker.process_message(message)

        assert result is True
        mock_sync_service.record_sync_start.assert_called_once()
        mock_sync_service.sync_problem.assert_called_once()
        mock_sqs_client.delete_message.assert_called_once_with(
            QueueUrl=worker.queue_url,
            ReceiptHandle="receipt-retry",
        )
