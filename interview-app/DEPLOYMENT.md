# Interview Prep — Canonical AWS EC2 Production Deployment Guide
## Full-Stack Deployment: Next.js Frontend + FastAPI Backend + Nginx Reverse Proxy

**Target Region:** `ap-south-2` (AWS Hyderabad)  
**Target Instance:** `m7i-flex.large` (2 vCPUs, 8 GiB RAM) with 30 GiB `gp3` storage  
**Operating System:** Ubuntu Server 24.04 LTS (64-bit x86)  
**Repository Branch:** [`aws-migration`](https://github.com/saicharanyadavalli/interview-prep/tree/aws-migration)  

---

## 1. Architecture Overview

```
                                    Internet Client (Browser)
                                     │                     │
                       Port 80/443   │                     │ HTTPS CDN Requests
                       (App Traffic) │                     │ (*.cloudfront.net)
                                     ▼                     ▼
                         ┌───────────────────────┐   ┌───────────────────────┐
                         │  Nginx Reverse Proxy  │   │ Amazon CloudFront CDN │
                         │ (Host System Service) │   │ (OAC Secured Delivery)│
                         └───────────┬───────────┘   └───────────┬───────────┘
                                     │                           │
                   ┌─────────────────┴─────────────────┐         │ S3 Read (OAC)
                   │ /                                 │         ▼
                   ▼                                   ▼   ┌───────────────────┐
          ┌───────────────────┐               ┌────────┴───┴──────┐   │ Amazon S3 Bucket  │
          │ Next.js Frontend  │               │  FastAPI Backend  ├──►│ (Private Storage) │
          │ (127.0.0.1:3000)  │               │ (127.0.0.1:8000)  │   │ avatars & diagrams│
          └─────────┬─────────┘               └─────────┬─────────┘   └───────────────────┘
                    │                                   │ (IAM Role Auth)
                    │ Client Auth                       │ Server-Side APIs
                    ▼                                   ▼
             Supabase Cloud                      ┌──────┴──────┐
             (User Auth Only)                    ▼             ▼
                                           Google Gemini   RDS Postgres
                                                (AI)        (App Data)
```

- **Next.js Frontend:** Port `3000` bound exclusively to host loopback `127.0.0.1`.
- **FastAPI Backend:** Port `8000` bound exclusively to host loopback `127.0.0.1`.
- **Nginx Reverse Proxy:** Public ports `80` (HTTP) and `443` (HTTPS), terminating external connections and proxying traffic to loopback containers.
- **Internal Network:** Docker bridge network `interview-prep-network` connects Next.js to FastAPI (`http://backend:8000`).
- **Amazon S3 & CloudFront CDN:** Static media (system design diagrams) and user uploads (profile avatars) are stored in private Amazon S3 and delivered globally via Amazon CloudFront with Origin Access Control (OAC). The FastAPI backend writes to S3 via instance IAM role without long-lived static credentials.

---

## 2. AWS Prerequisite Console Checklist (Before Launching EC2)

Complete these manual checks in the AWS Management Console in the **Hyderabad (`ap-south-2`)** region:

### A. Networking Verification
1. **VPC:** Confirm that `interview-prep-vpc` exists.
2. **Public Subnet:** Confirm `interview-prep-public-a` exists.
   - Go to **VPC > Subnets > interview-prep-public-a**.
   - Under **Actions > Edit subnet settings**, verify that **Enable auto-assign public IPv4 address** is checked.
3. **Public Route Table:**
   - Under **Subnets > interview-prep-public-a > Route table**, inspect the routes:
     - `10.0.0.0/16` (or VPC CIDR) &rarr; `local`
     - `0.0.0.0/0` &rarr; `interview-prep-igw` (Target: Internet Gateway)
   - Ensure the subnet association is explicitly set to this route table.
4. **Database Subnets (Isolation Check):**
   - Verify that your database subnets (e.g., `interview-prep-db-a`, `interview-prep-db-b`) are associated with the **private route table**.
   - Confirm the private route table has **NO** route to `0.0.0.0/0` &rarr; `interview-prep-igw`.
   - Amazon RDS PostgreSQL (`interview_prep_db`) is isolated in these private database subnets. EC2 connects securely to RDS via the VPC internal network. Supabase is retained strictly for authentication/JWT identity.

### B. Security Group Configuration (`interview-prep-app-sg`)
Reuse the existing security group `interview-prep-app-sg`. Ensure the **Inbound rules** match:

| Type | Protocol | Port Range | Source | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP** | TCP | `80` | `0.0.0.0/0` | Public Web Access (Initial IP Testing) |
| **HTTPS** | TCP | `443` | `0.0.0.0/0` | Secure Web Access (After Domain Setup) |
| **SSH** *(Optional)* | TCP | `22` | `<Your-IP>/32` | Emergency SSH (Never allow `0.0.0.0/0`) |

> [!CAUTION]
> - **NEVER** expose ports `3000` or `8000` in the AWS Security Group.
> - **NEVER** allow SSH (port 22) from `0.0.0.0/0`.
> - Once AWS Systems Manager Session Manager access is confirmed, port 22 can be removed entirely.

### C. IAM Role Setup (`InterviewPrepEC2Role`)
1. Go to **IAM Console > Roles > Create role**.
2. Select **Trusted entity type**: `AWS service`.
3. Select **Use case**: `EC2`.
4. Attach permission policies:
   - **`AmazonSSMManagedInstanceCore`** (AWS-managed): Enables Session Manager access without open inbound SSH ports.
   - **`InterviewPrepEC2S3Policy`** (Customer-managed / Inline): Grants least-privilege access to the private assets S3 bucket:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "ScopedS3BucketObjectAccess",
           "Effect": "Allow",
           "Action": [
             "s3:PutObject",
             "s3:GetObject",
             "s3:DeleteObject"
           ],
           "Resource": "arn:aws:s3:::interview-prep-assets-808431466075-ap-south-2/*"
         },
         {
           "Sid": "ScopedS3BucketListAccess",
           "Effect": "Allow",
           "Action": [
             "s3:ListBucket"
           ],
           "Resource": "arn:aws:s3:::interview-prep-assets-808431466075-ap-south-2"
         }
       ]
     }
     ```
   - **`InterviewPrepSecretsPolicy`** (Customer-managed / Inline): Scoped access to RDS PostgreSQL credentials in AWS Secrets Manager:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "ResolveRDSSecretValue",
           "Effect": "Allow",
           "Action": "secretsmanager:GetSecretValue",
           "Resource": "arn:aws:secretsmanager:ap-south-2:808431466075:secret:interview-prep/rds/app-*"
         }
       ]
     }
     ```
   > [!IMPORTANT]
   > - *Security rule:* Do not attach `AdministratorAccess` or broad wildcard policies.
   > - *Automated Provisioning:* If deploying with CloudFormation (`infrastructure/cloudformation/assets-s3-cloudfront.yaml`), setting parameter `AttachPolicyToRole='true'` automatically generates and attaches `BackendEC2S3Policy` to `InterviewPrepEC2Role`.
5. Set Role Name: **`InterviewPrepEC2Role`** and click **Create role**.

---

## 3. EC2 Instance Launch Specification

Launch the instance using **EC2 > Launch instances** with these parameters:

- **Name:** `interview-prep-app-server`
- **Application and OS Images (AMI):** **Ubuntu Server 24.04 LTS (HVM)**, SSD Volume Type, 64-bit (x86).
- **Instance Type:** **`m7i-flex.large`** (2 vCPUs, 8 GiB RAM).
- **Key Pair:** Select your existing key pair if you have retained the `.pem` file. If using Session Manager exclusively, you may select *"Proceed without a key pair"*.
- **Network Settings (Edit):**
  - **VPC:** `interview-prep-vpc`
  - **Subnet:** `interview-prep-public-a`
  - **Auto-assign public IP:** `Enable`
  - **Firewall (security groups):** Select existing security group &rarr; **`interview-prep-app-sg`**.
- **Configure Storage:**
  - 1 volume, **30 GiB**, `gp3` (General Purpose SSD, baseline 3000 IOPS / 125 MB/s).
- **Advanced Details:**
  - **IAM instance profile:** Select **`InterviewPrepEC2Role`**.
  - **Metadata version (IMDSv2):** `V2 only (token required)`.
  - **Metadata response hop limit:** `1`.
  - **User data:** *Leave completely blank.*

Click **Launch instance**.

---

## 4. Server Setup & Deployment Runbook

### Step 1: Connect via AWS Systems Manager Session Manager
In the AWS EC2 Console, select the instance and click **Connect > Session Manager > Connect**.

Alternatively, via AWS CLI:
```bash
aws ssm start-session --target i-0123456789abcdef0 --region ap-south-2
```

> [!NOTE]
> **Shell Account Context:** Session Manager opens a shell as `ssm-user` in `/usr/bin` or `/`.
> Switch to the standard `ubuntu` user to ensure consistent home directories, file paths, and environment isolation:
> ```bash
> sudo su - ubuntu
> cd /home/ubuntu
> ```

---

### Step 2: System Update & Package Installation
Execute as `ubuntu`:
```bash
# 1. Update Ubuntu packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg lsb-release git nginx

# 2. Add Docker's official GPG key & repository for Ubuntu 24.04
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update

# 3. Install Docker Engine, CLI, and Docker Compose plugin
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Enable non-root Docker execution
sudo usermod -aG docker ubuntu
sudo usermod -aG docker ssm-user
sudo systemctl enable --now docker nginx

# 5. Refresh group membership in current session
newgrp docker
```

---

### Step 3: Clone Repository (`aws-migration` branch)
```bash
cd /home/ubuntu
git clone -b aws-migration https://github.com/saicharanyadavalli/interview-prep.git
cd /home/ubuntu/interview-prep/interview-app
```

---

### Step 4: Configure Environment Variables
Create the production `.env` file from the verified template:
```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Populate the following values:
```env
# ── 1. Google Gemini AI Service ─────────────────────────────
GEMINI_API_KEY=AIzaSy...

# ── 2. Supabase Cloud (Authentication Only) ───────────────────
# Retained strictly for user auth, session tokens, and identity management.
SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
SUPABASE_ANON_KEY=eyJ...
# ⚠️ SECRET: Server-side only (never expose to frontend)
SUPABASE_SERVICE_KEY=eyJ...

# ── 2b. Amazon RDS PostgreSQL & AWS Secrets Manager ───────────
# Authoritative application datastore for all application data tables.
AWS_REGION=ap-south-2
RDS_SECRET_NAME=interview-prep/rds/app
RDS_POOL_MIN=2
RDS_POOL_MAX=10

# ── 3. Google OAuth ─────────────────────────────────────────
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com

# ── 3b. AWS S3 & Amazon CloudFront (Static Assets & Avatars) ──
# Authoritative S3 bucket and CloudFront CDN for profile avatars and system design diagrams.
# On EC2, instance accesses S3 via InterviewPrepEC2Role (zero static credentials).
S3_ASSETS_BUCKET=interview-prep-assets-808431466075-ap-south-2
S3_ASSETS_REGION=ap-south-2
ASSET_BASE_URL=https://<your-distribution-id>.cloudfront.net

# Optional asset folder prefixes (defaults shown)
S3_AVATAR_PREFIX=avatars
S3_SYSTEM_DESIGN_PREFIX=system-design

# ── 3c. Cloudinary (Media Storage - DEPRECATED) ───────────────
# Replaced by Amazon S3 + CloudFront CDN. Retained temporarily for backward compatibility.
# CLOUDINARY_CLOUD_NAME=your_cloud_name
# CLOUDINARY_API_KEY=your_cloudinary_key
# CLOUDINARY_API_SECRET=your_cloudinary_secret

# ── 4. Host Networking & CORS ───────────────────────────────
# Set to your EC2 Public IP for initial staging (e.g. http://16.113.92.222)
FRONTEND_URL=http://<EC2_PUBLIC_IP>
ALLOWED_ORIGINS=http://<EC2_PUBLIC_IP>,http://localhost:3000,http://127.0.0.1:3000

# ── 5. Authentication Redirect URLs (AWS EC2 Canonical) ─────
AUTH_REDIRECT_URL=http://<EC2_PUBLIC_IP>/auth/callback?next=/dashboard
NEXT_PUBLIC_AUTH_REDIRECT_URL=http://<EC2_PUBLIC_IP>/auth/callback?next=/dashboard
NEXT_PUBLIC_APP_URL=http://<EC2_PUBLIC_IP>

# ── 6. Frontend Build Variables ─────────────────────────────
NEXT_PUBLIC_API_BASE_URL=/api/backend
NEXT_PUBLIC_SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_DISABLE_AUTH=false

# ── 7. Worker Tuning (m7i-flex.large: 2 vCPUs) ──────────────
UVICORN_WORKERS=2
```

> [!IMPORTANT]
> **Build-Time vs. Runtime Variables:**
> - `NEXT_PUBLIC_*` variables are inlined into client JavaScript bundles when the frontend container is built (`docker compose build frontend`).
> - If you change `FRONTEND_URL`, `NEXT_PUBLIC_API_BASE_URL`, or `NEXT_PUBLIC_SUPABASE_*`, you **MUST** rebuild:
>   `docker compose build frontend && docker compose up -d`
> - Backend runtime variables (`GEMINI_API_KEY`, `SUPABASE_SERVICE_KEY`, etc.) take effect upon restarting:
>   `docker compose restart backend`

---

### Step 5: Configure Nginx Reverse Proxy
Install the verified Nginx configuration:
```bash
sudo cp nginx/interview-app.conf /etc/nginx/sites-available/interview-app
sudo ln -sf /etc/nginx/sites-available/interview-app /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Verify syntax
sudo nginx -t

# Reload Nginx
sudo systemctl restart nginx
```

> [!NOTE]
> **Alternative Reverse Proxy (Caddy):**
> A standalone `interview-app/nginx/Caddyfile` is provided for zero-config HTTP/IP testing as an alternative.
> Do **NOT** run Nginx and Caddy simultaneously on port 80/443. Nginx is the canonical choice.

---

### Step 6: Build & Start Containers
```bash
# Build and start services
docker compose up -d --build

# Verify container status
docker compose ps
```

Expected output:
```
NAME                      IMAGE                     COMMAND                  SERVICE   CREATED          STATUS                    PORTS
interview-prep-backend    interview-app-backend     "/bin/sh -c 'uvicorn…"   backend   15 seconds ago   Up 14 seconds (healthy)   127.0.0.1:8000->8000/tcp
interview-prep-frontend   interview-app-frontend    "docker-entrypoint.s…"   frontend  10 seconds ago   Up 9 seconds (healthy)    127.0.0.1:3000->3000/tcp
```

---

### Step 7: Verification & Health Checks

Run these GET requests on the EC2 host:

1. **Backend Health Check (Direct Loopback):**
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   ```
   **Expected Response:**
   ```json
   {"status":"ok","checks":{"gemini_key_set":true,"supabase_url_set":true,"supabase_key_set":true}}
   ```
   *(Note: This check validates environment-variable injection; see Section 5 regarding live database connectivity).*

2. **Nginx Reverse Proxy & Backend Route:**
   ```bash
   curl -fsS http://127.0.0.1/health
   curl -fsS http://127.0.0.1/api/backend/health
   ```

3. **Frontend Application Root:**
   ```bash
   curl -fsS http://127.0.0.1/ | head -n 25
   ```
   *Expected: HTML response containing `<!DOCTYPE html>` and Next.js meta tags.*

4. **Courses Public API via Nginx:**
   ```bash
   curl -fsS http://127.0.0.1/api/backend/courses
   ```

---

## 5. Supabase, OAuth & Reverse Proxy Architecture

1. **Supabase Scope & Project Status:**
   - Supabase Cloud is retained **strictly for Authentication**, user identity, and session tokens.
   - All application tables and user data reside authoritatively in **Amazon RDS PostgreSQL**.
   - If Supabase project `armfnjzilchguppytyvm` is paused (`INACTIVE`), log in to the [Supabase Dashboard](https://supabase.com/dashboard) and click **Restore Project** before starting auth flows.

2. **Google OAuth & Redirect URI Configuration (Exact Mapping):**
   - **Google Cloud Console (`APIs & Services > Credentials > OAuth 2.0 Client IDs`):**
     - **Authorized JavaScript origins:**
       - `http://16.113.92.222` (for staging IP testing)
       - `https://yourdomain.com` (for production)
     - **Authorized redirect URIs:**
       - `https://<project-ref>.supabase.co/auth/v1/callback` (e.g. `https://armfnjzilchguppytyvm.supabase.co/auth/v1/callback`)
     - ⚠️ **CRITICAL:** Do NOT put `http://16.113.92.222/auth/callback` in Google Cloud Console. Google must redirect to Supabase's auth handler, which validates the exchange and then redirects to the application callback below.

   - **Supabase Dashboard (`Authentication > URL Configuration`):**
     - **Site URL:**
       - `http://16.113.92.222` (staging) or `https://yourdomain.com` (production)
     - **Redirect URLs:**
       - `http://16.113.92.222/**`
       - `http://16.113.92.222/auth/callback`
       - `https://yourdomain.com/auth/callback` (production)
       - `http://localhost:3000/**` (local dev)
     - Supabase checks the `redirectTo` parameter against this allowlist. If the IP or domain is not present, Supabase rejects the redirect and falls back to Site URL.

3. **Production HTTPS & Custom Domain Mandate:**
   - Raw IP HTTP (`http://<ip>/auth/callback`) is suitable only for staging smoke tests.
   - For production, a custom domain and HTTPS are **mandatory**. Modern browsers enforce `SameSite` cookie security and reject insecure cookie storage across cross-site OAuth redirects.

4. **Nginx Buffer Tuning & 502 Bad Gateway Mitigation:**
   - Next.js `@supabase/ssr` returns multiple large `Set-Cookie` headers during OAuth session exchange (access token, refresh token, provider token).
   - Standard Nginx proxy buffer defaults (4k/8k) can overflow, triggering `502 Bad Gateway` with error:
     `upstream sent too big header while reading response header from upstream`.
   - The verified Nginx configuration in `nginx/interview-app.conf` includes:
     ```nginx
     proxy_buffer_size 128k;
     proxy_buffers 4 256k;
     proxy_busy_buffers_size 256k;
     large_client_header_buffers 4 32k;
     ```
   - **Diagnostic Check:** If a 502 Bad Gateway is encountered, inspect `/var/log/nginx/error.log`:
     - If the log reports `upstream sent too big header`, verify the buffer directives are loaded.
     - If the log reports `Connection refused` or `Connection reset by peer`, the Next.js or FastAPI container exited or failed to start. Check `docker compose logs frontend` or `docker compose logs backend`.

---

## 6. Dynamic Public IP, Costs & Operational Safety

1. **Dynamic Public IP Address Changes:**
   - An EC2 instance with auto-assigned public IP receives a **new IPv4 address** each time it is stopped and started.
   - If the IP changes:
     1. Update `.env`: set `FRONTEND_URL=http://<NEW_IP>`, `AUTH_REDIRECT_URL=http://<NEW_IP>/auth/callback?next=/dashboard`, and `ALLOWED_ORIGINS=http://<NEW_IP>,...`.
     2. Update Supabase Dashboard > Authentication > URL Configuration with the new IP.
     3. Rebuild the frontend: `docker compose build frontend && docker compose up -d`.
     4. Restart the backend: `docker compose restart backend`.
2. **Billing & Compute Costs:**
   - A running EC2 instance incurs compute charges continuously, regardless of traffic volume.
   - Stopping the instance stops EC2 compute billing, but EBS storage (30 GiB `gp3`) incurs storage charges continuously while retained.
3. **Production SSL Setup (Let's Encrypt):**
   - Once a custom domain DNS A-record points to the EC2 Public IP:
     ```bash
     sudo apt install -y certbot python3-certbot-nginx
     sudo certbot --nginx -d yourdomain.com
     ```

---

## 7. Staging Zero-Downtime Deployment Runbook

Follow this step-by-step sequence when deploying updates to staging:

### Phase 1: Database Migration (Additive & Non-destructive)
Run migration `002_course_lessons_tasks.sql` against Amazon RDS PostgreSQL:
```bash
# Connect to RDS (via bastion or EC2 instance using credentials from Secrets Manager)
psql -h <RDS_ENDPOINT> -U <DB_USER> -d interview_prep_db -f migrations/rds/002_course_lessons_tasks.sql
```
*Note: This migration adds `tasks JSONB NOT NULL DEFAULT '[]'::jsonb` and `slug TEXT` with indexes. It is completely additive and backwards compatible.*

### Phase 2: Validate & Seed SQL Course Lessons
Seed course lessons and interactive tasks into RDS:
```bash
# 1. Validate data integrity without database connection
python scripts/load_courses.py --validate-only

# 2. Dry-run to preview database operations without writing
python scripts/load_courses.py --dry-run

# 3. Authoritative upsert into RDS
python scripts/load_courses.py
```

### Phase 3: Read-Only Course Reconciliation
Verify data parity between reference catalog and RDS:
```bash
python scripts/reconcile_courses.py
```
*Expected: 21/21 lessons matched, tasks checksum matches, 0 missing or mismatched.*

### Phase 4: Container Build & Service Restart
Rebuild and deploy containers:
```bash
docker compose build
docker compose up -d
docker compose ps
```

### Phase 5: Verification & Smoke Testing
```bash
# 1. Backend health
curl -fsS http://127.0.0.1:8000/health

# 2. Nginx proxy route
curl -fsS http://127.0.0.1/api/backend/health

# 3. Authoritative lesson tasks endpoint
curl -fsS http://127.0.0.1/api/backend/courses/sql-course/lessons/select_queries_introduction | grep "tasks"

# 4. Frontend root
curl -fsS http://127.0.0.1/ | head -n 20
```

---

## 8. Static Media & Asset Delivery via Amazon CloudFront and S3

The application delivers system design lesson diagrams and user profile avatars using a private Amazon S3 bucket paired with Amazon CloudFront CDN.

### A. Security & Storage Architecture

```
                      Browser / Client
                             │
            HTTPS Request    │ (*.cloudfront.net)
                             ▼
               ┌───────────────────────────┐
               │   Amazon CloudFront CDN   │ (Origin Access Control)
               └─────────────┬─────────────┘
                             │
            AWS SigV4 Signed │ (s3:GetObject)
                             ▼
               ┌───────────────────────────┐
               │    Amazon S3 Bucket       │ (Block Public Access: ENABLED)
               │ interview-prep-assets-... │ (SSE-AES256, TLS 1.2+ Only)
               └─────────────▲─────────────┘
                             │
            Instance Profile │ s3:PutObject / s3:DeleteObject
            (IMDSv2 Assumed) │ (No static AWS keys in code/env)
                             │
               ┌─────────────┴─────────────┐
               │  FastAPI Backend on EC2   │
               │ (InterviewPrepEC2Role)    │
               └───────────────────────────┘
```

1. **Private S3 Bucket (`interview-prep-assets-808431466075-ap-south-2`):**
   - **Public Access Block:** All four block settings (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`, `RestrictPublicBuckets`) are active.
   - **Encryption:** Server-Side Encryption with Amazon S3 managed keys (`AES256` / SSE-S3) and S3 Bucket Keys enabled.
   - **Bucket Policy:** Denies all insecure requests (`aws:SecureTransport: 'false'`) and grants read access exclusively to the CloudFront distribution service principal (`cloudfront.amazonaws.com`) via Origin Access Control (OAC). Direct internet access to the S3 bucket is rejected with HTTP 403 Forbidden.

2. **CloudFront CDN Distribution:**
   - **Protocol Policy:** Redirects all HTTP traffic to HTTPS (`redirect-to-https`).
   - **Caching Policy:** Uses AWS Managed `CachingOptimized` (`658327ea-f89d-4fab-a63d-7e88639e58f6`) for high cache-hit ratios and minimal origin latency.
   - **CORS Headers:** Uses AWS Managed `SimpleCORS` (`60669652-455b-4ae9-85a4-c4c02393f86c`) ensuring secure cross-origin asset rendering.

### B. EC2 IAM Role Configuration (`InterviewPrepEC2Role`)

The FastAPI backend runs on the EC2 instance and utilizes the default AWS credential provider chain via `boto3`. No static AWS credentials (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`) are stored in `.env` or application code.

The instance profile `InterviewPrepEC2Role` requires the following scoped permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ScopedS3BucketObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::interview-prep-assets-808431466075-ap-south-2/*"
    },
    {
      "Sid": "ScopedS3BucketListAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::interview-prep-assets-808431466075-ap-south-2"
    }
  ]
}
```

### C. CloudFormation Infrastructure Provisioning

The infrastructure can be deployed or updated in a single CloudFormation command:

```bash
aws cloudformation deploy \
  --template-file infrastructure/cloudformation/assets-s3-cloudfront.yaml \
  --stack-name interview-prep-assets \
  --parameter-overrides \
      Environment=production \
      BucketName=interview-prep-assets-808431466075-ap-south-2 \
      EC2RoleName=InterviewPrepEC2Role \
      AttachPolicyToRole=true \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-south-2
```

To retrieve the generated CloudFront domain and Base URL:
```bash
aws cloudformation describe-stacks \
  --stack-name interview-prep-assets \
  --region ap-south-2 \
  --query "Stacks[0].Outputs[?OutputKey=='AssetBaseUrl'].OutputValue" \
  --output text
```

### D. Frontend Next.js Configuration

The Next.js frontend (`frontend/next.config.ts`) is configured with authorized remote image hostnames:

```typescript
const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "*.cloudfront.net" },
      { protocol: "https", hostname: "d*.cloudfront.net" },
      { protocol: "https", hostname: "res.cloudinary.com" },
      { protocol: "https", hostname: "lh3.googleusercontent.com" },
      { protocol: "https", hostname: "avatars.githubusercontent.com" },
      { protocol: "https", hostname: "ui-avatars.com" },
    ],
  },
  // ...
};
```

- **CloudFront CDN:** Matches any CloudFront distribution hostname (`*.cloudfront.net` or `d*.cloudfront.net`) over HTTPS.
- **OAuth Providers:** Preserves Google (`lh3.googleusercontent.com`) and GitHub (`avatars.githubusercontent.com`) avatar URLs.
- **Deterministic Avatar Fallbacks:** The `UserAvatar` component renders initials SVG data URIs deterministically whenever an avatar image is absent, empty, or fails to load.
- **Migration Backward-Compatibility:** Retains `res.cloudinary.com` during the transition phase.

### E. Asset Verification & Health Checks

Run these diagnostic checks on the EC2 instance or local development shell:

1. **Verify Direct S3 Access is Blocked (Expected 403 Forbidden):**
   ```bash
   curl -I https://interview-prep-assets-808431466075-ap-south-2.s3.ap-south-2.amazonaws.com/avatars/test.png
   # Expected: HTTP/1.1 403 Forbidden
   ```

2. **Verify CloudFront CDN Delivery (HTTPS with CORS):**
   ```bash
   curl -I https://<your-distribution-id>.cloudfront.net/system-design/01/system-architecture.png
   # Expected: HTTP/2 200 OK (or 404 if file does not exist yet)
   # Must include x-cache header (e.g. "Hit from cloudfront" or "Miss from cloudfront")
   ```

3. **Verify Avatar Upload Endpoint via Backend:**
   ```bash
   curl -X POST http://127.0.0.1:8000/profile/avatar/upload \
     -H "Authorization: Bearer <VALID_JWT_TOKEN>" \
     -F "file=@test-avatar.jpg"
   # Expected JSON: {"avatar_url": "https://<distribution-id>.cloudfront.net/avatars/<user-id>/<uuid>.jpg"}
   ```
