# S3 + CloudFront Migration: Shared Interface Contracts & Task Matrix (Staging Hardening)

## 1. Project Baseline
- **Repository:** saicharanyadavalli/interview-prep
- **Base Branch:** `aws-migration` (at `a26d95e65ca7c5414f6ded3d2b910d3bf3e14268`)
- **Active Feature Branch:** `feature/cloudinary-s3-staging-hardening`
- **AWS Region:** `ap-south-2` (Hyderabad)
- **AWS Account:** `808431466075`
- **EC2 IAM Role:** `InterviewPrepEC2Role` (Do NOT mutate or auto-attach policies in staging)

---

## 2. Shared Environment & Naming Conventions

### Staging vs. Production Naming
- **Staging Bucket:** `interview-prep-assets-808431466075-staging-ap-south-2`
- **Production Bucket:** `interview-prep-assets-808431466075-production-ap-south-2`
- **CloudFormation Parameter `Environment`:** Defaults to `staging`.
- **CloudFormation Parameter `AttachPolicyToRole`:** Defaults to `false` (isolated reviewable policy, no auto-attachment to existing EC2 role).

### Environment Variables
- `S3_ASSETS_BUCKET`: Target S3 bucket name.
- `S3_ASSETS_REGION`: AWS region (`ap-south-2`).
- `ASSET_BASE_URL`: Actual validated CloudFront distribution URL (e.g. `https://d3xxxxxxxxxxxx.cloudfront.net`).
  - **STRICT RULE:** Fictitious default hostnames (`d123456abcdef8.cloudfront.net`, `<distribution-id>`) are FORBIDDEN in runtime or executable CLI tools.
  - **STRICT RULE:** In staging/production, when `ASSET_BASE_URL` is missing or invalid, `s3_storage_service.py` must FAIL CLEARLY. It MUST NOT silently fall back to direct regional S3 URLs for private buckets protected by OAC.
  - Test mode fallback is permitted ONLY when running under `TESTING=1` or explicit test configuration.

### Asset Key Schemas
- **User Avatars:** `avatars/{user_id}/{unique_uuid}.{ext}`
- **System Design Lessons:** `system-design/{chapter_number}/{filename_slug}.{ext}`
- **Static Assets:** `static/{category}/{filename_slug}.{ext}`

### Avatar Reconciliation Contract (`reconcile_db_avatars.py`)
- **Verification Gate:** An existing avatar in RDS is ELIGIBLE for database update ONLY IF:
  1. The target S3 object actually exists (verified via S3 `head_object` or verified manifest entry).
  2. The avatar source is a genuine Cloudinary asset.
  3. Non-Cloudinary avatars (Google, GitHub, inline data URIs, empty/null) are strictly PRESERVED and untouched.
- If the destination object does not exist in S3, the avatar is reported as `missing_destination` or `pending_upload` and CANNOT be updated in RDS.

---

## 3. Strict File Ownership Matrix

- **Agent A (Docker & Runtime Configuration):**
  - `docker-compose.yml`
  - `backend/docker-compose.yml`
  - `.env.example`
  - `backend/.env.example`
  - `frontend/.env.example`
  - `backend/tests/unit/test_runtime_config.py`

- **Agent B (Asset Migration Tooling):**
  - `scripts/migrate_cloudinary_to_s3.py`
  - `backend/tests/unit/test_migrate_cloudinary_to_s3.py`
  - `docs/migrations/migration-manifest.json`

- **Agent C (Existing Avatar Data Migration):**
  - `scripts/reconcile_db_avatars.py`
  - `backend/tests/unit/test_reconcile_db_avatars.py`
  - `docs/migrations/database-avatar-migration.md`

- **Agent D (AWS Infrastructure & IAM):**
  - `infrastructure/cloudformation/assets-s3-cloudfront.yaml`
  - `docs/migrations/aws-infrastructure.md`

- **Agent E (Cloudinary Removal & Backend Integration):**
  - `backend/routes/profile.py`
  - `backend/services/s3_storage_service.py`
  - `backend/requirements.txt`
  - `backend/tests/unit/test_s3_storage_service.py`
  - `backend/tests/integration/test_profile_endpoints.py`
  - `frontend/next.config.ts`

- **Agent F (Independent Quality & Security Reviewer):**
  - Independent audit across all specialist changes.
  - Verification test suite execution.
  - `docs/migrations/staging-readiness-audit.md`

- **Lead Agent G (Integration & Orchestrator):**
  - Overall coordination, conflict resolution, final git commits, DEPLOYMENT.md, and staging readiness sign-off.
