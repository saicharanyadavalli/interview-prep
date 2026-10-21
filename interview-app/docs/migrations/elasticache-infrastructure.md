# AWS ElastiCache for Valkey / Redis OSS Infrastructure Specification

## 1. Executive Summary & Architecture Overview

This document specifies the production and personal staging caching infrastructure, network architecture, security group rules, encryption-in-transit (TLS), authentication mechanics, CloudFormation automation, and operational runbooks for integrating Amazon ElastiCache into the Interview Prep platform.

### Architecture Overview

```mermaid
flowchart TD
    subgraph Client["Client Layer"]
        Browser["User Web Browser"]
    end

    subgraph Host["AWS EC2 Host (ap-south-2 Hyderabad) - m7i-flex.large"]
        Nginx["Nginx Reverse Proxy\n(Port 80/443)"]
        
        subgraph DockerBridge["Docker Network: interview-prep-network"]
            Frontend["Next.js Frontend Container\n(127.0.0.1:3000)"]
            
            subgraph BackendContainer["FastAPI Backend Container (127.0.0.1:8000)"]
                FastAPI["FastAPI App (2 Workers)"]
                Limiter["SlowAPI Rate Limiter\n(Composite Key: user_id | IP)"]
                CacheService["Async Cache Service\n(Cache-Aside & Health Probes)"]
            end
        end
        
        IAMRole["EC2 IAM Role: InterviewPrepEC2Role\nIMDSv2 Session Token Required"]
    end

    subgraph AWS_VPC["Amazon VPC: interview-prep-vpc (10.0.0.0/16)"]
        subgraph PublicSubnet["Public Subnet (ap-south-2a)"]
            EC2Instance["EC2 Instance Security Group:\ninterview-prep-app-sg"]
        end

        subgraph PrivateSubnets["Private Subnets (No IGW Route)"]
            SubnetA["interview-prep-cache-a (10.0.20.0/24)\nAZ: ap-south-2a"]
            SubnetB["interview-prep-cache-b (10.0.21.0/24)\nAZ: ap-south-2b"]
            
            subgraph ElastiCacheTier["Amazon ElastiCache Cluster"]
                CacheSG["Security Group: interview-prep-cache-sg\nIngress: TCP 6379 from interview-prep-app-sg ONLY\nEgress: Restricted to VPC"]
                ValkeyCluster["ElastiCache for Valkey 7.2+\nServerless (100MB Floor) OR Node-Based (cache.t4g.micro)\nTLS 1.2+ In-Transit Encryption\nAt-Rest Encryption Enabled"]
            end
            
            subgraph RDSTier["Amazon RDS PostgreSQL"]
                RDSSG["Security Group: interview-prep-rds-sg"]
                Postgres["PostgreSQL 17.11 (interview_prep_db)"]
            end
        end
    end

    subgraph AWSServices["AWS Managed Services"]
        SecretsManager["AWS Secrets Manager\nSecret: interview-prep/elasticache/auth\nEncrypted via KMS"]
    end

    %% Network flows
    Browser -->|HTTP/HTTPS| Nginx
    Nginx -->|Proxy /| Frontend
    Nginx -->|Proxy /api/backend/| FastAPI
    Frontend -->|BFF API calls| FastAPI

    %% EC2 to AWS Services
    FastAPI -->|1. Resolve AUTH Token via IMDSv2| SecretsManager
    IAMRole -.->|Authorizes GetSecretValue| SecretsManager

    %% Rate Limiting & Caching (TLS rediss://)
    Limiter ==>|2. Shared Atomic Rate Limit Counters (rediss://:6379/0)| ValkeyCluster
    CacheService ==>|3. Async Cache-Aside GET/SET (rediss://:6379/0)| ValkeyCluster
    ValkeyCluster -.->|Protected by| CacheSG
    CacheSG -.->|Permits Source SG| EC2Instance

    %% Backend to Database
    FastAPI -->|4. Primary App Queries (Port 5432)| Postgres
```

### Core Architectural Principles

1. **Zero Public Network Exposure**: ElastiCache nodes reside strictly inside the private subnets (`interview-prep-cache-a` / `interview-prep-cache-b` or shared private database subnets) with no routes to an Internet Gateway (`interview-prep-igw`). Public IP allocation is architecturally impossible.
2. **Security Group Referencing (Least-Privilege Networking)**: Cache ingress on TCP port `6379` is permitted exclusively from the EC2 backend security group (`interview-prep-app-sg`). No CIDR blocks (`0.0.0.0/0` or even subnet CIDRs) are permitted in ingress rules.
3. **Mandatory Encryption in Transit (TLS 1.2+)**: All data moving between the FastAPI container and ElastiCache is encrypted using TLS (`--transit-encryption-enabled`). Unencrypted plaintext Redis connections are rejected.
4. **Alphanumeric AUTH Token via AWS Secrets Manager**: Authentication credentials are generated and managed via AWS Secrets Manager (`interview-prep/elasticache/auth-${Environment}`), resolved by the EC2 host at startup via instance profile IAM credentials without storing static passwords in git or image layers.
5. **Universal Client Compatibility**: The architecture employs Redis AUTH token authentication over TLS (`rediss://:<token>@<host>:6379/0`), providing 100% native compatibility with SlowAPI's `limits` library and `redis.asyncio` while avoiding the blocking limitations of IAM dynamic token signing.
6. **Graceful Cache-Aside Degradation**: The backend application treats the cache as an accelerator, not a single point of failure. If ElastiCache becomes temporarily unreachable, queries automatically fall back to Amazon RDS PostgreSQL and rate-limiting gracefully falls back to local memory without crashing API requests.

---

## 2. ElastiCache Engine & Topology Comparison: Valkey vs. Redis OSS

### 2.1 The Open-Source Context: Why Valkey?

In March 2024, Redis Ltd. abandoned open-source licensing (BSD-3-Clause) in favor of proprietary, restrictive dual-licenses (RSALv2 and SSPLv1). In response, the Linux Foundation, with backing from AWS, Google Cloud, Oracle, and Ericsson, established **Valkey** as a high-performance, community-governed open-source fork under BSD-3-Clause.

AWS announced first-class support for **Amazon ElastiCache for Valkey** with significant commercial incentives:
- **Direct Price Discount**: Valkey pricing is discounted by **20% to 33%** compared to ElastiCache for Redis OSS across both Serverless and node-based instances.
- **Drop-in Compatibility**: Valkey 7.2 is fully compatible with Redis 7.2 APIs, commands, and wire protocol (RESP2/RESP3). Existing Python clients (`redis-py`, `redis.asyncio`, `limits`) communicate with Valkey transparently without SDK modifications.
- **Future-Proof Upstream**: AWS engineering invests directly in Valkey kernel optimizations (such as enhanced multi-threaded I/O and slot migration performance).

### 2.2 Serverless vs. Node-Based Architecture Comparison

| Feature / Metric | ElastiCache Serverless for Valkey | ElastiCache Serverless for Redis OSS | Node-Based Valkey (`cache.t4g.micro` Standalone) | Node-Based Valkey (`cache.t4g.micro` Multi-AZ Primary + 1 Replica) | Node-Based Redis OSS (`cache.t4g.micro` Standalone) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Engine** | Valkey 7.2 / 8.0 | Redis OSS 7.1 | Valkey 7.2 | Valkey 7.2 | Redis OSS 7.1 |
| **Minimum Storage Floor** | **100 MB** | **1 GB** | 0.55 GiB (fixed) | 0.55 GiB per node | 0.55 GiB (fixed) |
| **Hourly Rate (ap-south-2)** | $0.0084 / 100MB-hr + ECPU | $0.125 / GB-hr + ECPU | **$0.0128 / hr** | **$0.0256 / hr** | $0.0160 / hr |
| **Base Monthly Cost (730 hrs)** | **~$6.15 - $7.50 / mo** | **~$91.25 / mo** | **~$9.34 / mo** | **~$18.68 / mo** | **~$11.68 / mo** |
| **High Availability SLA** | **99.99% Multi-AZ** built-in | 99.99% Multi-AZ built-in | Single node (no HA SLA) | **99.9% Multi-AZ** Auto-Failover | Single node (no HA SLA) |
| **Capacity Management** | Fully automatic (0 to TBs) | Fully automatic (0 to TBs) | Manual node resize | Manual node resize | Manual node resize |
| **Maintenance Windows** | **Zero downtime** (AWS-managed) | Zero downtime (AWS-managed) | Weekly window (brief reboot) | Weekly window (auto-failover) | Weekly window (brief reboot) |
| **Max Connections** | 65,000+ | 65,000+ | ~65,000 | ~65,000 | ~65,000 |
| **TLS Encryption** | **Mandatory** | Mandatory | Configurable (Enabled) | Configurable (Enabled) | Configurable (Enabled) |
| **SlowAPI URI Compatibility**| 100% via UserGroup Password | 100% via UserGroup Password | 100% via AuthToken / UserGroup | 100% via AuthToken / UserGroup | 100% via AuthToken |

### 2.3 Regional Pricing Breakdown (`ap-south-2` Hyderabad vs. `ap-south-1` Mumbai)

| Topology & Instance | Region | Hourly Rate | Estimated Monthly Cost (730 hrs) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Serverless Valkey (100 MB floor)** | `ap-south-2` (Hyderabad) | ~$0.0084/hr (storage) + ECPU | **~$6.15 - $7.50 / month** | Lowest entry cost for Serverless; Multi-AZ included. |
| **Serverless Valkey (100 MB floor)** | `ap-south-1` (Mumbai) | ~$0.0084/hr (storage) + ECPU | **~$6.15 - $7.50 / month** | Identical tier; 100 MB minimum. |
| **Serverless Redis OSS (1 GB floor)** | `ap-south-2` / `ap-south-1` | ~$0.1250/hr (storage) + ECPU | **~$91.25 - $95.00 / month** | ⚠️ Expensive due to 1 GB mandatory floor. |
| **Node-Based Valkey `cache.t4g.micro`** | `ap-south-2` (Hyderabad) | **$0.0128 / hr** | **~$9.34 / month** | Single node, 2 vCPUs, 0.55 GiB RAM. |
| **Node-Based Valkey `cache.t4g.micro`** | `ap-south-1` (Mumbai) | **$0.0128 / hr** | **~$9.34 / month** | Single node, 2 vCPUs, 0.55 GiB RAM. |
| **Node-Based Valkey `cache.t4g.small`** | `ap-south-2` (Hyderabad) | **$0.0256 / hr** | **~$18.69 / month** | Single node, 2 vCPUs, 1.37 GiB RAM. |
| **Node-Based Redis `cache.t4g.micro`** | `ap-south-2` (Hyderabad) | **$0.0160 / hr** | **~$11.68 / month** | 25% higher cost than Valkey equivalent. |

> [!TIP]
> **Key Financial Takeaway:**
> - **ElastiCache Serverless for Redis OSS** requires a mandatory **1 GB floor** (~$91.25/month), making it completely inappropriate for personal staging or lean production.
> - **ElastiCache Serverless for Valkey** reduces the storage floor to **100 MB** (~$6.15/month). For a personal or low-traffic production deployment, this delivers **automatic scaling, 99.99% Multi-AZ resilience, and zero maintenance windows** for LESS than the cost of a single node-based micro instance.

### 2.4 Sizing, Memory Overhead & Operational Constraints

1. **Usable Memory vs. Overhead**:
   - For `cache.t4g.micro`, physical RAM is 0.55 GiB (~560 MB).
   - Redis/Valkey maintains system overhead for background snapshotting (`bgsave`), replication buffers, and connection state. By default, AWS sets `reserved-memory-percent` to 25% (~140 MB). Usable application key storage is approximately **420 MB**.
   - With an average cached JSON payload of 4 KB (e.g. course lesson or question summary), 420 MB stores over **100,000 cached objects** simultaneously, far exceeding the current requirements of the application.
2. **Connection Limits**:
   - `cache.t4g.micro` supports up to **65,000 concurrent client connections**.
   - With 2 Uvicorn workers and connection pool size capped at 10–20 connections per worker, total persistent connections will not exceed **40 connections** (under 0.1% of capacity).
3. **Maintenance Windows**:
   - Node-based single-instance clusters require a weekly maintenance window (e.g., `sun:04:30-sun:05:30 UTC`). Operating system or engine patches may cause a 15–60 second transient disconnect. The application's graceful cache-aside retry pattern handles this without dropping user requests.
   - Serverless clusters apply updates seamlessly in the background with **zero application downtime**.

### 2.5 Recommended Environment Progression

```
┌─────────────────────────────────┐
│     Local Development / CI      │ ──► Docker Compose: redis:7-alpine
│      (redis://localhost:6379)   │     Cost: $0.00 / month (Zero AWS dependencies)
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│   Personal / Staging (Current)  │ ──► ElastiCache Serverless for Valkey (100MB floor)
│     (ap-south-2 Hyderabad)      │     Cost: ~$6.15 - $7.50 / month
└────────────────┬────────────────┘     Alternative: cache.t4g.micro standalone ($9.34/mo)
                 │
                 ▼
┌─────────────────────────────────┐
│     Full Scale Production       │ ──► ElastiCache Serverless for Valkey (Auto-scales)
│     (ap-south-2 Hyderabad)      │     Cost: ~$10.00 - $25.00 / month (usage-based)
└─────────────────────────────────┘     Multi-AZ 99.99% SLA, Zero Maintenance Downtime
```

---

## 3. Networking & Security Specification

### 3.1 VPC & Subnet Architecture

The ElastiCache cluster must be provisioned inside the existing `interview-prep-vpc` network in `ap-south-2` (Hyderabad):

| Network Resource | Resource Identifier | CIDR / Subnet ID | Availability Zone | Route Table Association |
| :--- | :--- | :--- | :--- | :--- |
| **VPC** | `interview-prep-vpc` | `10.0.0.0/16` | Multi-AZ | Main / Local |
| **Compute Subnet (EC2)** | `interview-prep-public-a` | `10.0.1.0/24` | `ap-south-2a` | Public Route Table (`0.0.0.0/0 -> igw`) |
| **Private Subnet A** | `interview-prep-db-a` / `interview-prep-cache-a` | `10.0.10.0/24` or `10.0.20.0/24` | `ap-south-2a` | Private Route Table (No IGW) |
| **Private Subnet B** | `interview-prep-db-b` / `interview-prep-cache-b` | `10.0.11.0/24` or `10.0.21.0/24` | `ap-south-2b` | Private Route Table (No IGW) |

> [!IMPORTANT]
> **Subnet Group Multi-AZ Mandate**:
> Amazon ElastiCache requires a Cache Subnet Group spanning **at least two Availability Zones** (`ap-south-2a` and `ap-south-2b`), even if deploying a single-node standalone cluster. This ensures that the cluster can fail over or migrate seamlessly across AZs without recreating the subnet group.

### 3.2 Security Group Rules (`interview-prep-cache-sg`)

The cache security group enforces strict micro-segmentation:

#### Inbound Rules (Ingress)
| Type | Protocol | Port Range | Source | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Custom TCP** | TCP | `6379` | `sg-xxxxxx` (`interview-prep-app-sg`) | Allow Valkey/Redis cache traffic from EC2 application instance only |

#### Outbound Rules (Egress)
| Type | Protocol | Port Range | Destination | Description |
| :--- | :--- | :--- | :--- | :--- |
| **All Traffic** | All | All | `10.0.0.0/16` | Allow VPC-internal responses (or default VPC egress) |

> [!CAUTION]
> **Security Invariants**:
> - **NEVER** add `0.0.0.0/0` to the inbound rules of `interview-prep-cache-sg`.
> - **NEVER** expose port `6379` to public internet traffic.
> - Source must reference the **Security Group ID** (`interview-prep-app-sg`), NOT the EC2 instance's private IP, ensuring that if the EC2 instance is replaced or scaled, access is maintained automatically without firewall changes.

### 3.3 In-Transit & At-Rest Encryption

1. **In-Transit Encryption (TLS 1.2+)**:
   - Flag: `TransitEncryptionEnabled: true`
   - All client connections must use the `rediss://` protocol scheme.
   - Node-to-node replication traffic and client-to-node communication are encrypted via AWS-managed certificates.
2. **At-Rest Encryption**:
   - Flag: `AtRestEncryptionEnabled: true`
   - Cache snapshots, disk swap files, and memory backups are encrypted using AWS KMS (`aws/elasticache` managed key or custom customer-managed key).

---

## 4. Authentication Architecture & Client Compatibility

### 4.1 Redis AUTH Token vs. AWS IAM Authentication

AWS supports two primary authentication modes for ElastiCache for Valkey and Redis OSS:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             Authentication Comparison                            │
├──────────────────────────────────────┬───────────────────────────────────────────┤
│          Redis AUTH Token            │            AWS IAM Authentication         │
├──────────────────────────────────────┼───────────────────────────────────────────┤
│ • Alphanumeric token (16-128 chars)  │ • Short-lived SigV4 token (15 min expiry) │
│ • Valid for connection lifetime      │ • Generated via AWS credentials / IMDSv2  │
│ • Passed via rediss://:<token>@host  │ • Requires custom CredentialProvider code │
│ • 100% compatible with SlowAPI limits│ • INCOMPATIBLE with SlowAPI limits URI    │
│ • Zero client patching required      │ • Complex refresh loop for async workers  │
│ • Stored securely in Secrets Manager │ • CloudTrail connection audit logs        │
└──────────────────────────────────────┴───────────────────────────────────────────┘
```

### 4.2 The SlowAPI / `limits` Library Constraint

The FastAPI backend uses SlowAPI (`slowapi==0.1.10`), which wraps the Python `limits` library (`limits==5.8.0`).
- The `limits` storage engine instantiates Redis storage via `storage_uri` strings:
  ```python
  # limits/storage/redis.py
  class RedisStorage(Storage):
      def __init__(self, uri: str, **options: Any):
          self.storage = redis.from_url(uri, **options)
  ```
- The URI string parser (`urllib.parse.urlparse`) extracts host, port, db, and password.
- **There is no native capability in `limits` to inject an IAM dynamic credential provider into the URI string.** Attempting to use IAM authentication would require monkey-patching `limits.storage.RedisStorage` or forking the library.
- In contrast, the **Redis AUTH Token** pattern is standard across all Redis and Valkey implementations:
  `rediss://:<AUTH_TOKEN>@<CACHE_HOST>:6379/0`
  It works out of the box with zero modifications to `limiter.py` or `limits`.

### 4.3 Production Authentication Decision

**Architectural Standard: Redis AUTH Token with Secrets Manager Rotation**
1. An alphanumeric AUTH token (32 characters, punctuation excluded) is generated and stored in AWS Secrets Manager (`interview-prep/elasticache/auth-${Environment}`).
2. On EC2 boot, the application resolves the secret value via `InterviewPrepEC2Role` (using IMDSv2), constructs the `rediss://` URI, and passes it to both SlowAPI and the caching service.
3. No credentials are hardcoded, committed to git, or baked into Docker container images.

---

## 5. Environment Variable Contract

### 5.1 Parameter Reference

| Variable Name | Required | Default Value | Example (Production) | Description |
| :--- | :--- | :--- | :--- | :--- |
| `CACHE_ENABLED` | No | `false` | `true` | Master feature flag. If `false`, caching layer degrades to direct DB queries. |
| `CACHE_ENGINE` | No | `valkey` | `valkey` | Caching engine type (`valkey` or `redis`). |
| `CACHE_HOST` | Conditional | `localhost` | `interview-prep-cache.xxxxxx.aps2.cache.amazonaws.com` | ElastiCache primary or configuration endpoint DNS. |
| `CACHE_PORT` | No | `6379` | `6379` | TCP port of the ElastiCache cluster. |
| `CACHE_DB` | No | `0` | `0` | Redis logical database index (0-15). |
| `CACHE_TLS_ENABLED` | No | `false` | `true` | Must be `true` for ElastiCache (`rediss://`), `false` for local docker. |
| `CACHE_AUTH_TOKEN` | Conditional | `""` | `v4lk3yS3cur3T0k3nP4ssw0rd999!` | Redis AUTH token. In production, resolved from Secrets Manager. |
| `CACHE_SECRET_NAME` | No | `interview-prep/elasticache/auth` | `interview-prep/elasticache/auth-production` | Secrets Manager secret name for dynamic resolution on EC2. |
| `CACHE_CONNECT_TIMEOUT`| No | `5.0` | `5.0` | Socket connection timeout in seconds. |
| `CACHE_SOCKET_TIMEOUT` | No | `2.0` | `2.0` | Socket read/write timeout in seconds. |
| `RATE_LIMIT_STORAGE_URI`| Yes | `memory://` | `rediss://:token@host:6379/0` | Canonical SlowAPI storage URI. |
| `CACHE_DEFAULT_TTL` | No | `3600` | `3600` | Default cache expiration time in seconds (1 hour). |
| `CACHE_KEY_PREFIX` | No | `interview_prep:personal:` | `interview_prep:prod:` | Namespace prefix prepended to all Redis keys. |

### 5.2 Environment Configurations by Tier

#### Local Development (`backend/.env` or root `.env`)
```env
# In local development, use Docker Compose Redis (no TLS, no auth)
CACHE_ENABLED=true
CACHE_ENGINE=valkey
CACHE_HOST=localhost
CACHE_PORT=6379
CACHE_DB=0
CACHE_TLS_ENABLED=false
CACHE_AUTH_TOKEN=
RATE_LIMIT_STORAGE_URI=redis://localhost:6379/0
CACHE_KEY_PREFIX=interview_prep:local:
```

#### Docker Compose Full-Stack (`interview-app/docker-compose.yml`)
```yaml
  # Inside backend environment:
  - CACHE_ENABLED=true
  - CACHE_ENGINE=valkey
  - CACHE_HOST=redis
  - CACHE_PORT=6379
  - CACHE_TLS_ENABLED=false
  - RATE_LIMIT_STORAGE_URI=redis://redis:6379/0
  - CACHE_KEY_PREFIX=interview_prep:docker:
```

#### EC2 Staging / Production (`interview-app/.env`)
```env
# AWS EC2 Production Configuration
CACHE_ENABLED=true
CACHE_ENGINE=valkey
CACHE_HOST=interview-prep-cache-personal.xxxxxx.0001.aps2.cache.amazonaws.com
CACHE_PORT=6379
CACHE_DB=0
CACHE_TLS_ENABLED=true
CACHE_SECRET_NAME=interview-prep/elasticache/auth-personal
CACHE_CONNECT_TIMEOUT=5.0
CACHE_SOCKET_TIMEOUT=2.0
RATE_LIMIT_STORAGE_URI=rediss://:{{resolve:secretsmanager:interview-prep/elasticache/auth-personal:SecretString:auth_token}}@interview-prep-cache-personal.xxxxxx.0001.aps2.cache.amazonaws.com:6379/0
CACHE_KEY_PREFIX=interview_prep:personal:
```

---

## 6. Application Integration Architecture Blueprint

### 6.1 Cache Service Module (`backend/services/cache_service.py`)

The application caching service encapsulates connection pooling, health checks, serialization, and graceful fallback:

```python
"""Amazon ElastiCache (Valkey / Redis OSS) async cache client with graceful fallback."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional
from urllib.parse import quote_plus

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[ConnectionPool] = None


def get_cache_url() -> str:
    """Derive canonical Redis connection URL with credentials and TLS."""
    override = os.getenv("CACHE_URL") or os.getenv("RATE_LIMIT_STORAGE_URI")
    if override and override.startswith(("redis://", "rediss://")):
        return override

    host = os.getenv("CACHE_HOST", "localhost")
    port = int(os.getenv("CACHE_PORT", "6379"))
    db = int(os.getenv("CACHE_DB", "0"))
    tls = os.getenv("CACHE_TLS_ENABLED", "false").lower() == "true"
    token = os.getenv("CACHE_AUTH_TOKEN", "").strip()

    scheme = "rediss" if tls else "redis"
    auth_part = f":{quote_plus(token)}@" if token else ""
    return f"{scheme}://{auth_part}{host}:{port}/{db}"


async def get_redis_client() -> Optional[aioredis.Redis]:
    """Obtain or initialize the async Redis connection client."""
    global _pool
    if os.getenv("CACHE_ENABLED", "false").lower() != "true":
        return None

    if _pool is None:
        url = get_cache_url()
        connect_timeout = float(os.getenv("CACHE_CONNECT_TIMEOUT", "5.0"))
        socket_timeout = float(os.getenv("CACHE_SOCKET_TIMEOUT", "2.0"))
        _pool = ConnectionPool.from_url(
            url,
            max_connections=20,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )

    return aioredis.Redis(connection_pool=_pool)


async def cache_get(key: str) -> Optional[Any]:
    """Retrieve and deserialize a JSON object from cache with graceful failure."""
    try:
        client = await get_redis_client()
        if not client:
            return None
        prefix = os.getenv("CACHE_KEY_PREFIX", "interview_prep:")
        raw = await client.get(f"{prefix}{key}")
        return json.loads(raw) if raw else None
    except Exception as exc:
        logger.warning("Cache GET failed for key '%s': %s (falling back to database)", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
    """Serialize and store a JSON object in cache with expiration."""
    try:
        client = await get_redis_client()
        if not client:
            return False
        prefix = os.getenv("CACHE_KEY_PREFIX", "interview_prep:")
        raw = json.dumps(value, default=str)
        await client.set(f"{prefix}{key}", raw, ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.warning("Cache SET failed for key '%s': %s", key, exc)
        return False


async def check_cache_health() -> bool:
    """Verify cache connectivity via PING command."""
    if os.getenv("CACHE_ENABLED", "false").lower() != "true":
        return True  # Cache disabled is not considered unhealthy
    try:
        client = await get_redis_client()
        if not client:
            return False
        return await client.ping()
    except Exception as exc:
        logger.error("Cache health probe failed: %s", exc)
        return False
```

### 6.2 Health Probe Integration (`main.py`)

Integrate cache liveness and readiness into `/health` and `/health/ready`:

```python
@app.get("/health")
async def health(response: Response):
    rds_ok = check_rds_health()
    cache_ok = await check_cache_health()
    checks = {
        "rds_connected": rds_ok,
        "cache_connected": cache_ok,
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY", "").strip()),
    }
    all_ok = all(checks.values())
    if not rds_ok:
        response.status_code = 503
    return {
        "status": "ok" if all_ok else ("degraded" if rds_ok else "unhealthy"),
        "checks": checks,
    }
```

---

## 7. Infrastructure as Code (CloudFormation)

The declarative CloudFormation template is located at:
`infrastructure/cloudformation/elasticache.yaml`

### 7.1 Template Resource Inventory

| Logical ID | Resource Type | Purpose |
| :--- | :--- | :--- |
| `CacheSecurityGroup` | `AWS::EC2::SecurityGroup` | Restricts TCP 6379 to `interview-prep-app-sg` |
| `CacheSubnetGroup` | `AWS::ElastiCache::SubnetGroup` | Associates private subnets across 2 AZs |
| `AuthSecret` | `AWS::SecretsManager::Secret` | Auto-generates secure 32-character Redis AUTH token |
| `CacheUser` | `AWS::ElastiCache::User` | RBAC user for Serverless cache (`default`) |
| `CacheUserGroup` | `AWS::ElastiCache::UserGroup` | RBAC user group linking the user to Serverless cluster |
| `ServerlessCache` | `AWS::ElastiCache::ServerlessCache` | Multi-AZ Serverless Valkey/Redis cache cluster |
| `NodeReplicationGroup`| `AWS::ElastiCache::ReplicationGroup` | Dedicated node-based cluster (`cache.t4g.micro`) |
| `BackendEC2ElastiCachePolicy` | `AWS::IAM::ManagedPolicy` | Least-privilege IAM policy granting EC2 access to auth secret |
| `EC2RolePolicyAttachment` | `AWS::IAM::Policy` | Optional direct attachment to `InterviewPrepEC2Role` |

### 7.2 Deployment via AWS CLI

#### Option A: Deploy Serverless Valkey Cluster (Recommended)
```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/elasticache.yaml \
  --stack-name interview-prep-elasticache-personal \
  --parameter-overrides \
      Environment=personal \
      VpcId=vpc-0123456789abcdef0 \
      CacheSubnetIds=subnet-01111111111111111,subnet-02222222222222222 \
      AppSecurityGroupId=sg-03333333333333333 \
      DeploymentType=Serverless \
      Engine=valkey \
      AttachPolicyToRole=true \
      EC2RoleName=InterviewPrepEC2Role \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-south-2
```

#### Option B: Deploy Node-Based Valkey Cluster (`cache.t4g.micro`)
```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/elasticache.yaml \
  --stack-name interview-prep-elasticache-personal \
  --parameter-overrides \
      Environment=personal \
      VpcId=vpc-0123456789abcdef0 \
      CacheSubnetIds=subnet-01111111111111111,subnet-02222222222222222 \
      AppSecurityGroupId=sg-03333333333333333 \
      DeploymentType=NodeBased \
      Engine=valkey \
      NodeCacheType=cache.t4g.micro \
      NumCacheNodes=1 \
      AttachPolicyToRole=true \
      EC2RoleName=InterviewPrepEC2Role \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-south-2
```

---

## 8. Step-by-Step AWS Console Operator Manual

### Step 1: Verify VPC & Subnet Prerequisites
1. Open the [Amazon VPC Console](https://ap-south-2.console.aws.amazon.com/vpc/home?region=ap-south-2) in **Hyderabad (`ap-south-2`)**.
2. Note your VPC ID (`interview-prep-vpc`).
3. Confirm you have at least two private subnets in distinct Availability Zones (e.g. `interview-prep-db-a` in `ap-south-2a` and `interview-prep-db-b` in `ap-south-2b`).
4. Verify the Route Table: Ensure their route table has **NO** route to `0.0.0.0/0 -> igw`.

---

### Step 2: Create the ElastiCache Security Group
1. Navigate to **VPC > Security groups > Create security group**.
2. **Basic details**:
   - Security group name: `interview-prep-cache-sg`
   - Description: `Security group for Interview Prep ElastiCache cluster`
   - VPC: Select `interview-prep-vpc`.
3. **Inbound rules**:
   - Type: `Custom TCP`
   - Port range: `6379`
   - Source: `Custom` &rarr; Search and select `interview-prep-app-sg` (the EC2 instance security group).
   - Description: `Allow Redis/Valkey from EC2 backend only`
4. **Outbound rules**: Leave default (All traffic).
5. Add tag: `Project` = `interview-prep`. Click **Create security group**.

---

### Step 3: Create the ElastiCache Subnet Group
1. Navigate to the [ElastiCache Console](https://ap-south-2.console.aws.amazon.com/elasticache/home?region=ap-south-2).
2. In the left navigation pane, choose **Subnet groups > Create subnet group**.
3. **Subnet group details**:
   - Name: `interview-prep-cache-subnets-personal`
   - Description: `Private multi-AZ subnets for interview prep cache`
   - VPC: Select `interview-prep-vpc`.
4. **Add subnets**:
   - Select Availability Zones: `ap-south-2a` and `ap-south-2b`.
   - Select the private subnets (`interview-prep-db-a` and `interview-prep-db-b`, or dedicated cache subnets).
5. Click **Create**.

---

### Step 4: Create the Redis AUTH Secret in AWS Secrets Manager
1. Navigate to the [AWS Secrets Manager Console](https://ap-south-2.console.aws.amazon.com/secretsmanager/home?region=ap-south-2).
2. Click **Store a new secret**.
3. Select secret type: **Other type of secret**.
4. Key/value pairs:
   - Key: `auth_token`
   - Value: Click **Generate password** &rarr; Length: `32`, deselect punctuation characters like `"`, `@`, `/`, `\`.
   - Key: `engine`, Value: `valkey`
   - Key: `username`, Value: `default`
5. Secret name: `interview-prep/elasticache/auth-personal`.
6. Leave automatic rotation disabled (can be enabled post-launch). Click **Store**.

---

### Step 5: Provision the ElastiCache Cluster via AWS Console

#### Method A: Serverless Valkey Cluster (Recommended)
1. In the ElastiCache Console, select **Serverless caches > Create Serverless cache**.
2. Select engine: **Valkey**.
3. **Cluster settings**:
   - Name: `interview-prep-cache-personal`
   - Description: `Interview Prep Serverless Valkey Cache`
4. **Connectivity**:
   - VPC: Select `interview-prep-vpc`.
   - Subnets: Select the subnets in `ap-south-2a` and `ap-south-2b`.
   - Security groups: Select `interview-prep-cache-sg` (deselect `default`).
5. **Security & Access Control**:
   - Encryption in-transit (TLS): Enabled (default).
   - Encryption at-rest: Enabled (default).
   - Access control: Select **Password** &rarr; supply the generated `auth_token` from Step 4.
6. **Limit configuration**:
   - Data storage limit: Max `5 GB`.
   - ECPU limit: Max `5000 ECPU/s`.
7. Click **Create**. Provisioning completes in approximately 2 minutes.

#### Method B: Node-Based Valkey Cluster (`cache.t4g.micro`)
1. In the ElastiCache Console, choose **Valkey clusters > Create Valkey cluster**.
2. Select **Cluster cache** &rarr; Deployment option: **Create a new cluster**.
3. **Cluster mode**: Disabled.
4. **Cluster settings**:
   - Cluster name: `interview-prep-node-personal`
   - Engine version: `7.2` (or latest Valkey).
   - Node type: `cache.t4g.micro` (2 vCPUs, 0.55 GiB RAM).
   - Number of replicas: `0` (for single-node staging) or `1` (for Multi-AZ production).
5. **Connectivity**:
   - Subnet group: Select `interview-prep-cache-subnets-personal`.
   - Security groups: Select `interview-prep-cache-sg`.
6. **Security**:
   - Encryption in-transit: **Check "Enable"**.
   - Redis AUTH default user password: Input the `auth_token` from Step 4.
   - Encryption at-rest: **Check "Enable"**.
7. Click **Create**. Provisioning completes in 5–8 minutes.

---

### Step 6: Update EC2 IAM Permissions
Ensure the EC2 instance role (`InterviewPrepEC2Role`) has permissions to read the ElastiCache secret:
1. In the **IAM Console > Roles > InterviewPrepEC2Role**.
2. Add inline policy `ElastiCacheSecretPolicy`:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "ResolveElastiCacheSecretValue",
         "Effect": "Allow",
         "Action": [
           "secretsmanager:GetSecretValue",
           "secretsmanager:DescribeSecret"
         ],
         "Resource": "arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/elasticache/*"
       }
     ]
   }
   ```

---

### Step 7: Verify Connectivity from EC2 Instance
Connect to the EC2 instance via AWS Systems Manager Session Manager and test network connectivity over TLS:

```bash
# 1. Switch to ubuntu user
sudo su - ubuntu
cd /home/ubuntu/interview-prep/interview-app

# 2. Test TLS socket connectivity using OpenSSL
openssl s_client -connect <CACHE_HOST>:6379 -starttls redis </dev/null
# Expected: Verify return code: 0 (ok) and SSL handshake completed

# 3. Test Redis AUTH ping using redis-cli (inside container or host)
docker compose exec backend python -c "
import redis, os
r = redis.Redis(
    host='<CACHE_HOST>',
    port=6379,
    password='<AUTH_TOKEN>',
    ssl=True,
    ssl_cert_reqs='required'
)
print('Redis PING response:', r.ping())
"
# Expected: Redis PING response: True
```

---

### Step 8: Update EC2 Environment & Deploy
Update `/home/ubuntu/interview-prep/interview-app/.env`:

```bash
nano .env
```
Append the cache configuration:
```env
CACHE_ENABLED=true
CACHE_ENGINE=valkey
CACHE_HOST=<CACHE_ENDPOINT_ADDRESS>
CACHE_PORT=6379
CACHE_TLS_ENABLED=true
CACHE_SECRET_NAME=interview-prep/elasticache/auth-personal
RATE_LIMIT_STORAGE_URI=rediss://:<AUTH_TOKEN>@<CACHE_ENDPOINT_ADDRESS>:6379/0
CACHE_KEY_PREFIX=interview_prep:personal:
```

Restart containers cleanly:
```bash
docker compose up -d --no-deps backend
```

Validate application logs and health:
```bash
docker compose logs backend --tail 50
curl -fsS http://127.0.0.1/api/backend/health
```
Expected output:
```json
{
  "status": "ok",
  "checks": {
    "rds_connected": true,
    "cache_connected": true,
    "gemini_key_set": true
  }
}
```

---

## 9. Rollback & Disaster Recovery Procedures

1. **Immediate Cache Bypass**:
   If the cache cluster becomes unresponsive, set `CACHE_ENABLED=false` and `RATE_LIMIT_STORAGE_URI=memory://` in `.env`, then execute `docker compose up -d --no-deps backend`. The backend immediately falls back to direct database execution with zero downtime.
2. **Data Durability**:
   ElastiCache stores transient data (rate-limit counters and cached query results). No authoritative user data, progress records, or credentials reside exclusively in the cache. Evacuating or deleting the cache causes zero data loss.
3. **Clean Teardown**:
   To delete the cluster via CloudFormation without leaving orphaned resources:
   ```bash
   aws cloudformation delete-stack \
     --stack-name interview-prep-elasticache-personal \
     --region ap-south-2
   ```
