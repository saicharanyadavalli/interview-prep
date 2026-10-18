# Cloudinary Asset and Reference Migration Inventory

> **Migration:** Cloudinary to Amazon S3 + CloudFront  
> **Repository:** `saicharanyadavalli/interview-prep`  
> **Branch:** `feature/cloudinary-s3-migration`  
> **AWS Region:** `ap-south-2` (Hyderabad)  
> **S3 Bucket:** `interview-prep-assets-808431466075-ap-south-2`  
> **CloudFront Origin:** `${ASSET_BASE_URL}` (e.g. `https://d123456abcdef8.cloudfront.net`)  

---

## 1. Executive Summary

This document provides the definitive, comprehensive inventory of all Cloudinary dependencies across the `interview-prep` codebase. Every metric reported herein was derived through exhaustive static codebase scanning (excluding `.git`, `node_modules`, `.next`, and virtual environments).

### Key Metrics Scoreboard

| Metric | Count | Details and Scope |
| :--- | :---: | :--- |
| **Total Repository Files Scanned** | **229** | Clean source files across backend, frontend, scripts, migrations, and docs |
| **Files with Cloudinary References** | **47** | 29 files with delivery URLs + 18 files with SDK/env/docs/config references |
| **Total Cloudinary Text Occurrences** | **599** | Total line matches of case-insensitive string `cloudinary` |
| **Total Cloudinary URL References** | **509** | Raw embedded Cloudinary URL instances across markup, code, and fixtures |
| **Distinct Unique Cloudinary URLs** | **508** | Distinct normalized URL strings discovered |
| **Distinct Underlying Asset Files** | **507** | Physical unique assets (distinguishing identical assets across protocols/variants) |

### Understanding the Metric Deltas

1. **Total URL References (509) vs. Distinct Unique URLs (508) - Delta = 1:**
   - In `frontend/system-design/lessons/step-19.html`, the URL `https://res.cloudinary.com/asdf12235464/image/upload/v1776888549/interview-assistant/system-design/19/figure-8-location-service-OYEBRJD3.svg` is embedded **twice**:
     - Line 216: Embedded as diagram for *Figure 8 Location service*
     - Line 348: Reused as diagram for *Figure 14 User location database*
   - Both instances point to the identical Cloudinary resource.

2. **Distinct Unique URLs (508) vs. Distinct Asset Files (507) - Delta = 1:**
   - In `backend/tests/conftest.py`, lines 449 and 450 reference the **exact same underlying mock asset** (`avatar.png`) under two different protocol schemes:
     - Line 449: `https://res.cloudinary.com/demo/image/upload/avatar.png` (`secure_url`)
     - Line 450: `http://res.cloudinary.com/demo/image/upload/avatar.png` (`url`)
   - These represent 2 unique URLs, but map to 1 underlying asset file (`avatar.png`).
   - All 506 assets in cloud `asdf12235464` represent strictly distinct individual files with zero filename collisions across chapters.

---

## 2. Cloud Identifier Investigation: `asdf12235464` vs. `demo`

A critical investigation was conducted into the two Cloudinary cloud names detected in the repository:

| Cloud Identifier | Role in Codebase | Total Occurrences | Unique URLs | Distinct Assets | File Locations | Action Required |
| :--- | :--- | :---: | :---: | :---: | :--- | :--- |
| **`asdf12235464`** | **Production Tenant** | **507** | **506** | **506** | 28 System Design HTML lessons (`step-02.html` to `step-29.html`), `.env`, `backend/.env` | Migrate all 506 static assets to S3 and rewrite HTML references to CloudFront. Remove cloud credentials from env files. |
| **`demo`** | **Test Mock Placeholder** | **2** | **2** | **1** | `backend/tests/conftest.py` (lines 449, 450) | Update mock fixture in `conftest.py` to return S3/CloudFront URLs; no physical assets need downloading. |

### Detailed Findings on `asdf12235464`
- This is the active Cloudinary production account owned by the application.
- All 506 unique production assets follow the rigid naming path:
  `https://res.cloudinary.com/asdf12235464/image/upload/v{version}/interview-assistant/system-design/{chapter_number}/{filename}`
- No query parameters (`?`) or dynamic Cloudinary transformations (e.g. `c_fill`, `w_500`, `q_auto`, `f_auto`) are applied to any of these URLs.
- Every asset has an immutable version tag (`v177688...`) followed by `interview-assistant/system-design/{chapter_num}/`.

### Detailed Findings on `demo`
- Cloudinary provides `demo` as a public demo cloud for sample code and documentation.
- In this repository, `demo` is **never used in production** or user-facing templates.
- It is confined exclusively to `backend/tests/conftest.py` in the `mock_cloudinary` fixture:
  ```python
  @pytest.fixture
  def mock_cloudinary() -> Generator[MagicMock, None, None]:
      with patch("routes.profile.cloudinary.uploader.upload") as upload_mock:
          upload_mock.return_value = {
              "secure_url": "https://res.cloudinary.com/demo/image/upload/avatar.png",
              "url": "http://res.cloudinary.com/demo/image/upload/avatar.png",
          }
          yield upload_mock
  ```
- When Agent 3 migrates profile avatar uploads to S3 storage, this test fixture must be adapted to return CloudFront URLs (e.g. `${ASSET_BASE_URL}/avatars/...`).

---

## 3. Asset Type Breakdown

All discovered assets fall into standard web raster and vector image formats. Below is the precise breakdown across all discovered assets:

| Asset Type | Extension | Unique URLs | Total Occurrences | Distinct Asset Files | Share of Assets | Typical Content / Description |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **SVG** | `.svg` | **339** | **340** | **339** | **66.9%** | Architectural system diagrams, network flows, cluster topologies |
| **PNG** | `.png` | **123** | **123** | **122** | **24.1%** | Charts, complex graphics, tables, mock test avatar |
| **WebP** | `.webp` | **34** | **34** | **34** | **6.7%** | High-density figures, screenshots, optimized modern illustrations |
| **JPG / JPEG** | `.jpg` | **12** | **12** | **12** | **2.4%** | Real-world photos, screenshots of external websites (Yelp, Google Maps) |
| **GIF** | `.gif` | **0** | **0** | **0** | **0.0%** | *Zero GIF assets detected across the entire codebase* |
| **TOTAL** | - | **508** | **509** | **507** | **100.0%** | |

> [!NOTE]
> 100% of the 506 production assets are vector SVG, WebP, PNG, or JPG. There are no animated GIFs, videos, or raw PDFs hosted in Cloudinary.

---

## 4. File-by-File Inventory

### A. System Design Lesson Files (28 Files Containing URLs)

The 507 Cloudinary URL occurrences in lessons are distributed across 28 distinct HTML files in `frontend/system-design/lessons/`:

| File Path | Chapter | URL Occurrences | Unique URLs | SVG | PNG | WebP | JPG | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `frontend/system-design/lessons/step-02.html` | Chapter 02 | 23 | 23 | 8 | 9 | 6 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-03.html` | Chapter 03 | 1 | 1 | 1 | 0 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-04.html` | Chapter 04 | 4 | 4 | 0 | 3 | 1 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-05.html` | Chapter 05 | 9 | 9 | 9 | 0 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-06.html` | Chapter 06 | 15 | 15 | 15 | 0 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-07.html` | Chapter 07 | 21 | 21 | 21 | 0 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-08.html` | Chapter 08 | 7 | 7 | 7 | 0 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-09.html` | Chapter 09 | 8 | 8 | 6 | 2 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-10.html` | Chapter 10 | 10 | 10 | 9 | 1 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-11.html` | Chapter 11 | 14 | 14 | 5 | 7 | 2 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-12.html` | Chapter 12 | 7 | 7 | 3 | 4 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-13.html` | Chapter 13 | 19 | 19 | 4 | 12 | 3 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-14.html` | Chapter 14 | 15 | 15 | 11 | 3 | 0 | 1 | All URLs unique |
| `frontend/system-design/lessons/step-15.html` | Chapter 15 | 28 | 28 | 17 | 8 | 3 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-16.html` | Chapter 16 | 15 | 15 | 10 | 5 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-17.html` | Chapter 17 | 25 | 25 | 4 | 12 | 3 | 6 | All URLs unique |
| `frontend/system-design/lessons/step-18.html` | Chapter 18 | 15 | 15 | 9 | 4 | 2 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-19.html` | Chapter 19 | 22 | 21 | 14 | 3 | 0 | 5 | Contains duplicate URL reference (Fig 8 & 14) |
| `frontend/system-design/lessons/step-20.html` | Chapter 20 | 37 | 37 | 35 | 2 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-21.html` | Chapter 21 | 23 | 23 | 17 | 6 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-22.html` | Chapter 22 | 30 | 30 | 28 | 2 | 0 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-23.html` | Chapter 23 | 20 | 20 | 15 | 4 | 1 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-24.html` | Chapter 24 | 17 | 17 | 4 | 11 | 2 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-25.html` | Chapter 25 | 28 | 28 | 23 | 2 | 3 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-26.html` | Chapter 26 | 26 | 26 | 10 | 10 | 6 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-27.html` | Chapter 27 | 13 | 13 | 7 | 5 | 1 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-28.html` | Chapter 28 | 30 | 30 | 29 | 0 | 1 | 0 | All URLs unique |
| `frontend/system-design/lessons/step-29.html` | Chapter 29 | 25 | 25 | 19 | 6 | 0 | 0 | All URLs unique |
| **Subtotal (Lessons)** | **28 Chapters** | **507** | **506** | **340** | **121** | **34** | **12** | **506 distinct static assets to migrate** |

#### Note on Missing Chapters in Lessons
- `step-01.html` (Chapter 1: *Join the Community*): Contains only text and an invite link to Discord. **Zero image tags, zero Cloudinary URLs.**
- `step-30.html` (Chapter 30: *The Learning Continues*): Contains reading lists and links to external tech blogs. **Zero image tags, zero Cloudinary URLs.**
- Consequently, lessons range from `step-02.html` through `step-29.html`.

### B. Test Files Containing Cloudinary URLs (1 File)

| File Path | Line Numbers | URL Occurrences | Unique URLs | Asset Type | Purpose |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `backend/tests/conftest.py` | Lines 449, 450 | 2 | 2 | `.png` | Test fixture mock response for `cloudinary.uploader.upload()` |

### C. Non-URL Repository Files with Cloudinary References (18 Files)

Beyond raw delivery URLs, Cloudinary is referenced across configuration files, SDK imports, tests, and documentation:

| Category | File Path | Line(s) | Description of Cloudinary Usage |
| :--- | :--- | :---: | :--- |
| **Backend Application** | `backend/routes/profile.py` | 5, 17, 18, 44-59, 278, 344-365 | Imports `cloudinary` & `cloudinary.uploader`. Implements `_configure_cloudinary()` reading env vars. Calls `upload()` with fallback to inline base64 data URI. |
| **Backend Dependencies** | `backend/requirements.txt` | 18, 28, 166, 203 | Declares `cloudinary==1.45.0` dependency. Must be replaced with `boto3`. |
| **Backend Configuration** | `backend/.env` | 11-16 | Defines live credentials: `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_AVATAR_FOLDER`, `CLOUDINARY_SYSTEM_DESIGN_FOLDER`. |
| **Backend Configuration** | `backend/.env.example` | 51-60 | Example template for Cloudinary environment variables. |
| **Docker Compose** | `backend/docker-compose.yml` | 35-39 | Injects `CLOUDINARY_*` environment variables into FastAPI backend container. |
| **Docker Ignore** | `backend/.dockerignore` | 52-54 | Ignores `.cloudinary_upload_cache.json` and `cloudinary-map.json`. |
| **Root Configuration** | `.env` | 14-19 | Root-level environment file with Cloudinary secrets. |
| **Root Configuration** | `.env.example` | 43-48 | Root-level example environment variables template. |
| **Root Compose** | `docker-compose.yml` | 27-29 | Root docker-compose passing `CLOUDINARY_*` environment variables. |
| **Frontend Next.js** | `frontend/next.config.ts` | 6 | Configures `images.remotePatterns` for `res.cloudinary.com`. |
| **Frontend Component** | `frontend/src/components/UserAvatar.tsx` | 22 | Code comment noting support for Cloudinary avatar URLs. |
| **Integration Tests** | `backend/tests/integration/test_profile_endpoints.py` | 110-129, 191-196 | Unit/integration tests asserting `storage == 'cloudinary'` and testing error fallback. |
| **Integration Tests** | `backend/tests/integration/test_main_endpoints.py` | 72 | Mocks `routes.profile.cloudinary.uploader.upload`. |
| **Test Suite** | `backend/tests/conftest.py` | 429, 445-452 | Defines `mock_cloudinary` pytest fixture. |
| **Abuse Resilience Tests** | `backend/test_abuse_resilience.py` | 39, 44 | Mocks `routes.profile.cloudinary.uploader.upload`. |
| **Documentation** | `README.md` | 14, 126-130, 229 | Mentions Cloudinary for avatars/assets and lists env vars. |
| **Documentation** | `DEPLOYMENT.md` | 34, 202-206 | Architecture diagram references Cloudinary; lists production env vars. |
| **Documentation** | `AWS-EC2-DEPLOYMENT-GUIDE.md` | 22 | Lists Cloudinary CDN under architecture media components. |
| **Contracts** | `docs/migrations/migration-contracts.md` | 6, 30, 31, 41, 42 | Migration task assignment contract. |

---

## 5. Deterministic Source-to-S3 Object Key Convention

To ensure seamless, repeatable, and collision-free asset resolution across S3 and CloudFront, the following object key schemas are defined:

### A. System Design Lesson Assets
- **Cloudinary Source Pattern:**  
  `https://res.cloudinary.com/asdf12235464/image/upload/v{version}/interview-assistant/system-design/{chapter_number}/{filename_slug}.{ext}`
- **Deterministic S3 Object Key:**  
  `system-design/{chapter_number}/{filename_slug}.{ext}`
- **Target S3 URI:**  
  `s3://interview-prep-assets-808431466075-ap-south-2/system-design/{chapter_number}/{filename_slug}.{ext}`
- **CloudFront Delivery URL:**  
  `${ASSET_BASE_URL}/system-design/{chapter_number}/{filename_slug}.{ext}`

#### Naming Guarantees:
1. **Chapter Number Consistency:** Preserves the exact 2-digit zero-padded numbers for chapters 02 through 16 (`system-design/02/`, `system-design/16/`) and unpadded numbers for chapters 17 through 29 (`system-design/17/`, `system-design/29/`). This matches the existing folder structure in Cloudinary and the HTML file numbering (`step-02.html` to `step-29.html`).
2. **Zero Collision Risk:** All 506 production filenames are completely unique even when stripped of chapter paths. Namespacing them under `system-design/{chapter}/` guarantees zero collision.
3. **Simplicity of HTML Rewriting:** Rewriting URLs requires simply replacing `https://res.cloudinary.com/asdf12235464/image/upload/v[0-9]+/interview-assistant/` with `${ASSET_BASE_URL}/`.

### B. User Avatar Assets
- **Legacy Cloudinary Pattern:**  
  `https://res.cloudinary.com/asdf12235464/image/upload/v{version}/interview-prep/avatars/{user_id}/avatar.{ext}`
- **New S3 Key Convention:**  
  `avatars/{user_id}/{unique_uuid}.{ext}`
- **Target S3 URI:**  
  `s3://interview-prep-assets-808431466075-ap-south-2/avatars/{user_id}/{unique_uuid}.{ext}`
- **CloudFront Delivery URL:**  
  `${ASSET_BASE_URL}/avatars/{user_id}/{unique_uuid}.{ext}`

#### Avatar Design Guarantees:
1. **Cache Busting via UUID:** Including a `{unique_uuid}` in the S3 key guarantees that subsequent avatar updates by the same user do not serve stale cached images from CloudFront or browser caches.
2. **Tenant and User Isolation:** The `{user_id}` prefix organizes user assets logically and enables granular S3 IAM / lifecycle policies.
3. **Reconciled Avatars:** Avatars migrated from existing RDS records follow `avatars/{user_id}/{filename}` where `{filename}` is deterministically extracted from the legacy Cloudinary URL.

### C. Other Static Assets and Test Fixtures
- **Pattern:** `static/{category}/{filename_slug}.{ext}`
- **Test Mock Placeholder:** `avatars/demo/avatar.png` or `static/test/avatar.png`

---

## 6. Unresolved Items, Nuances, and Cross-Agent Action Items

### Item 1: Database-Persisted Avatars (Agent 5 Hand-off)
- **Issue:** The repository code and HTML files do NOT contain user avatars; avatars are uploaded dynamically by users and persisted in RDS PostgreSQL (`user_profiles.avatar_url`).
- **Action:** Agent 5's tool (`scripts/reconcile_db_avatars.py`) must inspect the live database, identify Cloudinary URLs, download and migrate them to S3, and update `user_profiles.avatar_url` to the CloudFront URL. External OAuth avatars (Google, GitHub) and inline base64 data URIs must be preserved.

### Item 2: Discrepancy in Cloudinary Avatar Folder Env Var
- **Issue:** In `.env` and `backend/.env`, the variable is named `CLOUDINARY_AVATAR_FOLDER` (singular), whereas in `backend/routes/profile.py` (line 49), it queried `CLOUDINARY_AVATARS_FOLDER` (plural). The fallback default `"interview-prep/avatars"` was used in practice.
- **Action:** Agent 3 and Agent 6 should deprecate both environment variables in favor of standardized S3 variables: `S3_ASSETS_BUCKET` and `ASSET_BASE_URL`.

### Item 3: Duplicate Diagram URL in `step-19.html` (Agent 4 and Agent 6 Hand-off)
- **Issue:** URL `...figure-8-location-service-OYEBRJD3.svg` appears on line 216 (Figure 8) and line 348 (Figure 14).
- **Action:** Migration and URL replacement scripts must be idempotent so that replacing all occurrences in `step-19.html` updates both image tags without duplicate uploads or partial replacement.

### Item 4: Next.js Image Optimization Domains (Agent 6 Hand-off)
- **Issue:** `frontend/next.config.ts` currently whitelists only `res.cloudinary.com` under `images.remotePatterns`.
- **Action:** Agent 6 must update `frontend/next.config.ts` to include the CloudFront distribution domain (`*.cloudfront.net` or the specific domain configured in `ASSET_BASE_URL`).

### Item 5: Deprecation and Cleanup of Cloudinary Packages
- **Issue:** `cloudinary==1.45.0` is currently listed in `backend/requirements.txt`.
- **Action:** Once Agent 3 replaces Cloudinary with `boto3` in `s3_storage_service.py` and all tests pass, `cloudinary` must be removed from `requirements.txt` to eliminate dead dependencies.

---

## 7. Deliverable Artifacts Index

1. **`docs/migrations/cloudinary-inventory.json`:**  
   Machine-readable catalog of all **508** discovered unique URLs with full metadata:
   - `url`: Full original Cloudinary URL
   - `source_file`: Relative path to source file where found
   - `cloud_name`: `asdf12235464` or `demo`
   - `asset_type`: `svg`, `png`, `webp`, or `jpg`
   - `proposed_s3_key`: Deterministic target S3 key

2. **`docs/migrations/cloudinary-inventory.md`:**  
   This comprehensive report and operational analysis.
