# Amazon RDS PostgreSQL 17.11 Migration Runbook

This directory contains the canonical migration artifacts to initialize the **Amazon RDS PostgreSQL 17.11** schema and import the 11 table backup files from Supabase into `interview_prep_db`.

> [!WARNING]
> **Pre-cutover State:**
> Running this migration populates the Amazon RDS database with 100% data parity. It **does NOT** cut over production application traffic or change authentication. The live application on AWS EC2 (`http://16.113.92.222`) continues to run on Supabase until a separately approved cutover phase.

---

## 1. Architecture & Design Principles

1. **Decoupled Application User Model:**
   - In Supabase, user progress and history tables referenced `auth.users(id)`.
   - On Amazon RDS, `public.user_profiles` (`id UUID PRIMARY KEY`) serves as the root application user entity.
   - All user data tables (`user_progress`, `practice_history`, `user_comments`, `learning_track_progress`) reference `user_profiles(id) ON DELETE CASCADE`.
   - All 13 user profiles in `backups/user_profiles.json` match the 13 distinct users across all user activity tables (0 orphan rows).

2. **Full Data Parity (26,910 Total Records):**
   - `user_profiles` (13 rows)
   - `question_bank_questions` (1,081 rows)
   - `question_bank_qnum_aliases` (2,493 rows)
   - `leetcode_problems` (4,017 rows)
   - `leetcode_approaches` (3,305 rows)
   - `leetcode_code_solutions` (15,747 rows)
   - `course_lessons` (77 rows)
   - `user_progress` (43 rows)
   - `practice_history` (94 rows)
   - `user_comments` (20 rows)
   - `learning_track_progress` (20 rows)

3. **Lossless Type Marshalling:**
   - Arrays (`TEXT[]`, `INT[]`) are mapped directly to PostgreSQL native arrays.
   - Rich JSON structures (`examples`, `raw`) are mapped to `JSONB`.
   - GIN indexes are established on `topic_tags` and `company_tags` for fast querying.
   - `CHECK` constraints prevent non-positive IDs and ensure difficulty domain integrity.

---

## 2. Prerequisites

Before executing the migration:

1. **Amazon RDS PostgreSQL 17.11 Instance:**
   - Provisioned and available in AWS VPC.
   - Security group allows inbound PostgreSQL traffic (port `5432`) from your runner machine or EC2 instance.
   - Database `interview_prep_db` created.

2. **Python Environment:**
   - Python 3.10+ with `psycopg2-binary`:
     ```bash
     pip install psycopg2-binary
     ```

3. **Target Connection String:**
   - Set the `DATABASE_URL` environment variable:
     ```bash
     # Linux / macOS / Bash
     export DATABASE_URL="postgresql://<db_user>:<db_password>@<rds_endpoint>:5432/interview_prep_db?sslmode=require"

     # Windows PowerShell
     $env:DATABASE_URL="postgresql://<db_user>:<db_password>@<rds_endpoint>:5432/interview_prep_db?sslmode=require"
     ```

---

## 3. Step-by-Step Execution Guide

### Step 1: Pre-Migration Dry-Run (No Database Writes)
Validate all JSON backup files, data schemas, and manifest counts without writing to the database:
```bash
python interview-app/scripts/import_json_to_rds.py --backup-dir backups/ --dry-run
```
Expected output:
```
[INFO] Validated 11 backup files containing 26910 total records. Count matches manifest.
[INFO] Dry-run validation completed successfully in 0.42 seconds.
```

### Step 2: Initialize RDS Schema
Apply the canonical schema to the RDS database using `psql`:
```bash
psql "$DATABASE_URL" -f interview-app/migrations/rds/001_schema.sql
```
*Note: If using PowerShell:*
```powershell
Get-Content interview-app/migrations/rds/001_schema.sql | psql $env:DATABASE_URL
```

### Step 3: Execute Transactional Data Import
Import all 26,910 records in dependency order into RDS:
```bash
python interview-app/scripts/import_json_to_rds.py --backup-dir backups/ --batch-size 500
```
Expected output:
```
[INFO] Beginning transactional import of 11 tables...
[INFO]   user_profiles                imported     13 records in  0.02s
[INFO]   question_bank_questions      imported   1081 records in  0.45s
[INFO]   question_bank_qnum_aliases   imported   2493 records in  0.38s
[INFO]   leetcode_problems            imported   4017 records in  0.82s
[INFO]   leetcode_approaches          imported   3305 records in  0.58s
[INFO]   leetcode_code_solutions      imported  15747 records in  2.15s
[INFO]   course_lessons               imported     77 records in  0.10s
[INFO]   user_progress                imported     43 records in  0.02s
[INFO]   practice_history             imported     94 records in  0.03s
[INFO]   user_comments                imported     20 records in  0.02s
[INFO]   learning_track_progress      imported     20 records in  0.02s
[INFO] All 11 tables successfully committed.
```

### Step 4: Run Verification Suite
Verify table existence, row counts, constraints, foreign keys, and sample data:
```bash
python interview-app/scripts/verify_rds_migration.py --backup-dir backups/
```
Expected output:
```
[INFO] [1/5] Checking table existence in public schema...
[INFO]   PASSED: All 11 expected tables exist.
[INFO] [2/5] Checking row counts against manifest...
[INFO]   PASSED: All 11 tables match manifest counts exactly (26910 total rows).
[INFO] [3/5] Checking primary key constraints...
[INFO]   PASSED: All 11 tables have valid primary keys.
[INFO] [4/5] Checking foreign key integrity and orphan references...
[INFO]   PASSED: Zero foreign-key orphan rows found across all relationships.
[INFO] [5/5] Checking data sampling and JSONB/Array parsing...
[INFO]   PASSED: Data types, arrays, and JSONB structures verified.
[INFO] Database verification PASSED with 100% parity.
```

---

## 4. Idempotency, Retry, and Recovery Behavior

- **Conflict Protection (`ON CONFLICT DO NOTHING`):**
  The importer uses primary key conflict clauses. If a network interruption occurs midway or the script is re-run, previously inserted rows are preserved, avoiding duplicate-key failures.
- **Transactional Rollback:**
  Each execution runs inside an explicit transaction (`with conn:`). Any unhandled database exception immediately triggers `ROLLBACK`, leaving the database clean.
- **Disaster Recovery / Full Clean Restart:**
  To start fresh before production traffic is routed:
  ```sql
  DROP SCHEMA public CASCADE;
  CREATE SCHEMA public;
  GRANT ALL ON SCHEMA public TO postgres;
  GRANT ALL ON SCHEMA public TO public;
  ```
  Then re-run Step 2 (`001_schema.sql`) followed by Step 3 (`import_json_to_rds.py`).
