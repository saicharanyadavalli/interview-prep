# S3 + CloudFront Migration: Shared Interface Contracts & Task Matrix

## 1. Project Baseline
- **Repository:** saicharanyadavalli/interview-prep
- **Base Branch:** `aws-migration`
- **Feature Branch:** `feature/cloudinary-s3-migration`
- **Starting Commit:** `fa9f1bf1e544c13ad0a0f7affba86fcbc8a36002`
- **AWS Region:** `ap-south-2` (Hyderabad)
- **AWS Account:** `808431466075`
- **EC2 IAM Role:** `InterviewPrepEC2Role`

---

## 2. Shared Environment & Naming Conventions
- **S3 Bucket Name:** `interview-prep-assets-808431466075-ap-south-2`
- **S3 Bucket Region:** `ap-south-2`
- **Environment Variables:**
  - `S3_ASSETS_BUCKET`: Name of the S3 bucket (`interview-prep-assets-808431466075-ap-south-2`)
  - `S3_ASSETS_REGION`: AWS region (`ap-south-2`)
  - `ASSET_BASE_URL`: CloudFront distribution delivery origin (e.g. `https://d123456abcdef8.cloudfront.net`)
- **Key Schemas:**
  - Avatars: `avatars/{user_id}/{unique_uuid}.{ext}`
  - System Design Lessons: `system-design/{chapter_number}/{filename_slug}.{ext}`
  - Other Static Assets: `static/{category}/{filename_slug}.{ext}`

---

## 3. Strict File Ownership Matrix
- **Agent 1 (Inventory):**
  - `docs/migrations/cloudinary-inventory.md`
  - `docs/migrations/cloudinary-inventory.json`
- **Agent 2 (Infrastructure & IAM):**
  - `infrastructure/cloudformation/assets-s3-cloudfront.yaml`
  - `docs/migrations/aws-infrastructure.md`
- **Agent 3 (FastAPI S3 Upload):**
  - `backend/services/s3_storage_service.py`
  - `backend/routes/profile.py`
  - `backend/tests/unit/test_s3_storage_service.py`
  - `backend/tests/integration/test_profile_endpoints.py`
- **Agent 4 (Static Migration Tooling):**
  - `scripts/migrate_cloudinary_to_s3.py`
  - `backend/tests/unit/test_migrate_cloudinary_to_s3.py`
  - `docs/migrations/migration-manifest.json`
- **Agent 5 (Database Reconciliation):**
  - `scripts/reconcile_db_avatars.py`
  - `backend/tests/unit/test_reconcile_db_avatars.py`
  - `docs/migrations/database-avatar-migration.md`
- **Agent 6 (Frontend & Config):**
  - `frontend/next.config.ts`
  - `DEPLOYMENT.md`
  - `.env.example`
- **Agent 7 (Security, Testing & Review):**
  - `docs/migrations/security-audit-report.md`
