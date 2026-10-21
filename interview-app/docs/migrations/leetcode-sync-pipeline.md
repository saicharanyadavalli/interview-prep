# LeetCode Synchronization Pipeline: Architecture, Operations & Deployment Runbook

## 1. Executive Summary & Architecture Overview

The LeetCode Synchronization Pipeline provides automated, resilient, and idempotent synchronization of programming problems, solution approaches, and multi-language code snippets from the upstream [doocs/leetcode](https://github.com/doocs/leetcode) repository into the platform's authoritative Amazon RDS PostgreSQL database (`interview_prep_db`).

The pipeline uses an asynchronous, decoupled event-driven architecture designed to ensure zero downtime, strict rate limit protection, resilient dead-letter redrive, and complete isolation between the public webhook endpoint and the internal database workers.

```mermaid
flowchart TD
    subgraph GitHub["GitHub Upstream (doocs/leetcode)"]
        RepoPush["Repository Push Event\n(refs/heads/main)"]
        Webhook["GitHub Webhook Delivery\nHMAC-SHA256 Signed"]
    end

    subgraph AWS_Serverless["AWS Ingestion & Queueing Tier"]
        ApiGw["Amazon API Gateway HTTP API (v2)\nPOST /github/webhook"]

        subgraph LambdaReceiver["AWS Lambda Webhook Receiver (Python 3.12)"]
            SigCheck["Verify X-Hub-Signature-256\n(Constant-Time Comparison)"]
            EventFilter["Filter Event (push only)\nValidate Repo & Branch\nFilter Changed Paths (solution/)"]
        end

        SecretsManager["AWS Secrets Manager\n(Webhook Secret & GitHub Token)"]

        subgraph SQS_Tier["Amazon SQS Messaging"]
            SqsQueue["Primary SQS Queue\n(interview-prep-leetcode-sync-queue)\nRetention: 14 Days, Visibility: 300s"]
            SqsDlq["Dead-Letter Queue (DLQ)\n(interview-prep-leetcode-sync-dlq)\nMaxReceives: 5, Retention: 14 Days"]
        end
    end

    subgraph EC2_Host["AWS EC2 Host (ap-south-2 Hyderabad)"]
        subgraph DockerCompose["Docker Compose (interview-prep-network)"]
            Worker["LeetCode Sync Worker Container\n(workers.leetcode_sync_worker)\nLong-Polling SQS Consumer"]
            Backend["FastAPI Backend Container"]
        end

        EC2Role["EC2 IAM Role: InterviewPrepEC2Role\nScoped SQS Worker Policy Attached"]
    end

    subgraph DatabaseTier["Amazon RDS PostgreSQL 17.11"]
        SyncState["public.leetcode_sync_state\n(Last Synced Commit SHA)"]
        SyncHistory["public.leetcode_sync_history\n(Delivery Audit Trail)"]
        ProblemsTable["public.leetcode_problems\n(Master Problem Metadata)"]
        ApproachesTable["public.leetcode_approaches\n(Intuition, Time/Space Complexity)"]
        SolutionsTable["public.leetcode_code_solutions\n(Multi-Language Implementations)"]
    end

    %% Event Ingestion
    RepoPush --> Webhook
    Webhook -->|HTTPS POST| ApiGw
    ApiGw --> LambdaReceiver
    LambdaReceiver -->|1. Resolve Secret| SecretsManager
    LambdaReceiver -->|2. Verify Signature| SigCheck
    SigCheck -->|3. Validate & Inspect| EventFilter
    EventFilter -->|4. Enqueue Push Notification| SqsQueue
    SqsQueue -.->|Failed 5 Times| SqsDlq

    %% EC2 Worker Consumption
    Worker -->|5. Long-Poll ReceiveMessage| SqsQueue
    EC2Role -.->|Authorizes SQS Actions| Worker
    Worker -->|6. Stale Commit & State Check| SyncState
    Worker -->|7. Fetch Content & Fallback Trees| GitHub
    Worker -->|8. Record Start & Completion| SyncHistory
    Worker -->|9. Idempotent Upsert| ProblemsTable
    Worker -->|10. Upsert Approaches & Solutions| ApproachesTable
    Worker -->|10. Upsert Approaches & Solutions| SolutionsTable
    Worker -->|11. DeleteMessage (ACK)| SqsQueue
```

---

## 2. Configuration Parameters & Environment Variables

### Core Configuration Matrix

| Variable Name | Required | Default Value | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | `ap-south-2` | Target AWS region (Hyderabad). |
| `ENVIRONMENT` | Yes | `personal` | Deployment stage (`personal`, `production`). Defaults to `personal`. |
| `LEETCODE_SYNC_QUEUE_URL` | Yes (Worker) | *None* | SQS Queue URL provisioned by CloudFormation. |
| `LEETCODE_SOURCE_REPO` | Yes | `doocs/leetcode` | Upstream GitHub repository identifier (`owner/repo`). |
| `LEETCODE_SOURCE_BRANCH` | Yes | `main` | Upstream branch tracked for changes. |
| `LEETCODE_QUESTIONS_PATH` | Yes | `solution` | Relative directory path in repository containing solutions. |
| `GITHUB_TOKEN` | Optional | *None* | Personal access token for GitHub REST API (overcomes rate limits). |
| `GITHUB_TOKEN_SECRET_ARN` | Optional | *None* | Secrets Manager ARN holding the GitHub token. |
| `WEBHOOK_SECRET_ARN` | Yes (Lambda) | *None* | Secrets Manager ARN holding the GitHub webhook secret string. |
| `RDS_SECRET_NAME` | Yes | `interview-prep/rds/app` | Secrets Manager secret containing RDS PostgreSQL credentials. |

---

## 3. Additive Database Migration (`004_leetcode_sync_metadata.sql`)

> [!IMPORTANT]
> This migration is **purely additive** and non-destructive. It does not alter existing problem tables or user data (`user_progress`, `user_comments`, `custom_folders`).
>
> **Do NOT run this migration automatically in CI/CD without an authorized maintenance window.**

### Migration Schema Definition

File: `interview-app/migrations/rds/004_leetcode_sync_metadata.sql`

```sql
BEGIN;

-- 1. leetcode_sync_state: Stores checkpoint of last synced commit
CREATE TABLE IF NOT EXISTS public.leetcode_sync_state (
  source_repo TEXT NOT NULL,
  source_branch TEXT NOT NULL,
  last_sync_commit_sha TEXT NOT NULL,
  last_sync_timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (source_repo, source_branch)
);

-- 2. leetcode_sync_history: Audit log for all sync operations
CREATE TABLE IF NOT EXISTS public.leetcode_sync_history (
  delivery_id TEXT PRIMARY KEY,
  source_repo TEXT NOT NULL,
  source_branch TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('in_progress', 'success', 'failed', 'ignored')),
  files_processed INTEGER NOT NULL DEFAULT 0,
  files_added INTEGER NOT NULL DEFAULT 0,
  files_updated INTEGER NOT NULL DEFAULT 0,
  files_ignored INTEGER NOT NULL DEFAULT 0,
  files_failed INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

-- 3. Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_commit ON public.leetcode_sync_history(commit_sha);
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_created_at ON public.leetcode_sync_history(created_at);
CREATE INDEX IF NOT EXISTS idx_leetcode_sync_history_repo_branch ON public.leetcode_sync_history(source_repo, source_branch);

-- 4. UTILITY FUNCTIONS & TRIGGERS
-- Conditional definition: leaves existing function definition and ownership untouched.
-- Only creates the shared function if it does not already exist in the public schema.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public' AND p.proname = 'set_current_timestamp_updated_at'
  ) THEN
    CREATE FUNCTION public.set_current_timestamp_updated_at()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $fn$
    BEGIN
      NEW.updated_at = now();
      RETURN NEW;
    END;
    $fn$;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_leetcode_sync_state_updated_at ON public.leetcode_sync_state;
CREATE TRIGGER trg_leetcode_sync_state_updated_at
  BEFORE UPDATE ON public.leetcode_sync_state
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();

COMMIT;
```

### Manual Execution Runbook

To apply the migration against RDS PostgreSQL from the EC2 host:

```bash
# SSH into EC2 instance
ssh -i ~/.ssh/interview-prep-key.pem ubuntu@<EC2_PUBLIC_IP>

# Execute migration via psql using local Docker container or psql client
docker run --rm -i \
  --network host \
  postgres:17-alpine \
  psql "postgresql://$RDS_USER:$RDS_PASSWORD@$RDS_HOST:5432/interview_prep_db" \
  < interview-app/migrations/rds/004_leetcode_sync_metadata.sql
```

---

## 4. Storing GitHub Webhook Secret in AWS Secrets Manager

Before deploying the CloudFormation stack, store the secret in Secrets Manager:

```bash
# 1. Generate a strong random 32-byte secret
WEBHOOK_SECRET=$(openssl rand -hex 32)
echo "Generated Secret: $WEBHOOK_SECRET"

# 2. Store in AWS Secrets Manager in ap-south-2 (personal stage)
aws secretsmanager create-secret \
  --name "interview-prep/github/webhook-secret-personal" \
  --description "GitHub Webhook HMAC Secret for LeetCode Synchronization Pipeline (Personal)" \
  --secret-string "$WEBHOOK_SECRET" \
  --region ap-south-2

# 3. Retrieve Secret ARN for CloudFormation deployment
WEBHOOK_SECRET_ARN=$(aws secretsmanager describe-secret \
  --secret-id "interview-prep/github/webhook-secret-personal" \
  --region ap-south-2 \
  --query 'ARN' \
  --output text)

echo "Secret ARN: $WEBHOOK_SECRET_ARN"
```

---

## 5. Deploying CloudFormation Infrastructure

The CloudFormation template provisions:
1. SQS Dead-Letter Queue (DLQ) with 14-day retention.
2. SQS Primary Queue with RedrivePolicy (`maxReceiveCount: 5`).
3. Dedicated CloudWatch Log Group (`/aws/lambda/interview-prep-leetcode-webhook-<env>`).
4. Scoped IAM Role for Lambda Webhook Receiver.
5. AWS Lambda Webhook Receiver Function (`python3.12`).
6. Amazon API Gateway HTTP API (v2) with route `POST /github/webhook`.
7. Scoped IAM Managed Policy for EC2 Worker SQS access.

### Step 1: Package Lambda Webhook Receiver

```bash
cd interview-app/infrastructure/lambda/github_webhook_receiver

# Package handler into deployment zip
zip -r ../../../../lambda-webhook-receiver.zip handler.py __init__.py

# Upload zip to assets S3 bucket (ap-south-2 Hyderabad)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# E.g., interview-prep-assets-808431466075-personal-ap-south-2
BUCKET="interview-prep-assets-${ACCOUNT_ID}-personal-ap-south-2"

aws s3 cp ../../../../lambda-webhook-receiver.zip "s3://${BUCKET}/lambda/github-webhook-receiver.zip" \
  --region ap-south-2
```

### Step 2: Deploy CloudFormation Stack

```bash
cd interview-app/infrastructure/cloudformation

# Note: AttachPolicyToRole defaults to 'false' to prevent unreviewed modifications to existing IAM roles.
# Set AttachPolicyToRole=true only when authorized to attach the managed policy directly to EC2RoleName.
aws cloudformation deploy \
  --template-file leetcode-sync-pipeline.yaml \
  --stack-name interview-prep-leetcode-sync-personal \
  --parameter-overrides \
      Environment=personal \
      EC2RoleName=InterviewPrepEC2Role \
      AttachPolicyToRole=false \
      SourceRepo=doocs/leetcode \
      SourceBranch=main \
      QuestionsPath=solution \
      WebhookSecretArn="$WEBHOOK_SECRET_ARN" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-south-2
```

### Step 3: Capture Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name interview-prep-leetcode-sync-personal \
  --region ap-south-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

Key outputs:
- `ApiEndpoint`: `https://<api-id>.execute-api.ap-south-2.amazonaws.com/github/webhook`
- `SqsQueueUrl`: `https://sqs.ap-south-2.amazonaws.com/<account-id>/interview-prep-leetcode-sync-queue-personal`
- `SqsDlqArn`: `arn:aws:sqs:ap-south-2:<account-id>:interview-prep-leetcode-sync-dlq-personal`
- `EC2WorkerPolicyArn`: `arn:aws:iam::<account-id>:policy/interview-prep-leetcode-sync-personal-EC2LeetCodeSyncWorkerPolicy`

---

## 6. Configuring GitHub Webhook & Operational Alternatives

> [!IMPORTANT]
> **Repository Permissions Notice:**
> Configuring a repository webhook requires repository **Administrator** or **Owner** rights.
> Public upstream repositories such as `doocs/leetcode` do not allow external consumers to add webhooks to their repository settings.
>
> If you do not have administrative access to the upstream repository, choose one of the two authorized production alternatives below.

### Option A: Fork Upstream with Automated Fork Sync (Webhook-Driven)
1. Fork `https://github.com/doocs/leetcode` into your personal GitHub organization or account (e.g., `https://github.com/<your-account>/leetcode`).
2. Enable GitHub's automated fork synchronization (or GitHub Actions scheduled fork sync).
3. Navigate to your fork repository settings: `https://github.com/<your-account>/leetcode/settings/hooks`.
4. Click **Add webhook**.
5. Configure:
   - **Payload URL**: Paste `ApiEndpoint` output (e.g. `https://<api-id>.execute-api.ap-south-2.amazonaws.com/github/webhook`).
   - **Content type**: `application/json`.
   - **Secret**: The secret stored in Secrets Manager.
   - **Events**: Select **Just the push event**.
   - **Active**: Checked.
6. When your fork receives synced commits from upstream, GitHub triggers your webhook pipeline automatically.

### Option B: Scheduled EventBridge / Cron Polling (Zero Webhook Permissions Needed)
If you prefer not to maintain a fork, execute the worker periodically against the upstream repository without webhooks:
- Configure an EC2 cron job or AWS EventBridge Rule that invokes the sync worker:
  ```bash
  docker compose exec leetcode-sync-worker python -m workers.leetcode_sync_worker --once --full-sync
  ```
- The worker uses the GitHub Git Tree API to discover new or modified files under `solution/` and atomically updates `leetcode_sync_state` to the newly resolved immutable commit SHA.

---

## 7. EC2 Worker IAM Policy & Attachment

The EC2 worker requires scoped permissions to interact with the SQS queue:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ScopedSqsWorkerAccess",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:ap-south-2:*:interview-prep-leetcode-sync-queue-*"
    }
  ]
}
```

If `AttachPolicyToRole=true` was specified during CloudFormation deploy, this policy is automatically attached to `InterviewPrepEC2Role`.

To attach manually when ready:

```bash
aws iam attach-role-policy \
  --role-name InterviewPrepEC2Role \
  --policy-arn "$EC2_WORKER_POLICY_ARN"
```

---

## 8. Docker Compose Worker Service & Operational Commands

### Docker Compose Service Definition

In `interview-app/docker-compose.yml`:

```yaml
  leetcode-sync-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: runtime
    container_name: interview-prep-leetcode-sync-worker
    restart: on-failure:5
    command: >
      sh -c '
        if [ -z "$$LEETCODE_SYNC_QUEUE_URL" ]; then
          echo "LEETCODE_SYNC_QUEUE_URL is not configured. Sync worker is disabled.";
          exit 0;
        fi;
        exec python -m workers.leetcode_sync_worker
      '
    environment:
      - PYTHONUNBUFFERED=1
      - AWS_REGION=${AWS_REGION:-ap-south-2}
      - RDS_SECRET_NAME=${RDS_SECRET_NAME:-interview-prep/rds/app}
      - RDS_SECRET_ARN=${RDS_SECRET_ARN:-}
      - LEETCODE_SYNC_QUEUE_URL=${LEETCODE_SYNC_QUEUE_URL:-}
      - LEETCODE_SOURCE_REPO=${LEETCODE_SOURCE_REPO:-doocs/leetcode}
      - LEETCODE_SOURCE_BRANCH=${LEETCODE_SOURCE_BRANCH:-main}
      - LEETCODE_QUESTIONS_PATH=${LEETCODE_QUESTIONS_PATH:-solution}
      - GITHUB_TOKEN_SECRET_ARN=${GITHUB_TOKEN_SECRET_ARN:-}
      - ENVIRONMENT=${ENVIRONMENT:-personal}
    networks:
      - app-network
```

### Operational Commands on EC2

#### 1. Start Worker in Background

```bash
cd interview-app
docker compose up -d leetcode-sync-worker
```

#### 2. View Real-Time Structured Logs

```bash
docker compose logs -f leetcode-sync-worker
```

#### 3. Run Dry-Run Simulation (No DB Mutation)

```bash
docker compose run --rm leetcode-sync-worker \
  python -m workers.leetcode_sync_worker --once --dry-run
```

#### 4. Run Full Initial Sync / Backfill from Upstream Repository Tree

```bash
# Dry run first to inspect counts:
docker compose run --rm leetcode-sync-worker \
  python -m workers.leetcode_sync_worker --full-sync --dry-run

# Execute real synchronization:
docker compose run --rm leetcode-sync-worker \
  python -m workers.leetcode_sync_worker --full-sync
```

#### 5. Manually Sync a Specific Commit SHA

```bash
docker compose run --rm leetcode-sync-worker \
  python -m workers.leetcode_sync_worker --commit 7e2d9b1a45f8
```

---

## 9. Monitoring, Metrics & Alerting

### CloudWatch Log Groups

1. **Lambda Webhook Receiver Logs**:
   - Log Group: `/aws/lambda/interview-prep-leetcode-webhook-production`
   - Filter for errors: `{ $.status = "failed" || $.level = "ERROR" }`
2. **EC2 Worker Logs**:
   - Ingested via CloudWatch Agent or viewed directly via Docker:
     `docker logs --tail 200 -f interview-prep-leetcode-sync-worker`

### CloudWatch Alarms for SQS

Create CloudWatch alarms for monitoring pipeline health:

```bash
# Alarm when messages accumulate in DLQ
aws cloudwatch put-metric-alarm \
  --alarm-name "interview-prep-leetcode-sync-dlq-alarm-production" \
  --metric-name ApproximateNumberOfMessagesVisible \
  --namespace AWS/SQS \
  --statistic Maximum \
  --period 300 \
  --evaluation-periods 1 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=QueueName,Value=interview-prep-leetcode-sync-dlq-production \
  --alarm-description "Triggers if any message reaches the LeetCode Sync Dead Letter Queue" \
  --region ap-south-2
```

### Checking Synchronization Status via SQL

```sql
-- Check current synced commit
SELECT * FROM public.leetcode_sync_state;

-- Inspect last 10 webhook sync runs
SELECT delivery_id, commit_sha, status, files_processed, files_added, files_updated, files_failed, error_summary, created_at, completed_at
FROM public.leetcode_sync_history
ORDER BY created_at DESC
LIMIT 10;
```

---

## 10. Safe Disable & Rollback Instructions

### Emergency Kill Switch (Disable Sync Immediately)

If an upstream issue or bad push triggers unexpected behavior:

1. **Pause Webhook in GitHub**:
   Navigate to repo settings > Webhooks > Edit > Uncheck **Active** > Save.
2. **Stop the Worker Container on EC2**:
   ```bash
   docker compose stop leetcode-sync-worker
   ```
3. **Purge SQS Queue if Necessary**:
   ```bash
   aws sqs purge-queue \
     --queue-url "$LEETCODE_SYNC_QUEUE_URL" \
     --region ap-south-2
   ```

### Safe Rollback Procedure

Because all database upserts are additive and idempotent, and because upstream file removals **never delete records from RDS PostgreSQL**, the database remains consistent even if individual synchronization runs fail.

To roll back sync state to a previous commit:
```sql
UPDATE public.leetcode_sync_state
SET last_sync_commit_sha = '<PREVIOUS_GOOD_COMMIT_SHA>',
    updated_at = now()
WHERE source_repo = 'doocs/leetcode' AND source_branch = 'main';
```
Then rerun `python -m workers.leetcode_sync_worker --commit <PREVIOUS_GOOD_COMMIT_SHA>`.
