# Security Incident Report — GitGuardian Incident #38322346

## 1. Executive Summary
- **Incident ID:** GitGuardian `#38322346`
- **Severity:** High ("PostgreSQL Credentials")
- **Target Repository:** `saicharanyadavalli/interview-prep`
- **Flagged Branch:** `aws-migration`
- **Flagged Commit:** `41b4eae` (`feat(rds): migrate application data access to Amazon RDS PostgreSQL and AWS Secrets Manager`)
- **Flagged File:** `interview-app/backend/tests/unit/test_rds_client.py`
- **Target AWS Region:** `ap-south-2` (Hyderabad)
- **Active Secrets Manager Secret:** `interview-prep/rds/app` (`arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/rds/app-TVJeDz`)
- **Classification:** **Synthetic Test Fixture** (Safe / Nonfunctional mock data)

---

## 2. Evidence & AWS Verification Analysis
A safe, read-only investigation was executed in accordance with AWS security guidelines:
1. **AWS Identity & Access:**
   - Principal: `arn:aws:iam::808431466075:user/charan-admin`
   - Active RDS Database: `interview-prep-db` (Postgres 17.11) in region `ap-south-2`
   - Active RDS Endpoint Host: `interview-prep-db.clia2o8uuwlb.ap-south-2.rds.amazonaws.com`
2. **In-Memory Credential Comparison:**
   - Flagged Fixture 1 (`test_mask_db_url_masks_password`):
     - Username match: **NO** (Active: application role; Fixture: `my_user`)
     - Password match: **NO**
     - Host match: **NO** (Active: `ap-south-2`; Fixture: `rds-endpoint.us-east-1.rds.amazonaws.com`)
     - Database name match: **YES** (`interview_prep_db`)
   - Flagged Fixture 2 (`test_get_rds_credentials_from_secrets_manager`):
     - Username match: **YES** (`interview_prep_app` matches application standard role)
     - Password match: **NO**
     - Host match: **NO** (Active: `ap-south-2`; Fixture: `test-rds.cluster-xyz.us-east-1.rds.amazonaws.com`)
     - Database name match: **YES** (`interview_prep_db`)
3. **Usage Verification:**
   - The connection strings in unit tests were used strictly in memory as arguments passed to the `mask_db_url()` helper or mock `boto3` client.
   - The tests never attempted a network connection to any database or AWS endpoint.
   - Git history analysis (`git log -S`) confirmed that the flagged fixture strings existed exclusively in `test_rds_client.py` in commit `41b4eae` and nowhere else in the codebase, environment files, or documentation.

---

## 3. Remediation & Hardening Actions
1. **Synthetic Fixture Replacement (`interview-app/backend/tests/unit/test_rds_client.py`):**
   - Replaced all hardcoded credential-like strings with nonfunctional dummy values.
   - Replaced hostnames with RFC 2606 / RFC 6761 reserved example hostname `db.example.invalid`.
   - Replaced dummy AWS secret ARNs with RFC dummy account IDs (`123456789012`).
   - Configured region tests to validate `ap-south-2`.
2. **Masking Helper Hardening (`services/rds_client.py`):**
   - Fixed `mask_db_url()` to reliably mask percent-encoded passwords, URLs with password-only netlocs, and URLs with complex query parameters.
   - Sanitized exception logging in connection pool initialization, health checks, and query execution to prevent logging raw exception strings that could leak database connection parameters.
3. **Test Isolation (`interview-app/backend/tests/conftest.py` & `test_main_endpoints.py`):**
   - Configured default test environment `DATABASE_URL` and mocked `check_rds_health` on diagnostic health endpoints to ensure local test suites never attempt live AWS network resolution.
4. **Migration Test Sanitization (`interview-app/tests/test_rds_migration.py`):**
   - Replaced credential fixtures with synthetic mock strings and `db.example.invalid`.

---

## 4. Verification Results
- **Unit & Integration Tests:**
  - `pytest interview-app/backend/tests/unit/test_rds_client.py`: 17 passed, 0 failed.
  - `pytest interview-app/tests/test_rds_migration.py`: 13 passed, 0 failed.
  - `pytest interview-app/backend/tests interview-app/tests`: 180 passed, 0 failed (100% pass rate).
- **Secret Scanning:**
  - `detect-secrets` scan across all 187 tracked files confirmed 0 production secrets exposed. Flagged fixture passwords completely eliminated.

---

## 5. GitGuardian Alert Resolution Guidance
- **Recommended Action:** Resolve incident `#38322346` in the GitGuardian dashboard.
- **Resolution Reason:** **Test / Dummy Data (False Positive)**
- **Justification Note:**
  > The flagged connection string in `interview-app/backend/tests/unit/test_rds_client.py` at commit `41b4eae` was an entirely synthetic unit test fixture used solely to test string masking (`mask_db_url`). Safe in-memory verification against the active AWS Secrets Manager secret (`interview-prep/rds/app` in `ap-south-2`) confirmed that neither the password nor host ever matched real infrastructure. The fixture has been replaced with unmistakable test data (`db.example.invalid`) in commit `7fe9df0` on branch `aws-migration`.
