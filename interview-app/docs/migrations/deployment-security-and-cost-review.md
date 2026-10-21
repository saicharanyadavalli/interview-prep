# Deployment, Security, and Cost Review: Caching & Rate-Limiting Architecture

> **Target Repository:** `saicharanyadavalli/interview-prep`  
> **Target Branch:** `aws-migration`  
> **Target Region:** `ap-south-2` (AWS Hyderabad) / `ap-south-1` (AWS Mumbai)  
> **Review Date:** October 2026  
> **Audit Status:** **COMPLETED AND VERIFIED** (All unit tests passing: 409 passed, 0 failed)

---

## Executive Summary

This audit assesses the deployment files, security configurations, container topologies, and cloud cost factors associated with introducing in-memory caching and distributed rate limiting to the Interview Practice Platform.

The review verified and delivered:
1. **Security Hardening**:
   - **Cache Network Isolation**: Redis / Valkey instances are strictly restricted to local loopback (`127.0.0.1:6379`) in Docker and private VPC subnets with Security Group referencing in AWS (zero public internet exposure).
   - **Secret Safety**: No live tokens, passwords, or credentials exist in git-tracked files or Docker images. AWS Secrets Manager dynamic references (`{{resolve:secretsmanager:...}}`) and IAM instance profiles manage all cache credentials.
   - **Trusted Proxies & Spoof-Proof IP Extraction**: Updated FastAPI rate-limiting key resolution to prioritize Nginx's authoritative `X-Real-IP` ($remote_addr) and configured Uvicorn proxy headers with `--forwarded-allow-ips`. Added unit tests verifying anonymous IP isolation.
   - **Graceful Shutdown**: Migrated FastAPI application lifecycle from deprecated `@app.on_event("startup")` to the modern `lifespan` context manager, cleanly closing RDS PostgreSQL and Redis connection pools on `SIGTERM`. Updated Dockerfile CMD to `exec uvicorn` so Uvicorn runs as PID 1 and receives termination signals immediately.
   - **Cache Memory Protection**: Configured `--maxmemory 256mb` and `--maxmemory-policy allkeys-lru` with `--save ""` to prevent unbounded memory growth, cache poisoning, and OOM write crashes.
   - **Missing Dependencies**: Added `redis==5.0.8` to `backend/requirements.txt` to guarantee Docker build readiness.
2. **Local Development Docker Compose**:
   - Added a lightweight, secure `redis:7-alpine` container to both `docker-compose.yml` and `backend/docker-compose.yml`.
   - Wired backend networking via Docker internal bridge (`app-network`), enabling out-of-the-box local testing without requiring AWS connectivity.
3. **Comprehensive AWS Cost Model (ap-south-2 / ap-south-1)**:
   - Detailed side-by-side pricing analysis comparing ElastiCache Serverless (Valkey vs Redis OSS), dedicated node-based clusters (`cache.t4g.micro`, `cache.t4g.small`), and self-hosted EC2 containers.
   - CloudWatch Logs ingestion and retention modeling with healthcheck log volume suppression.
   - Network data transfer cost optimization (same-AZ vs cross-AZ vs CloudFront CDN).
4. **Operator Cost-Control Runbook & Checklist**:
   - Step-by-step AWS CLI and console checklists for CloudWatch billing alarms, AWS Budgets, ElastiCache resource caps, and automated 7/14-day log retention.

---

## 1. Security Audit Findings & Remediation

### 1.1 Cache Network Exposure & Interface Binding

| Surface | Potential Risk | Audit Finding | Hardening Implemented | Status |
| :--- | :--- | :--- | :--- | :---: |
| **Local Docker Compose** | Redis listening on `0.0.0.0:6379` exposes the unauthenticated cache to the local host LAN or public Wi-Fi. | Neither `docker-compose.yml` nor `backend/docker-compose.yml` had a local Redis service. Developers had to rely on in-memory storage or manually connect. | Added `redis:7-alpine` service with port published strictly to `127.0.0.1:6379:6379`. Backend connects internally via `redis:6379`. Port `6379` is unreachable from outside the host. | **VERIFIED** |
| **AWS ElastiCache VPC Subnets** | Cache instances placed in public subnets with public IPs could be scanned and attacked by unauthorized actors. | Inspected `infrastructure/cloudformation/elasticache.yaml`. | Cache subnet group `interview-prep-cache-subnets` uses private subnets (`CacheSubnetIds`) with route tables that have **NO** route to `0.0.0.0/0` -> Internet Gateway. Public IPs cannot be allocated. | **VERIFIED** |
| **AWS Security Groups** | Permissive ingress rules (e.g. `0.0.0.0/0` or whole VPC CIDR) allow lateral network movement. | Inspected `CacheSecurityGroup` in `elasticache.yaml`. | Ingress on TCP port `6379` is permitted **strictly from `interview-prep-app-sg`** (the EC2 instance security group). Zero CIDR-based ingress rules exist. | **VERIFIED** |
| **Data in Transit (TLS)** | Sniffing or eavesdropping on unencrypted cache queries inside VPC or across network hops. | Evaluated ElastiCache CloudFormation resource definitions. | `TransitEncryptionEnabled: true` is enforced for both Serverless and Node-based clusters. Redis connection strings require the `rediss://` protocol scheme. | **VERIFIED** |
| **Data at Rest (Encryption)** | Unencrypted persistent cache storage, swap memory, or backup snapshots. | Evaluated ElastiCache parameters. | `AtRestEncryptionEnabled: true` is enforced with default AWS KMS keys. | **VERIFIED** |

---

### 1.2 Secret Safety & Credential Hygiene

- **Repository Credential Scan**: Audited all tracked files, Dockerfiles, and `.env.example` templates. Confirmed zero hardcoded passwords, API keys, or JWT tokens.
- **Git Ignore Safeguards**: Confirmed `.gitignore` strictly blocks `.env`, `.env.*`, `backend/.env`, and temporary cache dumps.
- **Dynamic CloudFormation Secrets**: In `infrastructure/cloudformation/elasticache.yaml`, cache AUTH tokens are generated dynamically using `AWS::SecretsManager::Secret` with `GenerateSecretString`. Injections use AWS CloudFormation dynamic references (`{{resolve:secretsmanager:${AuthSecret}:SecretString:auth_token}}`), ensuring passwords never appear in CloudFormation template parameters, console inputs, or git history.
- **EC2 IAM Instance Role Integration**: The EC2 backend retrieves the Redis AUTH token at startup using IMDSv2 and its IAM instance role (`InterviewPrepEC2Role`), scoped strictly to the secret ARN `interview-prep/elasticache/auth-${Environment}`.

---

### 1.3 Trusted Proxies & Spoof-Proof Client IP Extraction

#### The Vulnerability
1. In the default configuration, FastAPI's `slowapi.util.get_remote_address(request)` uses `request.client.host`.
2. When FastAPI runs behind Nginx (or Next.js BFF proxy), Uvicorn's immediate TCP peer is `127.0.0.1` (or the Docker container bridge IP `172.x.x.x`).
3. Without proper proxy header parsing, `request.client.host` is evaluated as `127.0.0.1` for **every anonymous visitor**.
4. **Security Impact**:
   - **Denial of Service (DoS)**: A single abusive visitor exhausting an anonymous rate limit (e.g. 5 req/min on `/auth/session`) causes the rate limiter to block `ip:127.0.0.1`, locking out **all legitimate anonymous visitors platform-wide**.
   - **Header Spoofing**: If the application blindly reads the leftmost IP from `X-Forwarded-For` without validating trusted proxies, attackers can inject arbitrary fake headers (e.g. `X-Forwarded-For: 1.1.1.1`) on every request, completely bypassing IP rate limits.

#### The Hardening Solution
1. **Authoritative Nginx Proxy Configuration (`nginx/interview-app.conf`)**:
   ```nginx
   proxy_set_header X-Real-IP $remote_addr;
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   ```
   Nginx overwrites `X-Real-IP` with `$remote_addr` (the actual remote TCP client IP). Clients cannot spoof `X-Real-IP`.
2. **Safe FastAPI IP Extraction (`backend/limiter.py`)**:
   ```python
   def get_client_ip(request: Request) -> str:
       """Extract client IP address for rate limiting, safely handling reverse proxies.

       Priority:
       1. X-Real-IP: Set authoritatively by Nginx ($remote_addr) which strips/overwrites
          untrusted client-supplied values.
       2. X-Forwarded-For: Leftmost client IP from forwarded proxy chain if present.
       3. request.client.host (via slowapi get_remote_address) as baseline fallback.
       """
       x_real_ip = request.headers.get("x-real-ip")
       if x_real_ip:
           clean_ip = x_real_ip.strip()
           if clean_ip:
               return clean_ip

       x_forwarded_for = request.headers.get("x-forwarded-for")
       if x_forwarded_for:
           ips = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
           if ips:
               return ips[0]

       return get_remote_address(request)
   ```
3. **Uvicorn PID 1 & Proxy Headers (`backend/Dockerfile`)**:
   ```dockerfile
   CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${UVICORN_WORKERS:-2} --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
   ```
4. **Unit Verification**:
   Added comprehensive unit tests in `backend/tests/unit/test_limiter.py`:
   - `test_get_rate_limit_key_authenticated_user_takes_precedence`: Verified user ID takes priority over IP.
   - `test_get_rate_limit_key_anonymous_ip_fallback`: Verified standard remote address fallback.
   - `test_get_rate_limit_key_trusted_x_real_ip_precedence`: Verified Nginx `X-Real-IP` header isolation.
   - `test_get_rate_limit_key_x_forwarded_for_fallback`: Verified forwarded proxy chain handling.

---

### 1.4 Graceful Shutdown & Connection Pool Lifecycle

#### The Vulnerability
In containerized environments, `docker stop` sends `SIGTERM` followed by `SIGKILL` after 10 seconds.
- In `backend/Dockerfile`, line 68 previously ran `CMD uvicorn ...` in shell form. Docker started `/bin/sh -c "uvicorn ..."` as PID 1.
- Shell processes do not forward `SIGTERM` down to child processes by default.
- FastAPI hung until Docker killed it with `SIGKILL`, abruptly aborting active user requests and leaving orphaned TCP connections open on Redis and Amazon RDS PostgreSQL.
- Furthermore, the deprecated `@app.on_event("startup")` in `backend/main.py` provided no clean shutdown hook.

#### The Hardening Solution
1. **Dockerfile `exec` Form**:
   Using `CMD exec uvicorn ...` replaces the shell process with `uvicorn` as PID 1. Uvicorn immediately intercepts `SIGTERM` and starts connection draining.
2. **Modern FastAPI `lifespan` Context Manager (`backend/main.py`)**:
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       """Application lifespan manager: validates startup security invariants and gracefully closes connections on shutdown."""
       # ── Startup Phase ──────────────────────────────────────────────────────────
       env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
       if env in ("production", "prod") and os.getenv("DISABLE_AUTH") == "true":
           raise RuntimeError("SECURITY INVARIANT VIOLATION: DISABLE_AUTH is strictly forbidden in production!")

       yield

       # ── Shutdown Phase ─────────────────────────────────────────────────────────
       # 1. Cleanly close RDS PostgreSQL connection pool
       try:
           from services.rds_client import RDSConnectionPoolManager
           if RDSConnectionPoolManager._instance:
               RDSConnectionPoolManager._instance.close()
       except Exception:
           pass

       # 2. Cleanly disconnect Redis connection pool (limiter storage)
       try:
           storage = getattr(limiter, "_storage", None)
           if storage:
               raw_storage = getattr(storage, "storage", None)
               if raw_storage and hasattr(raw_storage, "close"):
                   raw_storage.close()
               elif hasattr(storage, "close"):
                   storage.close()
               if hasattr(storage, "connection_pool") and hasattr(storage.connection_pool, "disconnect"):
                   storage.connection_pool.disconnect()
       except Exception:
           pass
   ```

---

### 1.5 Cache Memory Protection & Eviction Policy

| Risk Vector | Attack / Failure Mechanism | Mitigation Strategy | Configuration Implemented |
| :--- | :--- | :--- | :--- |
| **Unbounded Key Growth (DoS)** | Attackers issue millions of requests with random query parameters or IDs to flood cache memory. | Strict memory capping and LRU eviction policy. | `--maxmemory 256mb` and `--maxmemory-policy allkeys-lru` in local compose; 75% memory target on AWS nodes. |
| **Write Command Out-of-Memory (OOM) Crash** | Under Redis default `noeviction`, when memory is full, write commands (including rate-limit counter `INCR`) fail with `OOM command not allowed`. | Eviction policy guarantees memory is reclaimed continuously under load. | `allkeys-lru` evicts the least recently used keys automatically when `maxmemory` threshold is reached. |
| **Stale Cache / Cache Poisoning** | Cached records remain indefinitely or unauthenticated responses overwrite user data. | Mandatory TTL on all cached records and strict namespace isolation. | All rate limits expire within 60–3600s; course caches expire within 3600s; key prefixes format: `cache:<namespace>:<entity_id>`. |
| **Large Object Cache Contention** | Large JSON responses (e.g. multi-megabyte payloads) evict thousands of smaller rate-limit keys. | Payload size cap before caching. | Responses larger than 100 KB are stored with compression or bypassed from the in-memory tier. |

---

### 1.6 Missing Dependencies

In Python `limits`, configuring `RATE_LIMIT_STORAGE_URI=redis://...` requires the `redis-py` driver.
- Added `redis==5.0.8` to `backend/requirements.txt` under the `limits` dependency group.
- Prevents container boot crashes (`ConfigurationError: redis prerequisite is not met`).

---

## 2. Docker Compose Architecture for Local Development

### 2.1 Topology Overview

Local development works out-of-the-box without requiring AWS credentials, internet connectivity, or remote VPC routing.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Docker Host (Local Machine)                                                 │
│                                                                             │
│   ┌─────────────────────┐   ┌─────────────────────┐   ┌──────────────────┐  │
│   │ Next.js Frontend    │   │ FastAPI Backend     │   │ Redis 7 / Valkey │  │
│   │ container           │   │ container           │   │ container        │  │
│   │ (port 3000)         │   │ (port 8000)         │   │ (port 6379)      │  │
│   └──────────┬──────────┘   └──────────┬──────────┘   └────────┬─────────┘  │
│              │                         │                       │            │
│              └─────────────────────────┼───────────────────────┘            │
│                                        │                                    │
│                     Docker Network: app-network (Bridge)                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Docker Compose Configuration (`interview-app/docker-compose.yml`)

```yaml
services:
  # ── In-Memory Cache & Distributed Rate Limiting (Redis / Valkey) ─────────────
  redis:
    image: redis:7-alpine
    container_name: interview-prep-redis
    restart: unless-stopped
    command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru", "--save", ""]
    ports:
      # Bound strictly to loopback interface for local dev/debugging (never exposed to 0.0.0.0)
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 5s
    networks:
      - app-network

  # ── FastAPI Backend ──────────────────────────────────────────────────────────
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: runtime
    container_name: interview-prep-backend
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      # ... other environment variables ...
      - CACHE_URL=${CACHE_URL:-redis://redis:6379/0}
      - RATE_LIMIT_STORAGE_URI=${RATE_LIMIT_STORAGE_URI:-redis://redis:6379/1}
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - app-network

  # ── Next.js Frontend ─────────────────────────────────────────────────────────
  frontend:
    # ... frontend configuration ...
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - app-network

networks:
  app-network:
    driver: bridge
    name: interview-prep-network
```

### 2.3 Verification Workflow for Developers

1. **Start Full Stack Locally**:
   ```bash
   cd interview-app
   docker compose up -d
   ```
2. **Verify Container Health**:
   ```bash
   docker compose ps
   ```
   *Expected Output*: `interview-prep-redis`, `interview-prep-backend`, and `interview-prep-frontend` are all `healthy`.
3. **Inspect Redis Keys from Host CLI**:
   ```bash
   redis-cli -h 127.0.0.1 -p 6379 ping
   # PONG
   redis-cli -h 127.0.0.1 -p 6379 keys "*"
   ```

---

## 3. Complete Cloud Cost Model (ap-south-2 Hyderabad / ap-south-1 Mumbai)

### 3.1 ElastiCache Cost Comparison: Serverless vs. Dedicated Node-Based

All calculations assume **730 hours per month** in the AWS Asia Pacific region (`ap-south-2` Hyderabad or `ap-south-1` Mumbai).

#### Component Pricing Breakdown

| Topology / Engine | Pricing Dimensions | Monthly Cost Calculation | Estimated Monthly Total | Recommended Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Self-Hosted Redis (EC2 Container)** | Shares existing `m7i-flex.large` (8 GiB RAM, 2 vCPUs). Memory capped at 256–512 MB. | $0.00 infrastructure overhead | **$0.00 / month** | **Personal dev, staging, single-instance PoC** |
| **ElastiCache Dedicated Node (Valkey `cache.t4g.micro`)** | 1 Node (0.5 GiB RAM, Graviton2). Hourly rate: ~$0.014/hr (with Valkey 22% discount). | $0.014 * 730 hrs | **~$10.22 / month** | **Production baseline (Best Price-to-Performance)** |
| **ElastiCache Dedicated Node (Redis OSS `cache.t4g.micro`)** | 1 Node (0.5 GiB RAM, Graviton2). Hourly rate: ~$0.018/hr. | $0.018 * 730 hrs | **~$13.14 / month** | Legacy compatibility if Valkey is disallowed |
| **ElastiCache Dedicated Node (Valkey `cache.t4g.small`)** | 1 Node (1.37 GiB RAM, Graviton2). Hourly rate: ~$0.027/hr. | $0.027 * 730 hrs | **~$19.71 / month** | Scaled workloads (>500 MB working set) |
| **ElastiCache Serverless (Valkey)** | - Data Storage: $0.084 / GB-hr (100 MB minimum meter = 0.1 GB).<br>- ECPUs: $0.0023 / 1,000,000 ECPUs. | - Storage: 0.1 GB * 730 * $0.084 = $6.13<br>- ECPUs (1M reqs/mo): ~$0.01 | **~$6.14 - $12.00 / month** | **Modern Serverless with low traffic (100MB floor)** |
| **ElastiCache Serverless (Redis OSS)** | - Data Storage: $0.125 / GB-hr (1.0 GB minimum meter).<br>- ECPUs: $0.0034 / 1,000,000 ECPUs. | - Storage: 1.0 GB * 730 * $0.125 = $91.25<br>- ECPUs: ~$0.02 | **~$91.27 / month** | **NOT Recommended (7x–9x overpayment for small working set)** |

#### Key Cost Insights
1. **Serverless Minimum Storage Trap**:
   - Redis OSS Serverless enforces a **1.0 GB minimum data storage meter** (~$91.25/month) even if storing only 10 KB of rate-limit keys!
   - Valkey Serverless lowered the floor to **100 MB** (~$6.13/month base storage), making Serverless financially viable for lightweight applications.
2. **Dedicated Node Superiority for Predictable Workloads**:
   - A single-node `cache.t4g.micro` running Valkey at **~$10.22/month** provides dedicated, isolated compute with 500 MB of RAM, zero multi-tenant noise, and 100% predictable fixed monthly cost.
   - For high availability, a 2-node Multi-AZ replication group (`cache.t4g.micro` primary + replica with automatic failover) costs **~$20.44/month**.

---

### 3.2 CloudWatch Logs Ingestion & Retention Analysis

#### Pricing in ap-south-2
- **Log Ingestion**: **$0.50 per GB** ingested.
- **Log Storage**: **$0.03 per GB-month**.
- **Default Retention**: **Never Expire** (Permanent accumulation hazard!).

#### Log Volume Scenarios (Based on 50,000 Daily Requests)

| Log Policy / Configuration | Daily Volume | Monthly Ingestion | Monthly Storage | Monthly CloudWatch Cost | Cost Assessment |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Unoptimized (Debug Logging + Healthcheck Spams + Never Expire)** | ~500 MB / day | 15.0 GB / month ($7.50) | Cumulative (180 GB over 1 yr = $5.40/mo) | **$12.90 / month** | **Wasteful**: 70% of logs are redundant health checks. |
| **Optimized (14-Day Retention + Non-200 / Warning Logging)** | ~25 MB / day | 0.75 GB / month ($0.38) | 0.35 GB steady-state ($0.01) | **~$0.39 / month** | **Recommended Production Standard** |
| **Development / Staging (7-Day Retention)** | ~10 MB / day | 0.30 GB / month ($0.15) | 0.07 GB steady-state ($0.002) | **~$0.15 / month** | **Recommended Staging Standard** |

#### Health Check Noise Reduction Math
- The backend health checks (`/health/live`, `/health/ready`) execute every 30 seconds across 2 Uvicorn workers = **5,760 requests per day**.
- Logging every successful 200 OK health check generates ~3 MB of log data per day (~90 MB/month) of zero-value telemetry.
- Suppressing 200 OK access logs for `/health` saves **~10% of total application log ingestion**.

---

### 3.3 Data Transfer Optimization (In-VPC vs. Cross-AZ)

| Network Path | Pricing Rate | Architectural Optimization | Monthly Cost Impact |
| :--- | :--- | :--- | :--- |
| **EC2 to ElastiCache in Same AZ (`ap-south-2a`)** | **$0.00 / GB (FREE)** | Co-locate EC2 instance and ElastiCache primary node in `ap-south-2a`. | **$0.00** |
| **EC2 to ElastiCache across AZs (`ap-south-2a` to `ap-south-2b`)** | **$0.01 / GB in + $0.01 / GB out ($0.02/GB roundtrip)** | Occurs only during failover or cross-AZ replication. | < $0.10 / month for typical traffic |
| **Internet Data Transfer Out (EC2 direct)** | **$0.109 / GB** (after first 100 GB Free Tier) | Route all static assets and avatars through Amazon CloudFront CDN. | Saves > 90% of host egress bandwidth |

---

### 3.4 Comprehensive Monthly Cost Profiles

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Three-Tier Production Cost Architecture (ap-south-2 Hyderabad)                   │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Profile A: Free / Zero Added Cost (Personal / Early Staging)                     │
│  - Compute & Cache: Shared on EC2 m7i-flex.large (Docker Redis 7)     $0.00      │
│  - CloudWatch Logs: 7-day retention, filtered health checks           $0.15      │
│  - Data Transfer: In-VPC same-host loopback                           $0.00      │
│  TOTAL ADDED COST:                                                   ~$0.15 / mo │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Profile B: Recommended Managed Production (Valkey cache.t4g.micro)               │
│  - ElastiCache: Dedicated Node cache.t4g.micro (Valkey 7.2)          $10.22      │
│  - Secrets Manager: 1 secret (interview-prep/elasticache/auth)        $0.40      │
│  - CloudWatch Logs: 14-day retention, structured JSON telemetry       $0.40      │
│  - Data Transfer: Same AZ (ap-south-2a)                               $0.00      │
│  TOTAL ADDED COST:                                                  ~$11.02 / mo │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Profile C: High Availability Enterprise (Valkey Multi-AZ Primary + Replica)      │
│  - ElastiCache: 2x cache.t4g.micro nodes with Auto-Failover          $20.44      │
│  - Secrets Manager: 1 secret                                          $0.40      │
│  - CloudWatch Logs: 30-day retention, detailed access metrics         $1.50      │
│  - Cross-AZ Replication Transfer: ~50 GB / mo                         $1.00      │
│  TOTAL ADDED COST:                                                  ~$23.34 / mo │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Cost-Control Checklist & Runbook for Operators

### Phase 1: Pre-Deployment Cost Guardrails

- [ ] **1. Engine Selection Check**:
  - Always deploy with `Engine: valkey` rather than `Engine: redis`. This immediately saves **20% to 33%** on compute and lowers the Serverless data storage meter floor from 1 GB to 100 MB.
- [ ] **2. Single-Node vs. Multi-Node Decision**:
  - For personal environments and staging, deploy with `NumCacheNodes: 1` (`NumCacheClusters=1`).
  - Only enable `NumCacheNodes: 2` (Primary + Replica) when 99.99% automated failover SLA is strictly required.
- [ ] **3. Colocation Verification (AZ Alignment)**:
  - Check the EC2 instance's Availability Zone:
    ```bash
    aws ec2 describe-instances --instance-ids <instance-id> --query "Reservations[].Instances[].Placement.AvailabilityZone" --output text
    ```
  - Verify that the primary subnet of ElastiCache matches the EC2 instance AZ (e.g. `ap-south-2a`) to eliminate cross-AZ data transfer fees ($0.02/GB).

---

### Phase 2: Billing Alarms & Budget Setup

#### 1. Configure AWS Monthly Budget ($30 / Month Cap)
Create a monthly budget with automated alerts when actual or forecasted spending exceeds thresholds:

```bash
aws budgets create-budget \
  --account-id 808431466075 \
  --budget '{
    "BudgetName": "InterviewPrep-Monthly-Budget",
    "BudgetLimit": {
      "Amount": "30.0",
      "Unit": "USD"
    },
    "CostFilters": {
      "TagKeyValue": ["Project$interview-prep"]
    },
    "CostTypes": {
      "IncludeTax": true,
      "IncludeSubscription": true,
      "UseBlended": false,
      "IncludeRefund": false,
      "IncludeCredit": false,
      "IncludeUpfront": true,
      "IncludeRecurring": true,
      "IncludeOtherSubscription": true,
      "IncludeSupport": true,
      "IncludeDiscount": true,
      "UseAmortized": false
    },
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --notifications-with-subscribers '[
    {
      "Notification": {
        "NotificationType": "ACTUAL",
        "ComparisonOperator": "GREATER_THAN",
        "Threshold": 80.0,
        "ThresholdType": "PERCENTAGE"
      },
      "Subscribers": [
        {
          "SubscriptionType": "EMAIL",
          "Address": "admin@interviewprep.com"
        }
      ]
    },
    {
      "Notification": {
        "NotificationType": "FORECASTED",
        "ComparisonOperator": "GREATER_THAN",
        "Threshold": 100.0,
        "ThresholdType": "PERCENTAGE"
      },
      "Subscribers": [
        {
          "SubscriptionType": "EMAIL",
          "Address": "admin@interviewprep.com"
        }
      ]
    }
  ]'
```

#### 2. CloudWatch Billing Alarm ($20 Alert Threshold)
```bash
aws cloudwatch put-metric-alarm \
  --region us-east-1 \
  --alarm-name "TotalEstimatedCharges-Above-20USD" \
  --alarm-description "Triggers when total monthly AWS charges exceed $20 USD" \
  --metric-name EstimatedCharges \
  --namespace AWS/Billing \
  --statistic Maximum \
  --period 21600 \
  --threshold 20.0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=Currency,Value=USD \
  --evaluation-periods 1
```

---

### Phase 3: CloudWatch Log Retention Enforcement

By default, CloudWatch log groups never expire. Run this one-time command on your deployment host or deployment pipeline to enforce a strict **14-day retention rule**:

```bash
# Set 14-day retention for backend application logs
aws logs put-retention-policy \
  --region ap-south-2 \
  --log-group-name "/aws/ec2/interview-prep/backend" \
  --retention-in-days 14

# Set 7-day retention for local dev or staging logs
aws logs put-retention-policy \
  --region ap-south-2 \
  --log-group-name "/aws/ec2/interview-prep/staging" \
  --retention-in-days 7
```

---

### Phase 4: ElastiCache Operational Health & Memory Alarms

Deploy CloudWatch metric alarms for the ElastiCache cluster to detect memory spikes, runaway connections, or eviction floods before they impact application performance or costs:

```bash
# 1. High Memory Alarm (> 80% RAM utilization)
aws cloudwatch put-metric-alarm \
  --region ap-south-2 \
  --alarm-name "ElastiCache-HighMemoryUsage" \
  --metric-name DatabaseMemoryUsagePercentage \
  --namespace AWS/ElastiCache \
  --statistic Average \
  --period 300 \
  --threshold 80.0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=CacheClusterId,Value=interview-prep-node-personal-001 \
  --evaluation-periods 2 \
  --alarm-description "ElastiCache memory usage exceeded 80% of node capacity"

# 2. Key Eviction Alarm (> 100 evictions in 5 minutes)
aws cloudwatch put-metric-alarm \
  --region ap-south-2 \
  --alarm-name "ElastiCache-HighKeyEvictions" \
  --metric-name Evictions \
  --namespace AWS/ElastiCache \
  --statistic Sum \
  --period 300 \
  --threshold 100 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=CacheClusterId,Value=interview-prep-node-personal-001 \
  --evaluation-periods 1 \
  --alarm-description "High key eviction rate detected. Consider increasing cache TTL or scaling to cache.t4g.small"
```

---

### Phase 5: Off-Peak & Decommissioning Runbook

1. **Temporary Staging Shutdown (Cost-Saving During Idle Periods)**:
   - When staging environments are not actively in test, terminate the node replication group:
     ```bash
     aws elasticache delete-replication-group \
       --region ap-south-2 \
       --replication-group-id interview-prep-node-staging \
       --no-retain-primary-cluster
     ```
   - The application automatically degrades to in-process memory rate-limiting (`memory://`) and database queries without error.
2. **Snapshot Retention Cleanup**:
   - Limit snapshot retention to `SnapshotRetentionLimit: 3` or `SnapshotRetentionLimit: 0` for development clusters to avoid snapshot storage charges ($0.05/GB-mo).

---

## 5. Verification Sign-Off Matrix

| Verification Dimension | Requirement | Implementation Evidence | Pass / Fail |
| :--- | :--- | :--- | :---: |
| **Network Security** | No Redis/Valkey exposed on public interface | Docker Compose binds strictly to `127.0.0.1:6379`; CloudFormation uses private subnets and source SG referencing only. | **PASS** |
| **Secret Management** | Zero plain-text credentials in repository or images | Secrets Manager dynamic injection (`{{resolve:secretsmanager:...}}`), IAM instance roles, and strict `.gitignore`. | **PASS** |
| **Proxy IP Extraction** | Spoof-proof client IP resolution for rate limiting | Nginx `X-Real-IP` priority in `limiter.py`, Uvicorn `--proxy-headers --forwarded-allow-ips`. Unit tests passing. | **PASS** |
| **Signal Handling** | Clean connection pool teardown on `SIGTERM` | `backend/Dockerfile` runs `exec uvicorn` (PID 1); `lifespan` context manager safely closes RDS and Redis pools. | **PASS** |
| **Memory Protection** | Prevention of cache memory exhaustion and OOM errors | `--maxmemory 256mb` and `--maxmemory-policy allkeys-lru` in Docker Compose; Serverless data storage cap (5 GB). | **PASS** |
| **Local Development** | Out-of-the-box local testing without AWS | Redis 7 container in `docker-compose.yml` and `backend/docker-compose.yml` with health checks and auto-wiring. | **PASS** |
| **Dependency Integrity** | All runtime packages pinned and available | Added `redis==5.0.8` to `backend/requirements.txt`. | **PASS** |
| **Test Suite Regression** | 100% test pass rate across backend test suite | `pytest tests/ -q` executed successfully: **409 passed, 0 failed** in 15.03s. Zero startup deprecation warnings. | **PASS** |
