# AWS Baseline Resource Inventory

**Target Account:** `808431466075`  
**Active Region:** `ap-south-2` (Hyderabad, India)  
**Caller Identity Principal:** `arn:aws:iam::808431466075:user/charan-admin`  
**Audit Timestamp:** 2026-10-25 15:00 UTC+05:30  
**Verification Method:** AWS CLI / Boto3 / Systems Manager (SSM) Live Introspection  

---

## 1. AWS Identity and Environment Reconciliation

| Attribute | Verified Value | Policy / Requirement Check | Status |
|---|---|---|---|
| **AWS Account ID** | `808431466075` | Mandatory check against prompt specification | **MATCH** |
| **Active Region** | `ap-south-2` | Strict adherence to Hyderabad region | **MATCH** |
| **IAM Principal** | `arn:aws:iam::808431466075:user/charan-admin` | Authenticated IAM User with admin delegation | **AUTHENTICATED** |
| **STS Session State** | Valid / Active | Direct API calls verified via AWS CLI and Boto3 | **OPERATIONAL** |

---

## 2. CloudFormation Stacks & Drift Inventory

| Stack Name | Status | Drift Status | Created / Updated | Primary Outputs & Managed Resources |
|---|---|---|---|---|
| `interview-prep-elasticache-personal` | `CREATE_COMPLETE` | `IN_SYNC` (0 drift) | 2026-10-21 | - Replication Group: `interview-prep-node-personal`<br>- Endpoint: `master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379`<br>- Secret: `arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/elasticache/auth-personal-6Ngn5U` |
| `interview-prep-cognito-personal` | `CREATE_COMPLETE` | `IN_SYNC` (0 drift) | 2026-10-18 | - User Pool ID: `ap-south-2_KDxlkNkkX`<br>- App Client ID: `6jju9cj777s60f9uhb3ha46g6o`<br>- Hosted UI: `interview-prep-auth-808431466075-personal` |
| `interview-prep-assets-personal` | `CREATE_COMPLETE` | `IN_SYNC` (0 drift) | 2026-10-18 | - S3 Bucket: `interview-prep-assets-808431466075-20261018-k8m4q2z7`<br>- CloudFront Distribution: `E290EV66LAZPM3`<br>- Domain: `d1uj3o882835l0.cloudfront.net`<br>- OAC ID: `EUIJVUMXS4U2B` |

---

## 3. VPC and Networking Topology

### Virtual Private Cloud (VPC)
- **VPC ID:** `vpc-07be8b7ccec39f3af` (`interview-prep-vpc`)
- **CIDR Block:** `10.0.0.0/16`
- **Internet Gateway:** `igw-0a2f0fd37c86b62ad` (`interview-prep-igw`) attached and active

### Subnet Layout (6 Subnets across 3 Availability Zones)
1. **Public Subnet:**
   - `subnet-0939a69b5ce10001b` (`interview-prep-public-a`, `10.0.1.0/24`, `ap-south-2a`, Public IP auto-assign: `true`)
2. **Private Data Subnets (Interview Prep Application):**
   - `subnet-03c170e1cab511f1a` (`interview-prep-db-a`, `10.0.11.0/24`, `ap-south-2a`, Public IP auto-assign: `false`)
   - `subnet-0b6105cce27e59d79` (`interview-prep-db-b`, `10.0.12.0/24`, `ap-south-2b`, Public IP auto-assign: `false`)
3. **Private Subnets (RDS Dedicated Subnet Group):**
   - `subnet-07ae7c079c0147d5f` (`RDS-Pvt-subnet-1`, `10.0.0.128/25`, `ap-south-2a`)
   - `subnet-08f5e1b09e93106a8` (`RDS-Pvt-subnet-2`, `10.0.2.0/25`, `ap-south-2b`)
   - `subnet-051654326d1ffa13e` (`RDS-Pvt-subnet-3`, `10.0.2.128/25`, `ap-south-2c`)

### AWS PrivateLink VPC Endpoints
1. **S3 Gateway Endpoint:** `vpce-0532b989ed78cef00`
   - Associated Route Tables: `rtb-09e37b81b070b81e7` (Public RT), `rtb-02fb79702c9da09a0` (Private RT)
   - Status: `available`
2. **Secrets Manager Interface Endpoint:** `vpce-0e1c0943e7320cda1`
   - Subnets: `subnet-03c170e1cab511f1a` (ap-south-2a), `subnet-0b6105cce27e59d79` (ap-south-2b)
   - Security Group: `sg-030dbf65a5cc16140` (Port 443 inbound)
   - Private DNS: `Enabled` (`secretsmanager.ap-south-2.amazonaws.com`)
   - Status: `available`
3. **SQS Interface Endpoint:** `vpce-06314ff7fb69e1f66`
   - Subnets: `subnet-03c170e1cab511f1a` (ap-south-2a), `subnet-0b6105cce27e59d79` (ap-south-2b)
   - Security Group: `sg-030dbf65a5cc16140` (Port 443 inbound)
   - Private DNS: `Enabled` (`sqs.ap-south-2.amazonaws.com`)
   - Status: `available`

---

## 4. Compute, Container Runtime & Host Security

### EC2 Host
- **Instance ID:** `i-05a744fb11e56780b` (`interview-prep-ec2`)
- **Instance Type:** `t8i.small` (1 core / 2 vCPUs)
- **Private IP:** `10.0.1.149` | **Public IP:** `16.113.92.222`
- **OS:** Ubuntu 24.04 LTS (`ami-03f1d2b3639314198`)
- **SSM Agent:** Active / Online (`v3.3.4793.0`)
- **IMDSv2:** Strictly Enforced (`HttpTokens: required`, `HttpPutResponseHopLimit: 2`)
- **Inbound Host Ports:** Port 22 SSH is **closed**. Ingress strictly restricted to ports 80 (HTTP) and 443 (HTTPS) on `sg-030dbf65a5cc16140`.

### IAM Instance Role: `InterviewPrepEC2Role`
- **Instance Profile ARN:** `arn:aws:iam::808431466075:instance-profile/InterviewPrepEC2Role`
- **Attached AWS Managed Policies:**
  - `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore`
  - `arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy`
  - `arn:aws:iam::808431466075:policy/interview-prep-assets-personal-BackendEC2S3Policy`
  - `arn:aws:iam::808431466075:policy/interview-prep-assets-personal-AssetMigrationS3Policy`
- **Inline Policies:**
  - `interview-prep-elasticache-personal-EC2ElastiCacheInlinePolicy`
  - `InterviewPrepAvatarS3Access`
  - `InterviewPrepRdsBackupRead_fromS3`
  - `InterviewPrepRdsSecretAccess`
  - `InterviewPrepSqsWorkerAccess`
  - `ReadInterviewPrepCognitoStackOutputs`

---

## 5. Database & In-Memory Caching

### Amazon RDS PostgreSQL 17 (`interview-prep-db`)
- **Engine / Version:** PostgreSQL `17.11`
- **Instance Identifier:** `interview-prep-db`
- **Instance Class:** `db.t4g.micro` (Single-AZ in `ap-south-2a`)
- **Endpoint:** `interview-prep-db.clia2o8uuwlb.ap-south-2.rds.amazonaws.com:5432`
- **Public Access:** `false` (Strictly internal to VPC)
- **Encryption:** Storage encrypted with AWS KMS (`arn:aws:kms:ap-south-2:808431466075:key/de76ef40-6608-4036-97c2-f54cb1278da1`)
- **Deletion Protection:** `true`
- **Performance Insights:** Enabled (7-day retention)
- **Live Database Inspection Findings:**
  - Database Name: `interview_prep_db`
  - Master User Secret: `arn:aws:secretsmanager:ap-south-2:808431466075:secret:rds!db-bb979d68-473f-4289-ac52-bd3f9dab5c4a-HT910y` (7-day auto-rotation)
  - Application User Secret: `arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/rds/app-TVJeDz`
  - Verified Live Tables:
    * `public.leetcode_problems`: **4,017** rows
    * `public.leetcode_approaches`: Active
    * `public.leetcode_code_solutions`: Active
    * `public.user_profiles`: **17** rows
    * `public.user_identities`: Active
    * `public.user_progress`: Active
    * `public.practice_history`: Active
    * `public.course_lessons`: Active

### Amazon ElastiCache Valkey (`interview-prep-node-personal`)
- **Engine / Version:** `valkey` `7.2.6`
- **Replication Group:** `interview-prep-node-personal` (1 node: `0001` in `ap-south-2b`)
- **Node Type:** `cache.t4g.micro`
- **Primary Endpoint:** `master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com:6379`
- **Security:**
  - In-Transit Encryption (TLS 1.3): Required
  - At-Rest Encryption: Enabled (`sse-elasticache`)
  - Redis AUTH Token: Enforced, secret stored in `interview-prep/elasticache/auth-personal`

---

## 6. Asynchronous Queues & Observability

### Amazon SQS Queues
1. **Primary Queue:** `interview-prep-leetcode-sync-queue-personal`
   - URL: `https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-queue-personal`
   - Visibility Timeout: `300s` (5 minutes)
   - Retention Period: `14 days`
   - Encryption: SQS-managed (`SSE-SQS`)
   - Redrive Policy: `deadLetterTargetArn: ...dlq-personal`, `maxReceiveCount: 5`
2. **Dead-Letter Queue (DLQ):** `interview-prep-leetcode-sync-dlq-personal`
   - URL: `https://sqs.ap-south-2.amazonaws.com/808431466075/interview-prep-leetcode-sync-dlq-personal`
   - Retention Period: `14 days`
   - Encryption: SQS-managed (`SSE-SQS`)

### CloudWatch Observability
- **Log Groups (14-day retention):**
  - `/aws/ec2/interview-prep/backend`
  - `/aws/ec2/interview-prep/nginx` (Active log stream: `i-05a744fb11e56780b-nginx-access`)
  - `/aws/ec2/interview-prep/system` (Active log stream: `i-05a744fb11e56780b-syslog`)
- **CloudWatch Agent:** Operational as systemd service on `i-05a744fb11e56780b` streaming host metrics (`InterviewPrep/EC2` namespace) and logs.
- **Metric Alarms (All State: `OK`):**
  - `interview-prep-ec2-high-cpu`: CPU >= 80% for 5m
  - `interview-prep-ec2-status-check-failed`: StatusCheckFailed_Instance >= 1
  - `interview-prep-sqs-dlq-messages-visible`: DLQ Messages >= 1 for 5m

---

## 7. Secrets Manager Catalog

1. `rds!db-bb979d68-473f-4289-ac52-bd3f9dab5c4a` (RDS master secret, auto-rotated)
2. `interview-prep/rds/app` (FastAPI backend application database credentials)
3. `interview-prep/elasticache/auth-personal` (Valkey AUTH password token)

---

## 8. Missing / Unprovisioned Components
- **API Gateway HTTP API:** None provisioned in `ap-south-2`.
- **Lambda Webhook Receiver:** None provisioned in `ap-south-2`.
- **Secrets Manager Webhook Secret:** `interview-prep/github/webhook-secret-personal` does not exist yet.
- **Amazon SNS Notification Topic:** None provisioned in `ap-south-2`. Alarms currently have `ActionsEnabled: false`.
- **Application Load Balancer (ALB):** None provisioned. Traffic hits EC2 directly.
- **Database Tracking Tables:** `public.leetcode_sync_history` and `public.leetcode_sync_state` have not been executed on RDS yet (pending `004_leetcode_sync_metadata.sql`).
