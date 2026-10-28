# GitHub-Triggered LeetCode Synchronization — AWS Lambda + SQS + RDS PostgreSQL

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:dispatching-parallel-agents and superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an automated, secure GitHub webhook-driven pipeline that synchronizes LeetCode problem Markdown files from upstream (`doocs/leetcode`) into Amazon RDS PostgreSQL via AWS Lambda, SQS (with DLQ), and a dedicated EC2 Docker Compose worker.

**Architecture:**
`GitHub Webhook (push)` &rarr; `Amazon API Gateway HTTP API (POST /github/webhook)` &rarr; `AWS Lambda Receiver (HMAC-SHA256, event filtering)` &rarr; `Amazon SQS (Standard + DLQ)` &rarr; `Python SQS Worker (EC2 Docker container)` &rarr; `Amazon RDS PostgreSQL (Transactional idempotent upserts)`.

**Tech Stack:** Python 3.12, AWS Lambda, Amazon API Gateway HTTP API, Amazon SQS, Amazon RDS PostgreSQL 17, AWS Secrets Manager, Docker Compose, boto3, psycopg2.

## Global Constraints
- Target Branch: `aws-migration` exclusively.
- Target Region: `ap-south-2` (Hyderabad).
- Do not commit, push, merge, deploy, provision AWS resources, modify live AWS configuration, or execute migrations against live RDS.
- Preserve all existing uncommitted changes in the repository.
- Parameterized SQL only; never log secrets, tokens, or raw webhook bodies.
- Idempotent upserts identifying problems by `qnum` and unique constraint `slug`. Never delete questions or affect user progress.

---

### Task 1: Parser, RDS Ingestion Service & Additive Migration (Agent A)
**Files:**
- Create: `interview-app/backend/services/leetcode_parser.py`
- Create: `interview-app/backend/services/leetcode_sync_service.py`
- Create: `interview-app/migrations/rds/004_leetcode_sync_metadata.sql`
- Test: `interview-app/backend/tests/unit/test_leetcode_parser.py`
- Test: `interview-app/backend/tests/unit/test_leetcode_sync_service.py`

**Interfaces:**
- Consumes: `services.rds_client` (`execute_query`, `execute_transaction`, `get_connection`).
- Produces: `parse_leetcode_markdown(content: str, filename: str) -> ParsedProblem`, `LeetCodeSyncService(rds_client=...).sync_problem(parsed, dry_run=False) -> SyncResult`.

---

### Task 2: AWS Lambda Webhook Receiver & Infrastructure Template (Agent B)
**Files:**
- Create: `interview-app/infrastructure/lambda/github_webhook_receiver/handler.py`
- Create: `interview-app/infrastructure/cloudformation/leetcode-sync-pipeline.yaml`
- Test: `interview-app/backend/tests/unit/test_github_webhook_lambda.py`

**Interfaces:**
- Consumes: AWS Secrets Manager for webhook secret, API Gateway HTTP API event format payload.
- Produces: SQS message payload `{ "delivery_id": ..., "repository": ..., "ref": ..., "before_sha": ..., "after_sha": ..., "changed_paths": [...], "timestamp": ... }`.
- CloudFormation Template: defines API Gateway, Lambda, SQS queue, SQS DLQ, IAM execution roles, and scoped EC2 worker policy.

---

### Task 3: Python SQS Worker, Docker Compose, Env Config & Ops Runbook (Agent C)
**Files:**
- Create: `interview-app/backend/workers/__init__.py`
- Create: `interview-app/backend/workers/leetcode_sync_worker.py`
- Modify: `interview-app/docker-compose.yml`
- Modify: `interview-app/.env.example`
- Modify: `interview-app/backend/.env.example`
- Create: `interview-app/docs/migrations/leetcode-sync-pipeline.md`
- Test: `interview-app/backend/tests/unit/test_leetcode_sync_worker.py`

**Interfaces:**
- Consumes: SQS messages, GitHub REST API (compare commits / recursive git trees / raw content), `LeetCodeParser`, `LeetCodeSyncService`.
- Produces: Long-polling worker service container in Docker Compose, safe retry/DLQ handling, and CLI manual sync support (`--dry-run`, `--full-sync`).

---

### Task 4: Integration, Test Execution, Diff Audit & Deliverables (Lead Agent)
- Run unit tests for parser, sync service, Lambda webhook, and worker.
- Validate CloudFormation template YAML syntax.
- Validate Docker Compose configuration.
- Perform security diff audit (no leaked secrets, no destructive queries).
- Generate comprehensive final report answering all prompt requirements.
