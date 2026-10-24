# Database Avatar Reconciliation Runbook
## Cloudinary to Amazon S3 + CloudFront CDN Migration

---

## 1. Executive Summary & Purpose

This runbook defines the operational procedure for reconciling user avatar URLs stored in Amazon RDS PostgreSQL (`interview_prep_db.public.user_profiles`) during the migration from Cloudinary to Amazon S3 and Amazon CloudFront.

The migration replaces legacy Cloudinary URLs (e.g. `https://res.cloudinary.com/...`) with high-performance CloudFront edge delivery URLs (e.g. `https://d3xxxxxxxxxxxx.cloudfront.net/avatars/{user_id}/{filename}`) while ensuring 100% transactional safety, auditability, and preservation of third-party OAuth profile photos.

> [!IMPORTANT]
> **Strict Verification Gate:** An avatar is ELIGIBLE for database update **ONLY IF** its destination S3 object is verified to exist in the destination bucket (checked via S3 `HeadObject` or via a verified manifest entry from `migrate_cloudinary_to_s3.py`). If the destination object does not exist in S3, it is marked as `missing_destination` (`pending_upload`) and **CANNOT** be updated in RDS!

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
- **Personal S3 Bucket:** `interview-prep-assets-808431466075-20261018-k8m4q2z7` (active deployed personal bucket)
- **Personal CloudFront Domain:** `d1uj3o882835l0.cloudfront.net`
- **Production S3 Bucket:** `interview-prep-assets-808431466075-production-ap-south-2`
- **Region:** `ap-south-2` (Hyderabad)
- **Avatar S3 Key Schema:** `avatars/{user_id}/{filename_or_uuid}.{ext}`
- **CloudFront Delivery URL:** `{ASSET_BASE_URL}/avatars/{user_id}/{filename}` (e.g., `https://d3xxxxxxxxxxxx.cloudfront.net/avatars/{user_id}/avatar.png`)

---

## 3. Safety Guardrails & Strict Invariants

The reconciliation utility (`scripts/reconcile_db_avatars.py`) implements strict guardrails:

1. **Destination S3 Object Verification Gate (Zero Broken Links Guarantee):**
   - An avatar candidate is marked **ELIGIBLE** for database mutation **ONLY IF** its destination S3 object is verified to exist:
     - Verified in AWS S3 using `s3_client.head_object(Bucket=..., Key=...)`, **OR**
     - Verified via an existing verified entry (`status == "verified"`) in `migration-manifest.json`.
   - If the destination object does not exist in S3, it is categorized as `missing_destination` / `pending_upload` and **CANNOT** be updated in RDS.

2. **Strict ASSET_BASE_URL Validation:**
   - Requires a valid, non-placeholder HTTPS `ASSET_BASE_URL`.
   - Fictitious placeholder hostnames (`d123456abcdef8.cloudfront.net`, `<distribution-id>`, `example.com`, `placeholder`, `your-distribution`) are strictly **REJECTED** with a `ValueError`.
   - Must use `https://` protocol; plain `http://` is forbidden.

3. **Third-Party Avatar Preservation:**
   - **Google Avatars:** URLs containing `googleusercontent.com` are strictly excluded from migration.
   - **GitHub Avatars:** URLs containing `githubusercontent.com` are strictly excluded.
   - **Inline Base64 Data:** URLs starting with `data:image/` are preserved intact.
   - **Empty / Null Avatars:** Blank strings and `NULL` values are left untouched.

4. **Column Immutability:**
   - The reconciliation script mutates **ONLY** `avatar_url` and `updated_at`.
   - Columns such as `email`, `username`, `name`, and `phone` are **NEVER** modified.
   - Parameterized SQL ensures zero possibility of SQL injection:
     ```sql
     UPDATE user_profiles SET avatar_url = %s, updated_at = now() WHERE id = %s;
     ```

5. **Atomic Transaction Isolation:**
   - Multi-row updates run inside an explicit PostgreSQL transaction (`conn.autocommit = False`, `BEGIN ... COMMIT`).
   - If any individual row update fails or the connection is interrupted, an automatic `ROLLBACK` is issued, leaving the database in its original state.

6. **Mandatory Explicit Confirmation:**
   - Dry-run is the default mode.
   - Live execution (`--execute`) requires the explicit `--confirm` flag; otherwise, the tool immediately aborts with exit code 1.

---

## 4. Environment Variables & Prerequisites

Before running the reconciliation tool on EC2 or during maintenance windows, ensure the following environment variables are configured:

```bash
# Database Connection (Priority: direct URL or AWS Secrets Manager)
export DATABASE_URL="postgresql://interview_prep_app:PASSWORD@rds-endpoint.ap-south-2.rds.amazonaws.com:5432/interview_prep_db"

# Asset Delivery Origin (Validated CloudFront distribution URL)
export ASSET_BASE_URL="https://d1uj3o882835l0.cloudfront.net"

# Target S3 Bucket & Region (Fallbacks)
export S3_ASSETS_BUCKET="interview-prep-assets-808431466075-20261018-k8m4q2z7"
export S3_ASSETS_REGION="ap-south-2"
```

Verify database connectivity prior to migration:
```bash
python scripts/verify_rds_migration.py --manifest docs/migrations/migration-manifest.json
```

---

## 5. Step-by-Step Reconciliation Execution

### Step 1: Execute Dry-Run & Generate Audit Mapping

Execute the reconciliation script in `--dry-run` mode with verification against S3 and/or the migration manifest, and export the proposed mappings to an audit JSON file:

```bash
python scripts/reconcile_db_avatars.py \
  --dry-run \
  --asset-base-url "https://d3xxxxxxxxxxxx.cloudfront.net" \
  --manifest docs/migrations/migration-manifest.json \
  --export-mapping docs/migrations/avatar-reconciliation-mapping.json
```

**Dry-Run Execution Output & Breakdown:**
The utility displays an ASCII candidate preview table followed by an explicit 8-metric breakdown report:

```
================================================================================
              DATABASE AVATAR RECONCILIATION REPORT (DRY-RUN)
================================================================================
Execution Mode:                                 DRY-RUN
Profiles scanned:                               150
Cloudinary avatar candidates:                   42
Avatars whose destination objects are verified: 40
Missing destination objects:                    2
Unavailable source assets:                      0
Invalid mappings:                               0
Rows eligible for change:                       40
Rows that must remain unchanged:                110
Preserved Non-Cloudinary:                       108
  - Google Avatars:                             65
  - GitHub Avatars:                             28
  - Inline Base64 Data:                         5
  - Empty / Null Avatars:                       10
  - Other / Preserved:                          0
Exported Mapping File:                          docs/migrations/avatar-reconciliation-mapping.json
================================================================================
```

### 8-Metric Breakdown Explanation:
| Metric | Description |
| :--- | :--- |
| **Profiles scanned** | Total rows read from `user_profiles` table. |
| **Cloudinary avatar candidates** | Rows with genuine Cloudinary avatars (excluding preserved OAuth URLs). |
| **Avatars whose destination objects are verified** | Candidates whose destination S3 object exists in S3 or is verified in the manifest. |
| **Missing destination objects** | Cloudinary avatars whose S3 destination object is missing (`pending_upload`); **cannot be updated in RDS**. |
| **Unavailable source assets** | Assets marked failed or 404 in the migration manifest. |
| **Invalid mappings** | Malformed URLs or rows with invalid user IDs that could not be mapped. |
| **Rows eligible for change** | Candidates with verified destination objects and valid mappings ready for RDS update. |
| **Rows that must remain unchanged** | All scanned rows that must not be changed (`scanned - eligible`), preserving un-migrated and OAuth profiles. |

### Step 2: Audit & Cross-Verify Mapping File

Inspect the exported audit mapping file:

```bash
cat docs/migrations/avatar-reconciliation-mapping.json | head -n 45
```

Structure of the mapping file:
```json
{
  "metadata": {
    "generated_at": "2026-10-18T13:30:00Z",
    "generator": "scripts/reconcile_db_avatars.py",
    "total_records": 42,
    "eligible_records": 40,
    "asset_base_url": "https://d3xxxxxxxxxxxx.cloudfront.net",
    "s3_bucket": "interview-prep-assets-808431466075-20261018-k8m4q2z7",
    "s3_region": "ap-south-2",
    "breakdown": {
      "profiles_scanned": 150,
      "cloudinary_candidates": 42,
      "verified_destinations": 40,
      "missing_destinations": 2,
      "unavailable_sources": 0,
      "invalid_mappings": 0,
      "eligible_for_change": 40,
      "must_remain_unchanged": 110
    }
  },
  "mappings": [
    {
      "id": "4a2b9687-9d7a-4286-b489-35a1f6a15db4",
      "email": "candidate@example.com",
      "username": "candidate42",
      "old_avatar_url": "https://res.cloudinary.com/cloud/image/upload/v1/interview-prep/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png",
      "new_avatar_url": "https://d3xxxxxxxxxxxx.cloudfront.net/avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png",
      "s3_key": "avatars/4a2b9687-9d7a-4286-b489-35a1f6a15db4/avatar.png",
      "status": "eligible",
      "destination_verified": true,
      "eligible": true,
      "reason": "Destination S3 object verified"
    }
  ],
  "eligible_mappings": [ ... ]
}
```

Verify missing destination objects (if any) and upload them before proceeding:
```bash
# Verify missing objects in S3
aws s3 ls s3://interview-prep-assets-808431466075-20261018-k8m4q2z7/avatars/ --recursive
```

### Step 3: Execute Live Transactional Migration

Once the audit mapping is validated and all destination objects are verified, execute the live migration:

```bash
python scripts/reconcile_db_avatars.py \
  --execute \
  --confirm \
  --asset-base-url "https://d3xxxxxxxxxxxx.cloudfront.net" \
  --manifest docs/migrations/migration-manifest.json \
  --export-mapping docs/migrations/avatar-reconciliation-executed.json
```

> [!IMPORTANT]
> The `--confirm` flag is required. Omitting `--confirm` will fail safely with a zero-mutation guarantee.
> Only rows marked `eligible` (destination S3 object verified) will be mutated. Rows with `missing_destination` are skipped.

**Execution Behavior:**
- Queries all candidate rows where `avatar_url ILIKE '%cloudinary%'`.
- Checks S3 existence for every candidate.
- Filters down strictly to `eligible_mappings`.
- Begins a single PostgreSQL transaction (`conn.autocommit = False`).
- Executes parameterized `UPDATE user_profiles SET avatar_url = %s, updated_at = now() WHERE id = %s`.
- Commits transaction upon success and outputs confirmation logs.

### Step 4: Post-Migration Verification Queries

Execute direct verification SQL queries in RDS to confirm completion:

```sql
-- 1. Check remaining Cloudinary URLs (should be 0 or equal to missing_destinations)
SELECT COUNT(*) AS remaining_cloudinary_avatars
FROM public.user_profiles
WHERE avatar_url ILIKE '%cloudinary%';

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
  --rollback docs/migrations/avatar-reconciliation-executed.json
```

Output displays:
- Rollback target file path
- Total records to restore (skips `missing_destination` and un-migrated items)
- Confirmation prompt

### Step 6.2: Live Transactional Rollback
Execute the rollback with `--confirm`:

```bash
python scripts/reconcile_db_avatars.py \
  --rollback docs/migrations/avatar-reconciliation-executed.json \
  --confirm
```

**Verification after Rollback:**
```sql
SELECT COUNT(*) AS restored_cloudinary_avatars
FROM public.user_profiles
WHERE avatar_url ILIKE '%cloudinary%';
```

---

## 7. Troubleshooting & Operational FAQs

### Q1: What happens if a database lock or network error occurs during execution?
The script wraps all mutations in an explicit transaction block (`conn.autocommit = False`). If an exception is encountered on any row, `conn.rollback()` is immediately invoked. No partial updates are committed.

### Q2: Why are some Cloudinary avatars not updated?
An avatar is eligible for update **ONLY IF** its destination S3 object exists. If `migrate_cloudinary_to_s3.py` has not yet uploaded the avatar, the avatar is reported as `missing_destination` and skipped in RDS to prevent broken image references for users. Once the S3 upload is complete, re-run `reconcile_db_avatars.py`.

### Q3: Why does `reconcile_db_avatars.py` reject `d123456abcdef8.cloudfront.net`?
`d123456abcdef8.cloudfront.net` is a fictitious example hostname. Writing placeholder URLs into production RDS would break profile images. The script strictly enforces validation of `ASSET_BASE_URL` to ensure only real, non-placeholder HTTPS CDN URLs are used.

### Q4: How do we test the script without access to production RDS or AWS?
Unit tests are fully isolated and mock both the database and S3 layers:
```bash
pytest backend/tests/unit/test_reconcile_db_avatars.py -v
```
All 36 test cases pass without requiring live network or database connections.
