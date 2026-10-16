# Interview Prep — AWS EC2 Deployment Guide

This guide documents the procedures for building, configuring, and running the Next.js frontend and FastAPI backend on an AWS EC2 instance using Docker and Docker Compose.

---

## 1. Prerequisites on EC2 (Ubuntu / Amazon Linux 2023)

Install Docker Engine and the Docker Compose plugin:

```bash
# Ubuntu 22.04 / 24.04 LTS
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow ec2-user/ubuntu to run docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

---

## 2. Environment Configuration

Create `.env` in the `interview-app/` directory (or use AWS Systems Manager Parameter Store / Secrets Manager):

```env
# AI Service
GEMINI_API_KEY=your_gemini_api_key

# Supabase Auth & Database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key

# Google OAuth
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com

# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# URLs
FRONTEND_URL=https://your-domain.com
NEXT_PUBLIC_API_BASE_URL=https://your-domain.com/api/backend
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_supabase_anon_key
```

---

## 3. Build & Run with Docker Compose

From `interview-app/`:

```bash
# Build both images
docker compose build

# Start services in background
docker compose up -d

# Verify health status
docker compose ps

# Check logs
docker compose logs -f backend
docker compose logs -f frontend
```

---

## 4. Health Verification

Test the local endpoints on EC2:

```bash
# Test backend health
curl http://127.0.0.1:8000/health

# Test frontend health
curl -I http://127.0.0.1:3000/
```

---

## 5. Reverse Proxy (Nginx)

Example reverse proxy block to terminate SSL and route frontend and backend traffic:

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # Backend API routes
    location /api/backend/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend Next.js Application
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
