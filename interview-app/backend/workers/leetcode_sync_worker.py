"""LeetCode synchronization pipeline background worker.

Independent long-polling SQS consumer running in Docker Compose on EC2.
Consumes GitHub push event notifications, retrieves changed LeetCode solution
markdown files from upstream repository, parses problems, and performs
transactional upserts into Amazon RDS PostgreSQL.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

# Ensure backend root is on sys.path for direct worker invocation
_BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

try:
    from logger import get_logger, setup_logging
    setup_logging()
    logger = get_logger("leetcode_sync_worker")
except Exception:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("leetcode_sync_worker")

from services.leetcode_parser import parse_leetcode_markdown, validate_problem
from services.leetcode_sync_service import LeetCodeSyncService


def is_candidate_question_file(path: str, questions_path: str = "solution") -> bool:
    """Determine whether a repository path is a potential LeetCode problem solution markdown file.

    Excludes root/template markdown files (e.g., solution/README.md, template.md) and range-index READMEs
    (e.g., solution/0000-0099/README.md) while including actual problem solutions
    (e.g., solution/0000-0099/0001.Two Sum/README_EN.md or solution/0001.Two Sum/README.md).
    """
    if not path or not path.lower().endswith(".md"):
        return False

    norm = path.replace("\\", "/").strip("/")
    q_prefix = questions_path.strip("/") + "/" if questions_path.strip("/") else ""

    if q_prefix and norm.startswith(q_prefix):
        rel_path = norm[len(q_prefix):]
    elif q_prefix and not norm.startswith(q_prefix):
        # Path is outside questions_path
        # But if it's already a relative question path without questions_path prefix, check if it looks like a question
        # e.g. starts with range like 0000-0099/ or problem folder like 0001.Two Sum/
        if re.match(r"^(?:\d+-\d+/)?(?:\d{1,5}[\.-]|\d{1,5}\s*-\s*)", norm):
            rel_path = norm
        else:
            return False
    else:
        rel_path = norm

    rel_lower = rel_path.lower()

    # Exclude root and non-question documentation files
    if rel_lower in (
        "readme.md",
        "readme_en.md",
        "template.md",
        "contributing.md",
        "license.md",
        "summary.md",
        "todo.md",
        "changelog.md",
    ):
        return False

    # Exclude range index READMEs e.g. "0000-0099/readme.md" or "0000-0099/readme_en.md"
    parts = rel_path.split("/")
    if len(parts) == 2 and re.match(r"^\d+-\d+$", parts[0]) and parts[1].lower() in ("readme.md", "readme_en.md"):
        return False

    return True


def filter_and_prioritize_markdown_files(
    paths: list[str], questions_path: str = "solution"
) -> list[str]:
    """Filter candidate problem files ending in .md and prioritize README_EN.md over README.md per directory."""
    md_paths = [p for p in paths if is_candidate_question_file(p, questions_path)]

    # Identify directories that contain a README_EN.md
    dirs_with_en: set[str] = set()
    for p in md_paths:
        norm = p.replace("\\", "/")
        if norm.endswith("/README_EN.md"):
            dirs_with_en.add(norm.rsplit("/", 1)[0])

    final_paths: list[str] = []
    for p in md_paths:
        norm = p.replace("\\", "/")
        dir_part = norm.rsplit("/", 1)[0] if "/" in norm else ""
        # If directory has README_EN.md in changed files, omit README.md
        if norm.endswith("/README.md") and dir_part in dirs_with_en:
            logger.info("Preferring README_EN.md over README.md for directory: %s", dir_part)
            continue
        final_paths.append(p)

    return final_paths


class CommitStaleness:
    """Distinct outcomes for commit staleness evaluation."""
    CONFIRMED_STALE = "confirmed_stale"
    CONFIRMED_NOT_STALE = "confirmed_not_stale"
    UNDETERMINED = "undetermined"


class LeetCodeSyncWorker:
    """Independent background worker consuming SQS sync messages."""

    def __init__(
        self,
        aws_region: Optional[str] = None,
        queue_url: Optional[str] = None,
        source_repo: Optional[str] = None,
        source_branch: Optional[str] = None,
        questions_path: Optional[str] = None,
        github_token: Optional[str] = None,
        github_token_secret_arn: Optional[str] = None,
        sync_service: Optional[LeetCodeSyncService] = None,
        sqs_client: Optional[Any] = None,
        secrets_client: Optional[Any] = None,
        visibility_timeout: int = 300,
        wait_time_seconds: int = 20,
    ) -> None:
        self.aws_region = aws_region or os.getenv("AWS_REGION", "ap-south-2")
        self.queue_url = queue_url or os.getenv("LEETCODE_SYNC_QUEUE_URL", "")
        self.source_repo = source_repo or os.getenv("LEETCODE_SOURCE_REPO", "doocs/leetcode")
        self.source_branch = source_branch or os.getenv("LEETCODE_SOURCE_BRANCH", "main")
        raw_path = questions_path or os.getenv("LEETCODE_QUESTIONS_PATH", "solution")
        self.questions_path = raw_path.rstrip("/\\")
        self.github_token = github_token or os.getenv("GITHUB_TOKEN", "")
        self.github_token_secret_arn = github_token_secret_arn or os.getenv("GITHUB_TOKEN_SECRET_ARN", "")
        self.visibility_timeout = visibility_timeout
        self.wait_time_seconds = wait_time_seconds

        self.sync_service = sync_service or LeetCodeSyncService()
        self._sqs_client = sqs_client
        self._secrets_client = secrets_client
        self._cached_token: Optional[str] = None
        self.stop_requested = False

    def get_sqs_client(self) -> Any:
        """Return cached or new boto3 SQS client."""
        if self._sqs_client is None:
            self._sqs_client = boto3.client("sqs", region_name=self.aws_region)
        return self._sqs_client

    def get_secrets_client(self) -> Any:
        """Return cached or new boto3 Secrets Manager client."""
        if self._secrets_client is None:
            self._secrets_client = boto3.client("secretsmanager", region_name=self.aws_region)
        return self._secrets_client

    def resolve_token(self) -> str:
        """Resolve GitHub personal access token with optional Secrets Manager lookup."""
        if self.github_token:
            return self.github_token.strip()

        if self._cached_token is not None:
            return self._cached_token

        if not self.github_token_secret_arn:
            return ""

        try:
            sm = self.get_secrets_client()
            resp = sm.get_secret_value(SecretId=self.github_token_secret_arn)
            raw = resp.get("SecretString", "")
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        self._cached_token = str(
                            parsed.get("token")
                            or parsed.get("github_token")
                            or parsed.get("GITHUB_TOKEN")
                            or raw
                        ).strip()
                        return self._cached_token
                except Exception:
                    pass
                self._cached_token = raw.strip()
                return self._cached_token
        except Exception as exc:
            logger.warning(
                "Could not retrieve GitHub token from Secrets Manager (%s): %s",
                self.github_token_secret_arn,
                exc,
            )

        return ""

    def get_github_headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        """Generate HTTP headers for GitHub REST API calls."""
        headers = {
            "Accept": accept,
            "User-Agent": "InterviewPrep-LeetCodeSyncWorker/1.0",
        }
        token = self.resolve_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def resolve_commit_sha(self, ref_or_branch: str) -> Optional[str]:
        """Resolve a branch name, ref, or short SHA to a concrete 40-character commit SHA via GitHub API."""
        if not ref_or_branch:
            return None

        clean_ref = ref_or_branch.strip()
        # If already a full 40-character hex SHA, return lowercase
        if len(clean_ref) == 40 and all(c in "0123456789abcdefABCDEF" for c in clean_ref):
            return clean_ref.lower()

        query_ref = clean_ref
        if query_ref.startswith("refs/heads/"):
            query_ref = query_ref[len("refs/heads/"):]

        url = f"https://api.github.com/repos/{self.source_repo}/commits/{query_ref}"
        headers = self.get_github_headers()

        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                concrete_sha = data.get("sha")
                if concrete_sha and len(concrete_sha) == 40:
                    logger.info("Resolved ref '%s' to concrete SHA: %s", ref_or_branch, concrete_sha)
                    return str(concrete_sha).lower()
            logger.error(
                "GitHub Commits API returned HTTP %d for ref '%s': %s",
                resp.status_code,
                ref_or_branch,
                resp.text[:200],
            )
        except Exception as exc:
            logger.error("Exception resolving commit SHA for '%s': %s", ref_or_branch, exc)

        return None

    def check_commit_staleness(self, commit_sha: str, last_synced_sha: str) -> str:
        """Check if incoming commit_sha is stale compared to last_synced_sha.

        Returns:
            CommitStaleness.CONFIRMED_STALE: Commit is definitely older than or identical to last_synced_sha.
            CommitStaleness.CONFIRMED_NOT_STALE: Commit is definitely newer than last_synced_sha.
            CommitStaleness.UNDETERMINED: Transient API failure, network timeout, rate limiting, or server error.
        """
        if not commit_sha or not last_synced_sha:
            return CommitStaleness.CONFIRMED_NOT_STALE

        if commit_sha.lower() == last_synced_sha.lower():
            return CommitStaleness.CONFIRMED_STALE

        url = f"https://api.github.com/repos/{self.source_repo}/compare/{commit_sha}...{last_synced_sha}"
        headers = self.get_github_headers()

        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                cmp_status = data.get("status")  # 'ahead', 'behind', 'diverged', 'identical'
                if cmp_status in ("ahead", "identical"):
                    logger.info(
                        "Incoming commit %s is an ancestor of or identical to last synced commit %s (compare status: %s). Mark as stale.",
                        commit_sha,
                        last_synced_sha,
                        cmp_status,
                    )
                    return CommitStaleness.CONFIRMED_STALE
                elif cmp_status == "behind":
                    logger.info(
                        "Incoming commit %s is newer than last synced commit %s (compare status: %s).",
                        commit_sha,
                        last_synced_sha,
                        cmp_status,
                    )
                    return CommitStaleness.CONFIRMED_NOT_STALE
                elif cmp_status == "diverged":
                    logger.warning(
                        "Incoming commit %s and last synced commit %s have diverged. Checking current branch head.",
                        commit_sha,
                        last_synced_sha,
                    )
                    current_head = self.resolve_commit_sha(self.source_branch)
                    if current_head and current_head.lower() == commit_sha.lower():
                        return CommitStaleness.CONFIRMED_NOT_STALE
                    if current_head:
                        head_cmp_url = f"https://api.github.com/repos/{self.source_repo}/compare/{commit_sha}...{current_head}"
                        head_resp = requests.get(head_cmp_url, headers=headers, timeout=20)
                        if head_resp.status_code == 200:
                            head_status = head_resp.json().get("status")
                            if head_status in ("ahead", "identical"):
                                return CommitStaleness.CONFIRMED_STALE
                            elif head_status == "behind":
                                return CommitStaleness.CONFIRMED_NOT_STALE
                    return CommitStaleness.UNDETERMINED

            logger.warning(
                "GitHub compare API returned HTTP %d while checking stale commit: %s",
                resp.status_code,
                resp.text[:200],
            )
            return CommitStaleness.UNDETERMINED
        except Exception as exc:
            logger.warning("Failed to check commit staleness via GitHub compare API: %s", exc)
            return CommitStaleness.UNDETERMINED

    def is_commit_stale(self, commit_sha: str, last_synced_sha: str) -> bool:
        """Backward-compatible helper returning True only if confirmed stale."""
        return self.check_commit_staleness(commit_sha, last_synced_sha) == CommitStaleness.CONFIRMED_STALE

    def compare_commits(self, before_sha: str, after_sha: str) -> tuple[list[str], list[str]]:
        """Compare commits using GitHub REST compare API.

        Returns:
            tuple[list[str], list[str]]: (added_or_modified_files, removed_files)
        """
        url = f"https://api.github.com/repos/{self.source_repo}/compare/{before_sha}...{after_sha}"
        headers = self.get_github_headers()

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                files = data.get("files", [])
                if len(files) >= 300 or data.get("status") == "diverged":
                    logger.warning(
                        "GitHub compare API returned %d files (or status is diverged); falling back to Git Tree API",
                        len(files),
                    )
                    tree_files = self.fetch_tree_files(after_sha)
                    return tree_files, []

                added_or_modified = [
                    f["filename"]
                    for f in files
                    if f.get("status") in ("added", "modified", "renamed", "changed")
                ]
                removed = [f["filename"] for f in files if f.get("status") == "removed"]
                return added_or_modified, removed

            logger.warning(
                "GitHub compare API returned HTTP %d: %s. Falling back to Git Tree API",
                resp.status_code,
                resp.text[:200],
            )
            tree_files = self.fetch_tree_files(after_sha)
            return tree_files, []

        except Exception as exc:
            logger.error("Exception invoking GitHub compare API: %s. Falling back to Git Tree API", exc)
            tree_files = self.fetch_tree_files(after_sha)
            return tree_files, []

    def fetch_tree_files(self, sha_or_ref: str) -> list[str]:
        """Fetch all blob paths from repository git tree matching questions_path."""
        url = f"https://api.github.com/repos/{self.source_repo}/git/trees/{sha_or_ref}?recursive=1"
        headers = self.get_github_headers()

        try:
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 200:
                tree_data = resp.json()
                tree = tree_data.get("tree", [])
                prefix = self.questions_path + "/"
                matched = [
                    item["path"]
                    for item in tree
                    if item.get("type") == "blob"
                    and (
                        item.get("path", "").startswith(prefix)
                        or item.get("path", "") == self.questions_path
                    )
                ]
                return matched

            logger.error(
                "GitHub Git Tree API returned HTTP %d: %s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        except Exception as exc:
            logger.error("Exception invoking GitHub Git Tree API: %s", exc)
            return []

    def fetch_file_content(self, path: str, sha: str) -> Optional[str]:
        """Fetch raw file content from GitHub raw endpoint or Contents API."""
        owner_repo = self.source_repo
        clean_path = path.strip("/")
        raw_url = f"https://raw.githubusercontent.com/{owner_repo}/{sha}/{clean_path}"
        raw_headers = {"User-Agent": "InterviewPrep-LeetCodeSyncWorker/1.0"}
        token = self.resolve_token()
        if token:
            raw_headers["Authorization"] = f"token {token}"

        try:
            resp = requests.get(raw_url, headers=raw_headers, timeout=20)
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("Failed raw endpoint request for %s: %s", clean_path, exc)

        # Fallback to Contents API with raw accept header
        contents_url = f"https://api.github.com/repos/{owner_repo}/contents/{clean_path}"
        api_headers = self.get_github_headers(accept="application/vnd.github.raw+json")

        try:
            resp = requests.get(contents_url, params={"ref": sha}, headers=api_headers, timeout=20)
            if resp.status_code == 200:
                return resp.text
            logger.warning(
                "GitHub Contents API returned HTTP %d for %s", resp.status_code, clean_path
            )
        except Exception as exc:
            logger.error("Exception fetching file via Contents API (%s): %s", clean_path, exc)

        return None

    def process_message_payload(self, payload: dict[str, Any], dry_run: bool = False) -> bool:
        """Process parsed SQS message payload.

        Returns:
            bool: True if message was successfully processed or safely skipped (eligible for SQS ACK).
                  False if any failure occurred, preventing SQS acknowledgment so message can retry.
        """
        delivery_id = str(payload.get("delivery_id") or f"manual-{int(time.time())}")
        repository = payload.get("repository", self.source_repo)
        ref = payload.get("ref", f"refs/heads/{self.source_branch}")
        before_sha = payload.get("before_sha", "")
        after_sha = payload.get("after_sha", "")
        changed_paths = payload.get("changed_paths") or []
        needs_investigation = payload.get("needs_investigation", False)

        # 1. Validate repository
        if repository.lower() != self.source_repo.lower():
            logger.info(
                "Skipping message for repository '%s' (configured: '%s')",
                repository,
                self.source_repo,
            )
            return True

        # 2. Validate branch/ref
        normalized_branch = (
            self.source_branch
            if self.source_branch.startswith("refs/heads/")
            else f"refs/heads/{self.source_branch}"
        )
        if (
            ref != self.source_branch
            and ref != normalized_branch
            and not ref.endswith(f"/{self.source_branch}")
        ):
            logger.info("Skipping message for ref '%s' (configured: '%s')", ref, self.source_branch)
            return True

        # 3. Check for duplicate delivery ID
        if delivery_id:
            prior_status = self.sync_service.get_delivery_status(delivery_id)
            if prior_status == "success":
                logger.info(
                    "Delivery %s has already been processed successfully. Skipping and acknowledging.",
                    delivery_id,
                )
                return True

        # 4. Check for stale commit
        last_synced_sha = self.sync_service.get_last_sync_sha(self.source_repo, self.source_branch)
        if after_sha and last_synced_sha:
            staleness = self.check_commit_staleness(after_sha, last_synced_sha)
            if staleness == CommitStaleness.CONFIRMED_STALE:
                logger.info(
                    "Commit %s is older than or equal to last synced commit %s for %s/%s. Skipping.",
                    after_sha,
                    last_synced_sha,
                    self.source_repo,
                    self.source_branch,
                )
                return True
            elif staleness == CommitStaleness.UNDETERMINED:
                logger.warning(
                    "Unable to determine commit staleness for %s against %s (GitHub Compare API error/timeout). "
                    "Refusing to process message to prevent potential checkpoint regression. "
                    "Leaving in SQS for retry.",
                    after_sha,
                    last_synced_sha,
                )
                return False

        # 5. Resolve changed files
        added_or_modified: list[str] = []
        removed: list[str] = []

        prefix = self.questions_path + "/"
        if changed_paths and not needs_investigation:
            added_or_modified = [
                p for p in changed_paths
                if is_candidate_question_file(p, self.questions_path)
            ]
        else:
            if before_sha and after_sha:
                added_or_modified, removed = self.compare_commits(before_sha, after_sha)
            elif after_sha:
                added_or_modified = self.fetch_tree_files(after_sha)

            added_or_modified = [
                p for p in added_or_modified
                if is_candidate_question_file(p, self.questions_path)
            ]

        # 6. Handle upstream removals (do NOT delete records from database)
        for removed_path in removed:
            if removed_path.startswith(prefix) or removed_path == self.questions_path:
                logger.warning(
                    "Upstream question file removed: %s (preserving database record for safety)",
                    removed_path,
                )

        candidate_files = filter_and_prioritize_markdown_files(
            added_or_modified, questions_path=self.questions_path
        )
        logger.info(
            "Synchronizing %d question file(s) for commit %s (delivery_id: %s, dry_run: %s)",
            len(candidate_files),
            after_sha,
            delivery_id,
            dry_run,
        )

        # 7. Record sync start
        if not dry_run and delivery_id and after_sha:
            try:
                self.sync_service.record_sync_start(
                    delivery_id=delivery_id,
                    commit_sha=after_sha,
                    repo=self.source_repo,
                    branch=self.source_branch,
                )
            except Exception as exc:
                logger.warning("Failed to record sync start in metadata history: %s", exc)

        files_processed = 0
        files_added = 0
        files_updated = 0
        files_ignored = 0
        files_failed = 0
        error_summaries: list[str] = []

        # 8. Fetch, parse, and synchronize each question file
        for file_path in candidate_files:
            content = self.fetch_file_content(file_path, after_sha)
            if not content:
                logger.warning("Could not fetch content for question file: %s", file_path)
                files_failed += 1
                error_summaries.append(f"{file_path}: Failed to fetch file content")
                continue

            parsed = parse_leetcode_markdown(content, filename_or_path=file_path)
            if parsed is None:
                logger.warning("Markdown parser returned None for file: %s", file_path)
                files_failed += 1
                error_summaries.append(f"{file_path}: Failed to parse markdown")
                continue

            is_valid, reason = validate_problem(parsed)
            if not is_valid:
                logger.warning("Problem validation failed for file %s: %s", file_path, reason)
                files_failed += 1
                error_summaries.append(f"{file_path}: {reason}")
                continue

            sync_res = self.sync_service.sync_problem(parsed, dry_run=dry_run)
            st = sync_res.get("status")
            if st == "added":
                files_added += 1
            elif st == "updated":
                files_updated += 1
            elif st == "unchanged":
                files_ignored += 1
            else:
                files_failed += 1
                details = sync_res.get("details", "Unknown sync error")
                error_summaries.append(f"qnum {parsed.qnum}: {details}")

            files_processed += 1

        # 9. Record sync completion and enforce all-or-nothing terminal success
        final_status = "failed" if files_failed > 0 else "success"
        error_str = "; ".join(error_summaries[:10])

        if not dry_run and delivery_id and after_sha:
            try:
                self.sync_service.record_sync_completion(
                    delivery_id=delivery_id,
                    commit_sha=after_sha,
                    status=final_status,
                    files_processed=files_processed,
                    files_added=files_added,
                    files_updated=files_updated,
                    files_ignored=files_ignored,
                    files_failed=files_failed,
                    error_summary=error_str,
                    repo=self.source_repo,
                    branch=self.source_branch,
                )
            except Exception as exc:
                logger.warning("Failed to record sync completion in metadata history: %s", exc)

        logger.info(
            "Sync run finished for %s: status=%s, processed=%d, added=%d, updated=%d, unchanged=%d, failed=%d",
            after_sha,
            final_status,
            files_processed,
            files_added,
            files_updated,
            files_ignored,
            files_failed,
        )

        # Incomplete processing must prevent SQS ACK so message remains available for retry/DLQ
        if files_failed > 0:
            logger.warning(
                "Sync run for delivery %s encountered %d failure(s). Incomplete run; leaving message for retry.",
                delivery_id,
                files_failed,
            )
            return False

        return True

    def process_message(self, message: dict[str, Any], dry_run: bool = False) -> bool:
        """Process an individual SQS message.

        Deletes message upon successful processing or safe skip.
        Does NOT delete message on unexpected exceptions or incomplete processing,
        allowing visibility timeout to expire for DLQ redrive.
        """
        receipt_handle = message.get("ReceiptHandle")
        body = message.get("Body", "")

        try:
            payload = json.loads(body)
        except Exception as exc:
            logger.warning("Encountered unparseable SQS message body (MessageId: %s): %s", message.get("MessageId"), exc)
            if receipt_handle and self.queue_url:
                try:
                    self.get_sqs_client().delete_message(
                        QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                    )
                except Exception as del_exc:
                    logger.warning("Failed to delete unparseable SQS message: %s", del_exc)
            return True

        try:
            should_ack = self.process_message_payload(payload, dry_run=dry_run)
            if should_ack and receipt_handle and self.queue_url:
                self.get_sqs_client().delete_message(
                    QueueUrl=self.queue_url, ReceiptHandle=receipt_handle
                )
                logger.info("Successfully deleted message from SQS (MessageId: %s)", message.get("MessageId"))
                return True
            elif not should_ack:
                logger.warning(
                    "Message processing incomplete or failed (MessageId: %s); leaving in SQS for retry / DLQ redrive",
                    message.get("MessageId"),
                )
                return False
            return True
        except Exception as exc:
            logger.error(
                "Unexpected failure processing SQS message (MessageId: %s): %s",
                message.get("MessageId"),
                exc,
                exc_info=True,
            )
            # Do NOT delete message; allow SQS visibility timeout to expire for automatic redrive to DLQ
            return False

    def run_once(self, dry_run: bool = False) -> bool:
        """Poll SQS once for a single batch of messages.

        Returns:
            bool: True if a message was received and processed; False if queue was empty or timed out.
        """
        if not self.queue_url:
            logger.error("Cannot poll SQS: LEETCODE_SYNC_QUEUE_URL is not configured.")
            return False

        sqs = self.get_sqs_client()
        try:
            response = sqs.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=self.wait_time_seconds,
                VisibilityTimeout=self.visibility_timeout,
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("Boto3 error polling SQS queue (%s): %s", self.queue_url, exc)
            return False
        except Exception as exc:
            logger.error("Unexpected error polling SQS queue: %s", exc)
            return False

        messages = response.get("Messages", [])
        if not messages:
            return False

        for msg in messages:
            self.process_message(msg, dry_run=dry_run)

        return True

    def run_loop(self, dry_run: bool = False, once: bool = False) -> None:
        """Continuous SQS consumer loop with graceful signal handling."""
        logger.info(
            "Starting LeetCode sync worker (queue: %s, repo: %s/%s, once: %s, dry_run: %s)",
            self.queue_url,
            self.source_repo,
            self.source_branch,
            once,
            dry_run,
        )

        while not self.stop_requested:
            received = self.run_once(dry_run=dry_run)
            if once:
                break
            if not received and not self.stop_requested:
                # Brief sleep between empty polls if wait_time_seconds was short
                time.sleep(1)

        logger.info("LeetCode sync worker stopped cleanly.")

    def run_full_sync(self, dry_run: bool = False) -> bool:
        """Bypass SQS and perform full sync from the upstream repository tree."""
        logger.info("Initiating full synchronization of %s branch '%s'", self.source_repo, self.source_branch)
        concrete_sha = self.resolve_commit_sha(self.source_branch)
        if not concrete_sha:
            logger.error("Could not resolve concrete commit SHA for branch '%s'. Aborting full sync.", self.source_branch)
            return False

        tree_files = self.fetch_tree_files(concrete_sha)
        if not tree_files:
            logger.error("No files found in git tree for commit '%s'", concrete_sha)
            return False

        payload = {
            "delivery_id": f"full-sync-{int(time.time())}",
            "event": "full_sync",
            "repository": self.source_repo,
            "ref": f"refs/heads/{self.source_branch}",
            "before_sha": "",
            "after_sha": concrete_sha,
            "changed_paths": tree_files,
            "needs_investigation": False,
        }
        return self.process_message_payload(payload, dry_run=dry_run)

    def run_commit_sync(self, commit_sha: str, dry_run: bool = False) -> bool:
        """Bypass SQS and sync against a specific commit SHA or reference."""
        logger.info("Initiating manual sync for ref/commit %s in %s", commit_sha, self.source_repo)
        concrete_sha = self.resolve_commit_sha(commit_sha) or commit_sha
        payload = {
            "delivery_id": f"manual-commit-{concrete_sha[:8]}-{int(time.time())}",
            "event": "manual_push",
            "repository": self.source_repo,
            "ref": f"refs/heads/{self.source_branch}",
            "before_sha": "",
            "after_sha": concrete_sha,
            "changed_paths": [],
            "needs_investigation": True,
        }
        return self.process_message_payload(payload, dry_run=dry_run)


def main() -> None:
    """CLI entry point for LeetCode synchronization worker."""
    parser = argparse.ArgumentParser(
        description="LeetCode synchronization background worker for RDS PostgreSQL"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate synchronization without executing database mutations",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll SQS once (or process 1 batch) and exit cleanly",
    )
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Bypass SQS and run a full synchronization of all questions from upstream tree",
    )
    parser.add_argument(
        "--commit",
        type=str,
        default=None,
        help="Manually synchronize against a specified commit SHA",
    )
    parser.add_argument(
        "--queue-url",
        type=str,
        default=None,
        help="SQS queue URL override",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Source GitHub repository override (e.g. doocs/leetcode)",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default=None,
        help="Source GitHub branch override (e.g. main)",
    )

    args = parser.parse_args()

    worker = LeetCodeSyncWorker(
        queue_url=args.queue_url,
        source_repo=args.repo,
        source_branch=args.branch,
    )

    def _handle_signal(signum: int, frame: Any) -> None:
        logger.info("Signal %s received; completing current task and shutting down...", signum)
        worker.stop_requested = True

    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception:
        pass

    if args.full_sync:
        worker.run_full_sync(dry_run=args.dry_run)
    elif args.commit:
        worker.run_commit_sync(args.commit, dry_run=args.dry_run)
    else:
        if not worker.queue_url:
            logger.error("LEETCODE_SYNC_QUEUE_URL environment variable is not configured. Exiting.")
            sys.exit(0)
        worker.run_loop(dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
    main()
