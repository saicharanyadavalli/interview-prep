# Interview Prep — AWS EC2 Production Deployment Guide

This guide details the exact steps for deploying the Next.js frontend and FastAPI backend on an AWS EC2 instance in **`ap-south-2` (Hyderabad)** or any other AWS region.

---

## 1. Architecture Overview

```
                      Internet Client
                             │ (Port 80 HTTP or 443 HTTPS)
                             ▼
                    ┌─────────────────┐
                    │  Nginx / Caddy  │ (Host Reverse Proxy)
                    └────────┬────────┘
                             │
            ┌────────────────┴────────────────┐
            ▼ /                               ▼ /api/backend/
  ┌───────────────────┐             ┌───────────────────┐
  │ Next.js Frontend  │             │  FastAPI Backend  │
  │ (127.0.0.1:3000)  │             │ (127.0.0.1:8000)  │
  └───────────────────┘             └─────────┬─────────┘
                                              │
                         ┌────────────────────┼────────────────────┐
                         ▼                    ▼                    ▼
                  Supabase Cloud       Google Gemini        Cloudinary
                  (Auth & Postgres)        (AI)              (Media)
```

---

## 2. Server Prerequisites (Ubuntu 22.04 / 24.04 LTS)

Connect to your EC2 instance via SSH and run:

```bash
# 1. Update system packages
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release git nginx

# 2. Install Docker Engine & Docker Compose plugin
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Enable non-sudo Docker access
sudo usermod -aG docker $USER
newgrp docker
```

---

## 3. Clone Repository & Switch to Migration Branch

```bash
cd /home/ubuntu
git clone https://github.com/saicharanyadavalli/interview-prep.git
cd interview-prep
git checkout aws-migration
```

---

## 4. Environment Variables Setup

Create a `.env` file in the `interview-app/` directory:

```bash
cd interview-app
nano .env
```

Paste your configuration:

```env
# ── AI Service ─────────────────────────────────────────────
GEMINI_API_KEY=your_gemini_api_key_here

# ── Supabase (Database & Auth) ─────────────────────────────
# ⚠️ Ensure your Supabase project is ACTIVE (unpaused)
SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key_here
SUPABASE_SERVICE_KEY=your_supabase_service_role_key_here

# ── Google OAuth & Cloudinary ──────────────────────────────
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com
CLOUDINARY_CLOUD_NAME=your_cloudinary_cloud_name
CLOUDINARY_API_KEY=your_cloudinary_api_key
CLOUDINARY_API_SECRET=your_cloudinary_api_secret

# ── Host / Domain Settings ─────────────────────────────────
# For temporary IP testing (e.g. EC2 Public IP: 13.200.50.25):
FRONTEND_URL=http://13.200.50.25
ALLOWED_ORIGINS=http://13.200.50.25,http://localhost:3000,http://127.0.0.1:3000
NEXT_PUBLIC_API_BASE_URL=/api/backend
NEXT_PUBLIC_SUPABASE_URL=https://armfnjzilchguppytyvm.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key_here
```

---

## 5. Reverse Proxy Setup

### Option A: Testing via EC2 Public IP (HTTP Port 80)
Copy the provided Nginx configuration:

```bash
sudo cp nginx/interview-app.conf /etc/nginx/conf.d/
sudo nginx -t
sudo systemctl restart nginx
```

> **Limitations of HTTP/IP Testing**:
> - **Google OAuth**: Google Cloud Console requires HTTPS redirect URIs (except for `localhost`). OAuth logins will reject raw IP HTTP redirects (`http://<ip>/auth/callback`). Use email/password sign-in during initial IP testing, or add an HTTPS domain.
> - **Cookies**: Browsers apply strict third-party cookie restrictions without HTTPS.

### Option B: Production with Domain & Free SSL (Let's Encrypt)
Once DNS points to your EC2 Public IP:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## 6. Build and Launch Containers

From `interview-app/`:

```bash
# Build frontend and backend containers
docker compose build

# Start services detached
docker compose up -d

# Verify container health
docker compose ps
```

---

## 7. Verification Checklist

```bash
# 1. Backend direct healthcheck
curl -f http://127.0.0.1:8000/health

# 2. Reverse proxy routing check
curl -I http://localhost/health
curl -I http://localhost/api/backend/health

# 3. Frontend direct healthcheck
curl -I http://localhost/
```

---

## 8. Important Architectural Blockers to Keep in Mind
1. **Supabase Project Status**: The Supabase project `armfnjzilchguppytyvm` was detected as paused/inactive during preflight audit. Restore it in the Supabase web dashboard before validating database requests.
2. **Google OAuth Callbacks**: If using Google Sign-In, ensure `http://<domain>/auth/callback` is registered in both the Google Cloud Console and the Supabase Authentication URL Configuration.
