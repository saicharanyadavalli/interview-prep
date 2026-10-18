# Database Avatar Reconciliation Runbook
## Cloudinary to Amazon S3 + CloudFront CDN Migration

---

## 1. Executive Summary & Purpose

This runbook defines the operational procedure for reconciling user avatar URLs stored in Amazon RDS PostgreSQL (`interview_prep_db.public.user_profiles`) during the migration from Cloudinary to Amazon S3 and Amazon CloudFront.

The migration replaces legacy Cloudinary URLs (e.g. `https://res.cloudinary.com/...`) with high-performance CloudFront edge delivery URLs (e.g. `https://d123456abcdef8.cloudfront.net/avatars/{user_id}/{filename}`) while ensuring 100% transactional safety, auditability, and preservation of third-party OAuth profile photos.

---

## 2. Architecture & Schema Verification

### 2.1 Database Schema Reference
The target entity is defined in `migrations/rds/001_schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS public.user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL,
  username TEXT UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  avatar_url TEXT NOT NULL DEFAULT '',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigger ensures updated_at reflects timestamp on modification
CREATE TRIGGER trg_user_profiles_updated_at
  BEFORE UPDATE ON public.user_profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.set_current_timestamp_updated_at();
```

### 2.2 S3 & CloudFront Key Schema
As codified in `docs/migrations/migration-contracts.md`:
- **S3 Bucket:** `interview-prep-assets-808431466075-ap-south-2`
- **Region:** `ap-south-2` (Hyderabad)
- **Avatar S3 Key Schema:** `avatars/{user_id}/{filename_or_uuid}.{ext}`
- **CloudFront Delivery URL:** `{ASSET_BASE_URL}/avatars/{user_id}/{filename}` (e.g., `https://d123456abcdef8.cloudfront.net/avatars/{user_id}/avatar.png`)

---

## 3. Safety Guardrails & Strict Invariants

The reconciliation utility (`scripts/reconcile_db_avatars.py`) implements strict guardrails:

1. **Third-Party Avatar Preservation:**
   - **Google Avatars:** URLs containing `googleusercontent.com` are strictly excluded from migration.
   - **GitHub Avatars:** URLs containing `githubusercontent.com` are strictly excluded.
   - **Inline Base64 Data:** URLs starting with `data:image/` are preserved intact.
   - **Empty / Null Avatars:** Blank strings and `NULL` values are left untouched.
2. **Column Immutability:**
   - The reconciliation script mutates **ONLY** `avatar_url` and `updated_at`.
   - Columns such as `email`, `username`, `name`, and `phone` are **NEVER** modified.
   - Parameterized SQL ensures zero possibility of SQL injection:
     ```sql
     UPDATE user_profiles SET avatar_url = %s, updated_at = now() WHERE id = %s;
     ```
3. **Atomic Transaction Isolation:**
   - Multi-row updates run inside an explicit PostgreSQL transaction (`BEGIN ... COMMIT`).
   - If any individual row update fails or the connection is interrupted, an automatic `ROLLBACK` is issued, leaving the database in its original state.
4. **Mandatory Explicit Confirmation:**
   - Dry-run is the default mode.
   - Live execution (`--execute`) requires the explicit `--confirm` flag; otherwise, the tool immediately aborts with exit code 1.

---

## 4. Environment Variables & Prerequisites

Before running the reconciliation tool on EC2 or during maintenance windows, ensure the following environment variables are configured:

```bash
# Database Connection (Priority: direct URL or AWS Secrets Manager)
export DATABASE_URL="postgresql://interview_prep_app:PASSWORD@rds-endpoint.ap-south-2.rds.amazonaws.com:5432/interview_prep_db"
# Or via AWS Secrets Manager:
# export RDS_SECRET_ARN="arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/rds/app"

# Asset Delivery Origin (CloudFront distribution)
export ASSET_BASE_URL="https://d123456abcdef8.cloudfront.net"

# Target S3 Bucket & Region (Fallbacks)
export S3_ASSETS_BUCKET="interview-prep-assets-808431466075-ap-south-2"
export S3_ASSETS_REGION="ap-south-2"
```

Verify database connectivity prior to migration:
```bash
python scripts/verify_rds_migration.py --manifest docs/migrations/migration-manifest.json
```

---

## 5. Step-by-Step Reconciliation Execution

### Step 1: Execute Dry-Run & Generate Audit Mapping

Execute the reconciliation script in `--dry-run` mode and export the proposed mappings to an audit JSON file:

```bash
python scripts/reconcile_db_avatars.py \
  --dry-run \
  --export-mapping docs/migrations/avatar-reconciliation-mapping.json \
  --asset-base-url "https://d123456abcdef8.cloudfront.net"
```

**Expected Output:**
- An ASCII table displaying each user ID, existing Cloudinary URL, and proposed CloudFront URL.
- Summary statistics indicating scanned records, Cloudinary candidates, and preserved external avatars.
- Generated audit file: `docs/migrations/avatar-reconciliation-mapping.json`.

### Step 2: Audit & Cross-Verify Mapping File

Inspect the exported mapping file to verify mapped URLs:

```bash
cat docs/migrations/avatar-reconciliation-mapping.json | head -n 35
```

Structure of the mapping file:
```json
{
  "metadata": {
    "generated_at": "2026-10-18T13:30:00Z",
    "generator": "scripts/reconcile_db_avatars.py",
    "total_records": 42,
    "asset_base_url": "https://d123456abcdef8.cloudfront.net",
    "s3_bucket": "interview-prep-assets-808431466075-ap-south-2",
    "s3_region": "ap-south-2"
  },
  "mappings": [
    {
      "id": "4a2b9687-9d7a-4286-b489-35a1f6a15db4",
      "email": "candidate@example.com",
      "username": "candidate42",
      "old_avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/interview-prep/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png",
      "new_avatar_url": "https://d123456abcdef8.cloudfront.net/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png"
    }
  ]
}
```

Verify that S3 objects exist for the mapped CloudFront URLs using AWS CLI or S3 client:
```bash
aws s3 ls s3://interview-prep-assets-808431466075-ap-south-2/avatars/ --recursive
```

### Step 3: Execute Live Transactional Migration

Once the audit mapping is validated, execute the live migration:

```bash
python scripts/reconcile_db_avatars.py \
  --execute \
  --confirm \
  --export-mapping docs/migrations/avatar-reconciliation-executed.json \
  --asset-base-url "https://d123456abcdef8.cloudfront.net"
```

> [!IMPORTANT]
> The `--confirm` flag is required. Omitting `--confirm` will fail safely with a zero-mutation guarantee.

**Execution Behavior:**
- Queries all candidate rows where `avatar_url ILIKE '%cloudinary%'`.
- Begins a single database transaction.
- Executes parameterized `UPDATE user_profiles SET avatar_url = %s, updated_at = now() WHERE id = %s`.
- Commits transaction upon success and outputs confirmation logs.

### Step 4: Post-Migration Verification Queries

Execute direct verification SQL queries in RDS to confirm completion:

```sql
-- 1. Ensure zero Cloudinary URLs remain
SELECT COUNT(*) AS remaining_cloudinary_avatars
FROM public.user_profiles
WHERE avatar_url ILIKE '%cloudinary%';
-- Expected Result: 0

-- 2. Confirm updated CloudFront URLs
SELECT id, username, avatar_url, updated_at
FROM public.user_profiles
WHERE avatar_url ILIKE '%cloudfront.net%'
LIMIT 10;

-- 3. Confirm external OAuth profile photos remain untouched
SELECT id, username, avatar_url
FROM public.user_profiles
WHERE avatar_url ILIKE '%googleusercontent%'
   OR avatar_url ILIKE '%githubusercontent%'
LIMIT 10;
```

---

## 6. Rollback Procedures

If an operational anomaly or asset delivery issue occurs post-migration, the database state can be rolled back to original Cloudinary URLs using the exported mapping file.

### Step 6.1: Rollback Dry-Run Preview
Preview the rollback without mutating records:

```bash
python scripts/reconcile_db_avatars.py \
  --rollback docs/migrations/avatar-reconciliation-mapping.json
```

Output displays:
- Rollback target file path
- Total records to restore
- Confirmation prompt

### Step 6.2: Live Transactional Rollback
Execute the rollback with `--confirm`:

```bash
python scripts/reconcile_db_avatars.py \
  --rollback docs/migrations/avatar-reconciliation-mapping.json \
  --confirm
```

**Verification after Rollback:**
```sql
SELECT COUNT(*) AS restored_cloudinary_avatars
FROM public.user_profiles
WHERE avatar_url ILIKE '%cloudinary%';
-- Should match the total_records in mapping file
```

---

## 7. Troubleshooting & Operational FAQs

### Q1: What happens if a database lock or network error occurs during execution?
The script wraps all mutations in an explicit transaction block (`conn.autocommit = False`). If an exception is encountered on any row, `conn.rollback()` is immediately invoked. No partial updates are committed.

### Q2: What if a user updated their avatar between dry-run and live execution?
The reconciliation script re-queries the latest database state at the beginning of `--execute`. If a user has already replaced their avatar with a Google avatar or new upload, the classifier detects this and preserves their latest URL.

### Q3: How do we test the script without access to production RDS?
Unit tests are fully isolated and mock the database layer:
```bash
pytest backend/tests/unit/test_reconcile_db_avatars.py -v
```
All 26 test cases pass without requiring live network or database connections.
