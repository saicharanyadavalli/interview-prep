# LeetCode Synchronization Pipeline Operations Runbook

**System:** LeetCode Webhook-to-RDS Processing Pipeline  
**Target AWS Account:** `808431466075` | **Region:** `ap-south-2` (Hyderabad)  
**IaC Stack:** `interview-prep-leetcode-sync-personal`  
**API Gateway Webhook Endpoint:** `https://xb16m44fm8.execute-api.ap-south-2.amazonaws.com/github/webhook`  
**Primary SQS Queue:** `https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-queue-personal`  
**Dead-Letter Queue (DLQ):** `https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-dlq-personal`  

---

## 1. Pipeline Architecture Summary

```
[ GitHub: doocs/leetcode (push to main) ]
                   │
                   ▼ (HTTPS POST /github/webhook)
       Amazon API Gateway HTTP API v2 (xb16m44fm8)
                   │
                   ▼ (AWS_PROXY Payload v2.0)
     AWS Lambda: interview-prep-leetcode-webhook-personal
     - Reads HMAC secret from AWS Secrets Manager
     - Verifies X-Hub-Signature-256 (constant-time compare)
     - Filters push events touching solution/
                   │
                   ▼ (sqs:SendMessage)
     Amazon SQS: interview-prep-leetcode-sync-queue-personal
                   │
                   ▼ (Long-polling 20s via PrivateLink)
     EC2 Docker Worker: interview-prep-leetcode-sync-worker
     - Parses markdown & solution approaches
     - Transactional upsert into Amazon RDS PostgreSQL
     - Acks & deletes message ONLY upon successful DB commit
     - Automatic DLQ redrive after 5 retries
                   │
                   ▼ (Port 5432 / TLS 1.3)
      Amazon RDS: interview_prep_db (4,017+ problems)
```

---

## 2. GitHub Webhook Registration Guide

To link the upstream repository (`doocs/leetcode` or your fork) to the synchronization pipeline:

1. Navigate to the GitHub repository: **Settings** ➔ **Webhooks** ➔ **Add webhook**.
2. **Payload URL:**
   ```
   https://xb16m44fm8.execute-api.ap-south-2.amazonaws.com/github/webhook
   ```
3. **Content type:** Select `application/json`.
4. **Secret:** Retrieve the shared secret from AWS Secrets Manager using:
   ```bash
   aws secretsmanager get-secret-value \
     --secret-id "interview-prep/github/webhook-secret-personal" \
     --region ap-south-2 \
     --query 'SecretString' \
     --output text
   ```
   *Note: Extract the value of `webhook_secret` and paste it into the GitHub Secret field.*
5. **SSL verification:** Enable SSL verification (`Verify SSL`).
6. **Which events would you like to trigger this webhook?**
   - Select **"Just the push event"**.
7. **Active:** Ensure the checkbox is checked.
8. Click **Add webhook**.
   - GitHub will send an initial `ping` event.
   - The Lambda function will verify the signature, acknowledge the ping with `HTTP 200 {"message": "pong"}`, and log the handshake without enqueueing to SQS.

---

## 3. Routine Operations & Worker Lifecycle

### Checking Worker Status on EC2
Connect via AWS Systems Manager (SSM) or Run Command:
```bash
# Check container status
docker ps --filter "name=interview-prep-leetcode-sync-worker"

# View live worker logs
docker logs -f --tail 100 interview-prep-leetcode-sync-worker

# Inspect resource consumption
docker stats --no-stream interview-prep-leetcode-sync-worker
```

### Restarting or Reloading the Worker
```bash
cd /home/ubuntu/interview-prep/interview-app
docker compose restart leetcode-sync-worker
```

### Manual Trigger / Ad-Hoc Sync
If you need to trigger a manual sync of specific commits without waiting for a webhook:
```bash
docker exec -it interview-prep-leetcode-sync-worker python -m workers.leetcode_sync_worker --commit-sha <COMMIT_SHA>
```

---

## 4. Troubleshooting & Failure Recovery Procedures

### Scenario A: Messages Accumulating in Dead-Letter Queue (DLQ)
When a poison message or persistent database failure causes 5 failed retries, SQS automatically routes the message to `interview-prep-leetcode-sync-dlq-personal`.
The CloudWatch alarm `interview-prep-sqs-dlq-messages-visible` will trigger.

**Diagnostic Steps:**
1. Check DLQ message count:
   ```bash
   aws sqs get-queue-attributes \
     --queue-url "https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-dlq-personal" \
     --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
     --region ap-south-2
   ```
2. Read the failed message without deleting it:
   ```bash
   aws sqs receive-message \
     --queue-url "https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-dlq-personal" \
     --max-number-of-messages 1 \
     --visibility-timeout 30 \
     --region ap-south-2
   ```
3. Check the audit history in RDS:
   ```sql
   SELECT delivery_id, commit_sha, status, error_summary, created_at 
   FROM public.leetcode_sync_history 
   WHERE status = 'failed' 
   ORDER BY created_at DESC 
   LIMIT 5;
   ```
4. **Redrive / Reprocess Messages:**
   Once the underlying issue (e.g. database connectivity, GitHub rate limit) is resolved, start SQS dead-letter queue redrive back to the main queue:
   ```bash
   aws sqs start-message-move-task \
     --source-arn "arn:aws:sqs:ap-south-2:808431466075:interview-prep-leetcode-sync-dlq-personal" \
     --destination-arn "arn:aws:sqs:ap-south-2:808431466075:interview-prep-leetcode-sync-queue-personal" \
     --region ap-south-2
   ```

### Scenario B: Webhook Signature Verification Failures (HTTP 401)
If GitHub webhook deliveries report `HTTP 401 Unauthorized`:
1. Check CloudWatch Lambda logs:
   ```bash
   aws logs filter-log-events \
     --log-group-name "/aws/lambda/interview-prep-leetcode-webhook-personal" \
     --filter-pattern "signature_verification_failed" \
     --region ap-south-2
   ```
2. Ensure the secret string in GitHub Webhook settings exactly matches `interview-prep/github/webhook-secret-personal` in AWS Secrets Manager.

### Scenario C: GitHub API Rate Limiting (HTTP 403 Secondary Limits)
If upstream markdown fetching hits unauthenticated GitHub rate limits (60 req/hr):
1. Store a personal access token (PAT) with `public_repo` read scope in Secrets Manager:
   ```bash
   aws secretsmanager create-secret \
     --name "interview-prep/github/token-personal" \
     --secret-string '{"github_token": "ghp_..."}' \
     --region ap-south-2
   ```
2. Update `/home/ubuntu/interview-prep/interview-app/.env`:
   ```bash
   GITHUB_TOKEN_SECRET_ARN=arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/github/token-personal-...
   ```
3. Restart worker: `docker compose restart leetcode-sync-worker`. Authenticated limits provide 5,000 req/hr.

---

## 5. Rollback Procedures

If the pipeline needs to be completely rolled back or disabled:

1. **Disable Worker Container:**
   ```bash
   # On EC2 instance:
   cd /home/ubuntu/interview-prep/interview-app
   docker compose stop leetcode-sync-worker
   ```
2. **Pause Webhook Ingress (zero incoming traffic):**
   Delete the webhook from GitHub repository settings.
3. **De-provision CloudFormation Stack:**
   ```bash
   aws cloudformation delete-stack \
     --stack-name interview-prep-leetcode-sync-personal \
     --region ap-south-2
   ```
   *Note: This removes API Gateway, Lambda, SQS queues, and the IAM worker policy cleanly without touching existing RDS data, S3 assets, or the EC2 instance.*
