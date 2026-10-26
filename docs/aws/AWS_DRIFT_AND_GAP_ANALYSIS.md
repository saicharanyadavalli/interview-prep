# AWS Drift and Gap Analysis

**Repository:** `saicharanyadavalli/interview-prep`  
**Target AWS Account:** `808431466075` | **Region:** `ap-south-2` (Hyderabad)  
**Baseline Branch:** `feature/leetcode-sync-pipeline-and-hardening` (branched from `aws-migration` @ `a61c611`)  
**Audit Date:** 2026-10-25 15:05 UTC+05:30  

---

## 1. CloudFormation Stack Drift Analysis

Drift detection was initiated across all existing deployed stacks via the AWS CloudFormation API:

| Stack Name | Managed Resources | Drift Status | Drifted Resource Count | Evaluation Details |
|---|---|---|---|---|
| `interview-prep-elasticache-personal` | ReplicationGroup, SecurityGroup, SubnetGroup, Secret, IAM Policy | **`IN_SYNC`** | 0 | All ElastiCache, Secrets Manager, and IAM properties match IaC declarations. |
| `interview-prep-cognito-personal` | UserPool, UserPoolClient, UserPoolDomain, IdentityProvider | **`IN_SYNC`** | 0 | Client callbacks, PKCE settings, and Google OAuth federation match declarations. |
| `interview-prep-assets-personal` | S3Bucket, CloudFrontDistribution, OAC, BucketPolicy, IAM Policies | **`IN_SYNC`** | 0 | S3 OAC SigV4 policy, CloudFront cache behavior, and security headers match declarations. |

**Key Finding:** There is **zero configuration drift** across existing stacks. The foundation is stable and cleanly managed by CloudFormation.

---

## 2. Architectural Gap Analysis: Repository Intent vs. Live AWS State

| Subsystem / Pipeline | Repository Specification | Live AWS State | Severity | Architectural Impact |
|---|---|---|---|---|
| **LeetCode Webhook Ingress** | `leetcode-sync-pipeline.yaml` declares API Gateway HTTP API v2 + Lambda proxy route `POST /github/webhook`. | **Missing**. 0 HTTP APIs and 0 Lambda functions exist in `ap-south-2`. | **High** | Upstream GitHub repository push notifications cannot be received. |
| **Lambda Deployment Package** | Template expects `lambda/github-webhook-receiver.zip` in `interview-prep-assets-808431466075-personal-ap-south-2`. | **Missing**. Bucket is empty. Zip package is not uploaded. | **High** | CloudFormation stack creation will fail immediately if attempted without the zip. |
| **Webhook HMAC Shared Secret** | Template expects parameter `WebhookSecretArn` pointing to Secrets Manager. | **Missing**. Secret `interview-prep/github/webhook-secret-personal` does not exist in Secrets Manager. | **High** | Lambda cannot authenticate incoming webhooks without the shared HMAC secret. |
| **Sync Tracking Database Tables** | `migrations/rds/004_leetcode_sync_metadata.sql` defines `leetcode_sync_history` and `leetcode_sync_state`. | **Missing**. Live RDS table query confirmed neither table exists yet (`leetcode_problems` exists with 4,017 rows). | **High** | Sync worker will throw `UndefinedTableError` when attempting to write audit history. |
| **EC2 Sync Worker Container** | `docker-compose.yml` defines `leetcode-sync-worker` service running `workers.leetcode_sync_worker`. | **Disabled**. Worker exits with code 0 because `LEETCODE_SYNC_QUEUE_URL` is empty in `.env`. | **Medium** | No background process is polling the queue for synchronization events. |
| **Alarm Notifications & Incident Response** | CloudWatch alarms exist for CPU, StatusCheckFailed, and DLQ messages. | **Unwired**. `ActionsEnabled: false`. 0 Amazon SNS topics exist in `ap-south-2`. | **Medium** | When alarms transition to `ALARM` state, no notifications or alerts are delivered. |
| **Perimeter Security & Ingress Decoupling** | `alb-staging.yaml` defines Multi-AZ ALB with WAF WebACL association. | **Unprovisioned**. Traffic hits EC2 directly. `interview-prep-waf` WebACL is orphaned. | **Medium** | Direct exposure of EC2 public IP; WAF rules are not filtering web traffic. |

---

## 3. Risk Assessment & Blast Radius Matrix

| Proposed Mutation | Blast Radius | Data Loss Risk | Rollback Mechanism |
|---|---|---|---|
| **1. Create Secrets Manager Secret for Webhook** | Zero (New secret `interview-prep/github/webhook-secret-personal`) | None | `aws secretsmanager delete-secret --force-delete-without-recovery` |
| **2. Upload Lambda Package Zip to S3** | Zero (Additive S3 object `lambda/github-webhook-receiver.zip`) | None | `aws s3 rm s3://.../lambda/github-webhook-receiver.zip` |
| **3. Deploy `leetcode-sync-pipeline.yaml` CloudFormation Stack** | Scoped strictly to new API Gateway, Lambda, and IAM role. | None | `aws cloudformation delete-stack --stack-name interview-prep-leetcode-sync-personal` |
| **4. Apply RDS Migration 004 (`004_leetcode_sync_metadata.sql`)** | Additive DDL (`CREATE TABLE IF NOT EXISTS`). Does not alter existing `leetcode_problems` or user tables. | None (Additive only) | `DROP TABLE IF EXISTS public.leetcode_sync_history, public.leetcode_sync_state;` |
| **5. Configure EC2 `.env` and Start Sync Worker** | Container lifecycle change (`interview-prep-leetcode-sync-worker`). | None | Stop container / clear `LEETCODE_SYNC_QUEUE_URL` |
| **6. Provision Amazon SNS Alerting Topic** | Additive SNS Topic + update alarm actions. | None | Delete SNS topic / disable alarm actions |

---

## 4. Remediation Action Plan

1. **Prerequisite 1: Secrets Management**
   - Generate cryptographically secure 32-byte webhook secret.
   - Create AWS Secrets Manager secret `interview-prep/github/webhook-secret-personal`.
2. **Prerequisite 2: Lambda Packaging & Upload**
   - Package `interview-app/infrastructure/lambda/github_webhook_receiver/handler.py` and `__init__.py` into `github-webhook-receiver.zip`.
   - Upload to `s3://interview-prep-assets-808431466075-personal-ap-south-2/lambda/github-webhook-receiver.zip`.
3. **Infrastructure Deployment: CloudFormation**
   - Reconcile manually created SQS queues with CloudFormation stack (delete manual empty queues so CloudFormation manages them cleanly).
   - Deploy `interview-app/infrastructure/cloudformation/leetcode-sync-pipeline.yaml` with stack name `interview-prep-leetcode-sync-personal`.
   - Capture stack outputs: `ApiEndpoint`, `SqsQueueUrl`, `SqsQueueArn`, `EC2WorkerPolicyArn`.
4. **Database Migration: RDS**
   - Execute `004_leetcode_sync_metadata.sql` against `interview_prep_db` via the backend container connection.
   - Verify creation of `leetcode_sync_state` and `leetcode_sync_history` tables.
5. **Worker Activation: EC2**
   - Inject `LEETCODE_SYNC_QUEUE_URL` into `/home/ubuntu/interview-prep/interview-app/.env`.
   - Fix compose `fail-closed` behavior so worker container does not silently exit in production.
   - Start `interview-prep-leetcode-sync-worker` container and verify logs.
6. **Observability: SNS & Alarms**
   - Provision SNS Topic `interview-prep-alerts-personal`.
   - Update CloudWatch alarms to route notifications to the SNS Topic and set `ActionsEnabled: true`.
7. **End-to-End Testing & Verification**
   - Test invalid signature rejection (HTTP 401).
   - Test valid push payload simulation via API Gateway -> SQS -> Worker -> RDS upsert verification.
