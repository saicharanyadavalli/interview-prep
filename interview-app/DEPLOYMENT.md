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
                                 │
                     Port 80 (HTTP) / 443 (HTTPS)
                                 ▼
                     ┌───────────────────────┐
                     │  Nginx Reverse Proxy  │ (Host System Service)
                     └───────────┬───────────┘
                                 │
               ┌─────────────────┴─────────────────┐
               │ /                                 │ /api/backend/
               ▼                                   ▼
      ┌───────────────────┐               ┌───────────────────┐
      │ Next.js Frontend  │               │  FastAPI Backend  │
      │ (127.0.0.1:3000)  │               │ (127.0.0.1:8000)  │
      └─────────┬─────────┘               └─────────┬─────────┘
                │                                   │
                │ Client Auth                       │ Server-Side APIs
                ▼                                   ▼
         Supabase Cloud                      ┌──────┴──────┐
        (Auth & Database)                    ▼             ▼
                                       Google Gemini   Cloudinary
                                            (AI)        (Media)
```

- **Next.js Frontend:** Port `3000` bound exclusively to host loopback `127.0.0.1`.
- **FastAPI Backend:** Port `8000` bound exclusively to host loopback `127.0.0.1`.
- **Nginx Reverse Proxy:** Public ports `80` (HTTP) and `443` (HTTPS), terminating external connections and proxying traffic to loopback containers.
- **Internal Network:** Docker bridge network `interview-prep-network` connects Next.js to FastAPI (`http://backend:8000`).

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
   - *Note:* Do not provision an AWS RDS instance or NAT Gateway in this phase; Supabase Cloud serves as the external database.

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
4. Attach permission policy: **`AmazonSSMManagedInstanceCore`** (AWS-managed).
   - *Security rule:* Do not attach `AdministratorAccess` or unnecessary permissions.
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

# ── 2. Supabase Cloud (Database & Authentication) ───────────
# ⚠️ Verify project is ACTIVE (unpaused) in Supabase dashboard
SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
SUPABASE_ANON_KEY=eyJ...
# ⚠️ SECRET: Server-side only (never expose to frontend)
SUPABASE_SERVICE_KEY=eyJ...

# ── 3. Google OAuth & Cloudinary ────────────────────────────
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_cloudinary_key
CLOUDINARY_API_SECRET=your_cloudinary_secret

# ── 4. Host Networking & CORS ───────────────────────────────
# Set to your EC2 Public IP for initial testing (e.g. http://13.200.50.25)
FRONTEND_URL=http://<EC2_PUBLIC_IP>
ALLOWED_ORIGINS=http://<EC2_PUBLIC_IP>,http://localhost:3000,http://127.0.0.1:3000

# ── 5. Frontend Build Variables ─────────────────────────────
NEXT_PUBLIC_API_BASE_URL=/api/backend
NEXT_PUBLIC_SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_DISABLE_AUTH=false

# ── 6. Worker Tuning (m7i-flex.large: 2 vCPUs) ──────────────
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

## 5. Supabase & Authentication Limitations

1. **Supabase Inactivity Blocker:**
   - Preflight audits identified that Supabase project `armfnjzilchguppytyvm` is currently paused (`INACTIVE`).
   - Before database operations will succeed, log in to the [Supabase Dashboard](https://supabase.com/dashboard) and click **Restore Project**.
2. **Plain HTTP / Raw IP Limitations:**
   - Initial testing over `http://<EC2_PUBLIC_IP>` is intended only for non-sensitive smoke tests.
   - Do **NOT** enter real passwords over unencrypted HTTP.
   - **Google OAuth / Magic Links:** Google Cloud Console and modern browsers reject OAuth redirects over raw IP HTTP (`http://<ip>/auth/callback`). Use email/password authentication during initial IP testing.
3. **OAuth Implementation Detail:**
   - The OAuth PKCE exchange handler is implemented in `interview-app/frontend/src/app/auth/callback/route.ts` at route `/auth/callback`.
   - When configuring custom domains with SSL, register `https://<yourdomain>/auth/callback` in both Google Cloud Console and the Supabase Authentication URL configuration.

---

## 6. Dynamic Public IP, Costs & Operational Safety

1. **Dynamic Public IP Address Changes:**
   - An EC2 instance with auto-assigned public IP receives a **new IPv4 address** each time it is stopped and started.
   - If the IP changes:
     1. Update `.env`: set `FRONTEND_URL=http://<NEW_IP>` and `ALLOWED_ORIGINS=http://<NEW_IP>,...`.
     2. Rebuild the frontend: `docker compose build frontend && docker compose up -d`.
     3. Restart the backend: `docker compose restart backend`.
2. **Billing & Compute Costs:**
   - A running EC2 instance incurs compute charges continuously, regardless of traffic volume.
   - **Stopping the instance** stops EC2 compute billing, but the website becomes unavailable.
   - Attached EBS storage (30 GiB `gp3`) incurs storage charges continuously while retained.
   - Please confirm current regional AWS pricing in `ap-south-2` and verify active trial credits in the AWS Billing Console.
3. **Production SSL Setup (Let's Encrypt):**
   - Once a custom domain DNS A-record points to the EC2 Public IP:
     ```bash
     sudo apt install -y certbot python3-certbot-nginx
     sudo certbot --nginx -d yourdomain.com
     ```
