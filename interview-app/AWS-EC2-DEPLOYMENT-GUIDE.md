# Complete AWS EC2 Production Deployment Guide

## Interview Practice Platform - Backend Deployment

---

## Table of Contents

- [Section 1: Architecture Analysis](#section-1-architecture-analysis)
- [Section 2: Missing Files](#section-2-missing-files)
- [Section 3: Docker Deployment Files](#section-3-docker-deployment-files)
- [Section 4: Non-Docker Deployment (Systemd)](#section-4-non-docker-deployment-systemd)
- [Section 5: EC2 Commands](#section-5-ec2-commands)
- [Section 6: Nginx Configuration](#section-6-nginx-configuration)
- [Section 7: SSL Setup](#section-7-ssl-setup)
- [Section 8: CI/CD Setup](#section-8-cicd-setup)
- [Section 9: Verification Checklist](#section-9-verification-checklist)
- [Section 10: Troubleshooting Guide](#section-10-troubleshooting-guide)
- [Section 11: Monitoring &amp; Logging Setup](#section-11-monitoring--logging-setup)
- [Section 12: Connecting Backend with Supabase](#section-12-connecting-backend-with-supabase)
- [Section 13: Update Vercel Frontend API URL](#section-13-update-vercel-frontend-api-url)
- [Section 14: Quick Reference](#section-14-quick-reference)

---

## Section 1: Architecture Analysis

### 1.1 Application Overview

| Component | Technology | Current Hosting | Target |
| --------- | ---------------------------- | --------------- | ------------------------- |
| Frontend | Next.js 16 (App Router, React 19, Tailwind CSS v4) | Vercel | Vercel (existing) |
| Backend   | FastAPI (Python 3.11+)       | Render          | AWS EC2                   |
| Database  | PostgreSQL (Supabase)        | Supabase Cloud  | Supabase Cloud (existing) |
| Auth      | Supabase Auth + Google OAuth | Supabase Cloud  | Supabase Cloud (existing) |
| AI        | Google Gemini API            | Cloud           | Cloud (existing)          |
| Storage   | Cloudinary                   | Cloud           | Cloud (existing)          |

### 1.2 Backend Architecture

```
interview-app/backend/
├── main.py                    # Entry point - FastAPI app
├── requirements.txt           # Python dependencies
├── models/
│   └── schemas.py            # Pydantic models
├── routes/                   # API endpoints (8 routers)
│   ├── auth.py               # JWT validation
│   ├── questions.py          # Question CRUD
│   ├── assistant.py          # AI doubt assistant
│   ├── progress.py           # Progress tracking
│   ├── revisit.py            # Revisit queue
│   ├── comments.py           # User comments
│   ├── profile.py            # Profile management
│   └── system_design.py      # Learning tracks
└── services/                 # Business logic
    ├── supabase_client.py    # Database client
    ├── gemini_service.py     # AI integration
    ├── questions_service.py  # Question loading
    └── system_design_course.py
```

### 1.3 Dependencies Analysis

```python
# Core dependencies
fastapi>=0.115.0,<1.0.0            # Web framework
uvicorn[standard]>=0.30.0,<1.0.0   # ASGI server with hot reload
supabase>=2.0.0,<3.0.0             # Database client (includes httpx, pyjwt)

# Optional but used
google-generativeai>=0.8.0,<1.0.0  # Gemini AI
cloudinary>=1.42.0,<2.0.0           # Image storage
python-dotenv>=1.0.0,<2.0.0         # Environment loader
python-multipart>=0.0.9,<1.0.0      # File upload support
```

### 1.4 Environment Variables Required

| Variable                            | Required | Description               | Source                                   |
| ----------------------------------- | -------- | ------------------------- | ---------------------------------------- |
| `GEMINI_API_KEY`                  | Yes      | Google Gemini AI API key  | Google AI Studio                         |
| `SUPABASE_URL`                    | Yes      | Supabase project URL      | Supabase Dashboard                       |
| `SUPABASE_ANON_KEY`               | Yes      | Public anonymous key      | Supabase Dashboard                       |
| `SUPABASE_SERVICE_KEY`            | Yes      | Service role key (secret) | Supabase Dashboard                       |
| `GOOGLE_CLIENT_ID`                | Yes      | Google OAuth client ID    | Google Cloud Console                     |
| `CLOUDINARY_CLOUD_NAME`           | Yes      | Cloudinary cloud name     | Cloudinary Dashboard                     |
| `CLOUDINARY_API_KEY`              | Yes      | Cloudinary API key        | Cloudinary Dashboard                     |
| `CLOUDINARY_API_SECRET`           | Yes      | Cloudinary API secret     | Cloudinary Dashboard                     |
| `CLOUDINARY_AVATAR_FOLDER`        | No       | Avatar upload folder      | Default:`interview-prep/avatars`       |
| `CLOUDINARY_SYSTEM_DESIGN_FOLDER` | No       | System design folder      | Default:`interview-prep/system-design` |

### 1.5 Startup Command

```bash
# Development
cd interview-app/backend
uvicorn main:app --reload --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

## Section 2: Missing Files

The following files are **NOT present** in the repository and need to be created:

| File                             | Status     | Purpose                       |
| -------------------------------- | ---------- | ----------------------------- |
| `Dockerfile`                   | ❌ Missing | Container image definition    |
| `docker-compose.yml`           | ❌ Missing | Multi-container orchestration |
| `.dockerignore`                | ❌ Missing | Build context exclusions      |
| `.env.example`                 | ❌ Missing | Environment template          |
| `nginx/nginx.conf`             | ❌ Missing | Reverse proxy configuration   |
| `.github/workflows/deploy.yml` | ❌ Missing | CI/CD pipeline                |
| `scripts/healthcheck.sh`       | ❌ Missing | Health monitoring script      |

---

## Section 3: Docker Deployment Files

### 3.1 Dockerfile

Create file: `interview-app/backend/Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1

# ============================================
# Interview Practice Platform - Production Dockerfile
# Multi-stage build for optimized image size
# ============================================

# --- Stage 1: Builder ---
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Production Runtime ---
FROM python:3.11-slim-bookworm AS runtime

# Security: Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy application code
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Labels for transparency
LABEL org.opencontainers.image.title="Interview Practice Platform"
LABEL org.opencontainers.image.description="FastAPI backend for interview practice"
LABEL org.opencontainers.image.version="1.0.0"

# Production startup command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

### 3.2 .dockerignore

Create file: `interview-app/backend/.dockerignore`

```dockerignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
dist/
build/
*.egg

# Virtual environments
venv/
.venv/
env/
.env.local

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# Git
.git/
.gitignore

# Docker
Dockerfile
docker-compose.yml
.dockerignore

# Tests
tests/
test_*.py
*_test.py
.pytest_cache/
.coverage
htmlcov/

# Documentation
*.md
docs/

# Misc
.DS_Store
*.log
*.tmp
.env

# Cloudinary cache
.cloudinary_upload_cache.json
cloudinary-map.json
```

### 3.3 docker-compose.yml

Create file: `interview-app/backend/docker-compose.yml`

```yaml
# ============================================
# Interview Practice Platform - Docker Compose
# Production deployment configuration
# ============================================

version: "3.9"

services:
  # ==========================================
  # FastAPI Backend Application
  # ==========================================
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    container_name: interview-api
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      # Application
      - PYTHONUNBUFFERED=1
      - PYTHONDONTWRITEBYTECODE=1
      # Workers (adjust based on CPU cores)
      - UVICORN_WORKERS=${UVICORN_WORKERS:-2}
      # Secrets from .env file
      - GEMINI_API_KEY=${GEMINI_API_KEY:?GEMINI_API_KEY is required}
      - SUPABASE_URL=${SUPABASE_URL:?SUPABASE_URL is required}
      - SUPABASE_ANON_KEY=${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is required}
      - SUPABASE_SERVICE_KEY=${SUPABASE_SERVICE_KEY:?SUPABASE_SERVICE_KEY is required}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}
      - CLOUDINARY_CLOUD_NAME=${CLOUDINARY_CLOUD_NAME:-}
      - CLOUDINARY_API_KEY=${CLOUDINARY_API_KEY:-}
      - CLOUDINARY_API_SECRET=${CLOUDINARY_API_SECRET:-}
      - CLOUDINARY_AVATAR_FOLDER=${CLOUDINARY_AVATAR_FOLDER:-interview-prep/avatars}
      - CLOUDINARY_SYSTEM_DESIGN_FOLDER=${CLOUDINARY_SYSTEM_DESIGN_FOLDER:-interview-prep/system-design}
    volumes:
      # Read-only mount for any static assets if needed
      - ./assets:/app/assets:ro
    networks:
      - backend-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "1G"
        reservations:
          cpus: "0.5"
          memory: "256M"

  # ==========================================
  # Prometheus Monitoring (Optional)
  # ==========================================
  prometheus:
    image: prom/prometheus:v2.48.0
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/usr/share/prometheus/console_libraries'
      - '--web.console.templates=/usr/share/prometheus/consoles'
      - '--storage.tsdb.retention.time=15d'
      - '--web.enable-lifecycle'
    profiles:
      - monitoring
    networks:
      - backend-network

  # ==========================================
  # Grafana Dashboard (Optional)
  # ==========================================
  grafana:
    image: grafana/grafana:10.2.2
    container_name: grafana
    restart: unless-stopped
    ports:
      - "127.0.0.1:3001:3000"
    environment:
      - GF_SECURITY_ADMIN_USER=${GF_ADMIN_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASSWORD:-admin123}
      - GF_SERVER_ROOT_URL=http://localhost:3001
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    profiles:
      - monitoring
    depends_on:
      - prometheus
    networks:
      - backend-network

networks:
  backend-network:
    driver: bridge
    name: interview-network

volumes:
  prometheus-data:
    name: prometheus-data
  grafana-data:
    name: grafana-data
```

### 3.4 .env.example

Create file: `interview-app/backend/.env.example`

```bash
# ============================================
# Interview Practice Platform - Environment Variables
# Copy to .env and fill in your values
# ============================================

# ==========================================
# REQUIRED - AI Service
# ==========================================
# Google Gemini API Key (from Google AI Studio)
# Get from: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# ==========================================
# REQUIRED - Supabase Database
# ==========================================
# Supabase Project URL (from Project Settings > API)
SUPABASE_URL=https://your-project-ref.supabase.co

# Public anon key (safe for frontend - from Project Settings > API)
SUPABASE_ANON_KEY=your_supabase_anon_key_here

# Service role key (SECRET - from Project Settings > API)
# ⚠️ NEVER expose this in frontend code
SUPABASE_SERVICE_KEY=your_supabase_service_role_key_here

# ==========================================
# REQUIRED - Google OAuth
# ==========================================
# Google OAuth Client ID (from Google Cloud Console)
GOOGLE_CLIENT_ID=your_google_client_id.apps.googleusercontent.com

# ==========================================
# REQUIRED - Cloudinary (Image Storage)
# ==========================================
# Cloudinary credentials (from Cloudinary Dashboard)
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_cloudinary_api_key
CLOUDINARY_API_SECRET=your_cloudinary_api_secret

# Optional folder paths (defaults shown)
CLOUDINARY_AVATAR_FOLDER=interview-prep/avatars
CLOUDINARY_SYSTEM_DESIGN_FOLDER=interview-prep/system-design

# ==========================================
# OPTIONAL - Application Settings
# ==========================================
# Number of Uvicorn workers (default: 2)
# Recommended: (2 * CPU cores) + 1
UVICORN_WORKERS=2

# ==========================================
# OPTIONAL - Monitoring (if enabled)
# ==========================================
# Grafana admin credentials
GF_ADMIN_USER=admin
GF_ADMIN_PASSWORD=change_me_secure_password
```

---

## Section 4: Non-Docker Deployment (Systemd)

### 4.1 Systemd Service Unit

Create file: `/etc/systemd/system/interview-api.service`

```ini
[Unit]
Description=Interview Practice Platform - FastAPI Backend
After=network.target
Documentation=https://github.com/yourusername/interview-prep

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/interview-api/backend

# Environment
Environment="PATH=/opt/interview-api/venv/bin"
EnvironmentFile=/opt/interview-api/.env

# Executable
ExecStart=/opt/interview-api/venv/bin/uvicorn main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 2 \
    --forwarded-allow-ips='*' \
    --proxy-headers

# Graceful shutdown
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30

# Restart policy
Restart=always
RestartSec=5

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/interview-api/logs
ReadOnlyPaths=/opt/interview-api

# Limits
LimitNOFILE=65535
LimitNPROC=4096

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=interview-api

[Install]
WantedBy=multi-user.target
```

### 4.2 Setup Script for Non-Docker

Create file: `scripts/setup-systemd.sh`

```bash
#!/bin/bash
# ============================================
# Non-Docker Deployment Setup Script
# Run as root on the EC2 instance
# ============================================

set -euo pipefail

# Configuration
APP_USER="www-data"
APP_DIR="/opt/interview-api"
APP_REPO="https://github.com/yourusername/interview-prep.git"
PYTHON_VERSION="3.11"

echo "=== Interview Practice Platform - Non-Docker Setup ==="

# 1. Install Python
echo "[1/7] Installing Python ${PYTHON_VERSION}..."
apt update
apt install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev

# 2. Create application directory
echo "[2/7] Creating directories..."
mkdir -p ${APP_DIR}/{logs,assets}
chown -R ${APP_USER}:${APP_USER} ${APP_DIR}

# 3. Clone repository
echo "[3/7] Cloning repository..."
git clone ${APP_REPO} ${APP_DIR}/repo || true
cd ${APP_DIR}/repo/interview-app/backend

# 4. Create virtual environment
echo "[4/7] Creating virtual environment..."
python${PYTHON_VERSION} -m venv ${APP_DIR}/venv
source ${APP_DIR}/venv/bin/activate

# 5. Install dependencies
echo "[5/7] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 6. Copy environment file
echo "[6/7] Setting up environment..."
if [ -f "$HOME/.env" ]; then
    cp $HOME/.env ${APP_DIR}/.env
    chmod 600 ${APP_DIR}/.env
    chown ${APP_USER}:${APP_USER} ${APP_DIR}/.env
fi

# 7. Setup systemd service
echo "[7/7] Setting up systemd service..."
cp scripts/interview-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable interview-api
systemctl start interview-api

echo "=== Setup Complete ==="
echo "Check status: systemctl status interview-api"
echo "View logs: journalctl -u interview-api -f"
```

---

## Section 5: EC2 Commands (Fresh Ubuntu 24.04)

### 5.1 Initial Server Setup

```bash
# ============================================
# EC2 Ubuntu 24.04 - Initial Setup
# Run these commands after SSH-ing into your instance
# ============================================

# Update system packages
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y \
    curl wget git vim \
    ca-certificates \
    gnupg \
    software-properties-common \
    apt-transport-https \
    ufw fail2ban

# Set timezone
sudo timedatectl set-timezone UTC

# Create swap file (if instance has limited RAM)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 5.2 Install Docker

```bash
# ============================================
# Docker Installation - Ubuntu 24.04
# ============================================

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository
echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker
sudo systemctl enable --now docker

# Add current user to docker group
sudo usermod -aG docker $USER

# Verify installation
docker --version
docker compose version
```

### 5.3 Configure Firewall

```bash
# ============================================
# Firewall Configuration (UFW)
# ============================================

# Reset UFW
sudo ufw --force reset

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH (adjust port if different)
sudo ufw allow 22/tcp comment 'SSH'

# Allow HTTP/HTTPS
sudo ufw allow 80/tcp comment 'HTTP'
sudo ufw allow 443/tcp comment 'HTTPS'

# Allow from specific IPs only (optional - more secure)
# sudo ufw allow from YOUR_IP_ADDRESS to any port 22

# Enable UFW
sudo ufw --force enable

# Check status
sudo ufw status verbose
```

### 5.4 Install Nginx

```bash
# ============================================
# Nginx Installation
# ============================================

sudo apt install -y nginx

# Start and enable
sudo systemctl enable --now nginx

# Verify
nginx -v
```

### 5.5 Deploy Application

```bash
# ============================================
# Application Deployment
# ============================================

# Create application directory
sudo mkdir -p /opt/interview-api
sudo chown $USER:$USER /opt/interview-api

# Clone repository
cd /opt
git clone https://github.com/yourusername/interview-prep.git interview-api
cd interview-api/interview-app/backend

# Create .env file
nano .env  # Paste your environment variables

# OR use existing .env file
# scp your-local-.env user@ec2-instance:/opt/interview-api/backend/.env

# Build and start with Docker Compose
docker compose build
docker compose up -d

# Check status
docker compose ps
docker compose logs -f app
```

### 5.6 Configure Nginx Reverse Proxy

```bash
# ============================================
# Nginx Configuration
# ============================================

# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default

# Create application config
sudo tee /etc/nginx/sites-available/interview-api << 'EOF'
# ============================================
# Interview Practice Platform - Nginx Config
# ============================================

# Upstream - FastAPI backend
upstream fastapi_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

# HTTP - Redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name api.yourdomain.com;

    # Allow ACME challenges for Let's Encrypt
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/certbot;
        allow all;
    }

    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.yourdomain.com;

    # SSL Certificate (will be configured after certbot)
    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;

    # SSL Configuration
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_session_tickets off;

    # Modern SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # HSTS (uncomment after confirming HTTPS works)
    add_header Strict-Transport-Security "max-age=63072000" always;

    # Security Headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml+rss;

    # Logging
    access_log /var/log/nginx/interview-api-access.log;
    error_log /var/log/nginx/interview-api-error.log;

    # API Proxy
    location / {
        proxy_pass http://fastapi_backend;
        proxy_http_version 1.1;
      
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
      
        # WebSocket support (if needed)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
      
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
      
        # Buffer settings
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # Health check endpoint (no auth required)
    location /health {
        proxy_pass http://fastapi_backend/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        access_log off;
    }

    # Disable access to hidden files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }
}
EOF

# Enable site
sudo ln -sf /etc/nginx/sites-available/interview-api /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Create certbot directory (for SSL)
sudo mkdir -p /var/www/certbot
sudo chown www-data:www-data /var/www/certbot

# Reload Nginx (will fail due to missing SSL certs - this is expected)
sudo systemctl reload nginx || true
```

---

## Section 6: Nginx Configuration

### 6.1 Full Nginx Configuration

File: `/etc/nginx/nginx.conf`

```nginx
# ============================================
# Nginx Main Configuration
# Ubuntu 24.04 - Production Optimized
# ============================================

user www-data;
worker_processes auto;
pid /run/nginx.pid;
error_log /var/log/nginx/error.log;

include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 4096;
    multi_accept on;
    use epoll;
}

http {
    # Basic Settings
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    server_tokens off;

    # Increase buffer sizes for large headers (JWT tokens)
    client_header_buffer_size 16k;
    large_client_header_buffers 4 64k;

    # MIME types
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # Logging Format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct="$upstream_connect_time" '
                    'uht="$upstream_header_time" urt="$upstream_response_time"';

    access_log /var/log/nginx/access.log main;

    # Gzip Compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_disable "msie6";
    gzip_types text/plain text/css text/xml application/json application/javascript application/rss+xml application/atom+xml image/svg+xml;

    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;

    # Connection limit
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

    # Security headers map
    map $sent_http_content_type $cors_header {
        default "*";
        ~application/json "*";
        ~application/javascript "*";
    }

    # Include site configurations
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

### 6.2 Rate Limiting Configuration

File: `/etc/nginx/conf.d/rate-limit.conf`

```nginx
# ============================================
# Rate Limiting Configuration
# ============================================

# Define zones before using them
limit_req_zone $binary_remote_addr zone=general:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=api:10m rate=20r/s;
limit_req_zone $binary_remote_addr zone=auth:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=upload:10m rate=2r/m;
```

---

## Section 7: SSL Setup (Let's Encrypt)

### 7.1 Install Certbot

```bash
# ============================================
# Certbot Installation
# ============================================

sudo apt install -y certbot python3-certbot-nginx

# Stop Nginx temporarily (for standalone mode)
sudo systemctl stop nginx

# Get certificate (replace with your domain)
sudo certbot certonly --standalone \
    -d api.yourdomain.com \
    --email your-email@example.com \
    --agree-tos \
    --no-eff-email \
    --keep-until-expiring

# Start Nginx again
sudo systemctl start nginx

# Configure auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Test renewal
sudo certbot renew --dry-run
```

### 7.2 Alternative: Using Nginx Pjlugin

```bash
# Easier method using Nginx plugin
sudo certbot --nginx \
    -d api.yourdomain.com \
    --email your-email@example.com \
    --agree-tos \
    --no-eff-email \
    --redirect

# This automatically modifies your Nginx config
```

### 7.3 SSL Hardening

Add to your Nginx site config:

```nginx
# OCSP Stapling
ssl_stapling on;
ssl_stapling_verify on;
resolver 8.8.8.8 8.8.4.4 valid=300s;
resolver_timeout 5s;

# SSL Session
ssl_session_timeout 1d;
ssl_session_cache shared:SSL:50m;
ssl_session_tickets off;

# HSTS
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

# Additional headers
add_header Content-Security-Policy "default-src 'self';" always;
add_header Permissions-Policy "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=()" always;
```

---

## Section 8: CI/CD Setup (GitHub Actions)

### 8.1 Complete GitHub Actions Workflow

Create file: `.github/workflows/deploy.yml`

```yaml
# ============================================
# Interview Practice Platform - CI/CD Pipeline
# Deploys to AWS EC2 on push to main branch
# ============================================

name: Deploy to AWS EC2

on:
  push:
    branches:
      - main
      - master
    paths:
      - 'interview-app/backend/**'
      - '.github/workflows/deploy.yml'
  pull_request:
    branches:
      - main
      - master
    paths:
      - 'interview-app/backend/**'
  workflow_dispatch:
    inputs:
      environment:
        description: 'Deployment environment'
        required: true
        default: 'production'
        type: choice
        options:
          - production
          - staging

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}/interview-api

jobs:
  # ==========================================
  # Build and Test
  # ==========================================
  build:
    name: Build & Test
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}
  
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        working-directory: interview-app/backend
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Lint with flake8
        working-directory: interview-app/backend
        run: |
          pip install flake8
          flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
          flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
        continue-on-error: true

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Container Registry
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata for Docker
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=sha,prefix=
            type=ref,event=branch
            type=raw,value=latest,enable={{is_default_branch}}

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: ./interview-app/backend
          file: ./interview-app/backend/Dockerfile
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64

  # ==========================================
  # Deploy to Production
  # ==========================================
  deploy:
    name: Deploy to EC2
    needs: build
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/master'
    environment:
      name: production
      url: https://api.yourdomain.com
  
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Deploy to EC2
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.EC2_HOST }}
          username: ${{ secrets.EC2_USER }}
          key: ${{ secrets.EC2_SSH_KEY }}
          port: 22
          script: |
            set -e
          
            echo "=== Starting deployment ==="
            cd /opt/interview-api/interview-app/backend
          
            # Pull latest code
            git pull origin main
          
            # Pull latest Docker image (if using registry)
            # docker compose pull
          
            # Build new image
            docker compose build --no-cache
          
            # Stop old containers gracefully
            docker compose down --remove-orphans --timeout 30
          
            # Start new containers
            docker compose up -d
          
            # Wait for health check
            echo "Waiting for application to start..."
            sleep 10
          
            # Check if container is healthy
            if docker compose ps | grep -q "Up"; then
                echo "✅ Deployment successful!"
              
                # Show logs
                docker compose logs --tail=50 app
            else
                echo "❌ Deployment failed! Rolling back..."
                docker compose logs --tail=100 app
                exit 1
            fi
          
            # Clean up old images
            docker image prune -af --filter "until=24h"

      - name: Verify Deployment
        run: |
          echo "Waiting for application to be ready..."
          sleep 15
        
          # Health check
          response=$(curl -s -o /dev/null -w "%{http_code}" https://api.yourdomain.com/health || echo "000")
        
          if [ "$response" = "200" ]; then
            echo "✅ Health check passed! Status: $response"
          else
            echo "❌ Health check failed! Status: $response"
            exit 1
          fi

  # ==========================================
  # Notify on Success/Failure
  # ==========================================
  notify:
    name: Notify
    needs: [build, deploy]
    runs-on: ubuntu-latest
    if: always()
  
    steps:
      - name: Send Slack Notification
        if: github.event_name == 'push'
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ needs.deploy.result }}
          text: |
            Deployment ${{ needs.deploy.result == 'success' && '✅ succeeded' || '❌ failed' }}
            Repository: ${{ github.repository }}
            Commit: ${{ github.sha }}
            Author: ${{ github.actor }}
          webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### 8.2 Required GitHub Secrets

Navigate to: **Settings → Secrets and variables → Actions**

| Secret Name           | Description              | Example                                     |
| --------------------- | ------------------------ | ------------------------------------------- |
| `EC2_HOST`          | EC2 public IP or DNS     | `ec2-12-34-56-78.compute-1.amazonaws.com` |
| `EC2_USER`          | SSH user                 | `ubuntu`                                  |
| `EC2_SSH_KEY`       | Private SSH key          | *(content of your .pem file)*             |
| `SLACK_WEBHOOK_URL` | Slack webhook (optional) | `https://hooks.slack.com/services/...`    |

---

## Section 9: Verification Checklist

### 9.1 Post-Deployment Verification

```bash
# ============================================
# Verification Commands
# ============================================

# 1. Check Docker containers
docker compose ps
docker compose logs --tail=50 app

# 2. Check Nginx status
sudo systemctl status nginx
sudo nginx -t

# 3. Check SSL certificate
sudo certbot certificates
curl -vI https://api.yourdomain.com 2>&1 | grep -E "(SSL|TLS|HTTP)"

# 4. Check application health
curl -s http://localhost:8000/health | jq
curl -s https://api.yourdomain.com/health | jq

# 5. Check database connection
curl -s -H "Authorization: Bearer YOUR_TOKEN" https://api.yourdomain.com/api/profile

# 6. Check logs
sudo journalctl -u nginx -f
docker compose logs -f app

# 7. Test API endpoints
curl -X GET https://api.yourdomain.com/
curl -X GET https://api.yourdomain.com/questions/companies

# 8. Check firewall
sudo ufw status numbered

# 9. Resource usage
htop
docker stats
```

### 9.2 Automated Health Check Script

Create file: `scripts/healthcheck.sh`

```bash
#!/bin/bash
# ============================================
# Health Check Script
# Add to cron: */5 * * * * /opt/interview-api/scripts/healthcheck.sh
# ============================================

LOG_FILE="/var/log/interview-api-health.log"
API_URL="https://api.yourdomain.com"
ALERT_WEBHOOK="${SLACK_WEBHOOK_URL:-}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_health() {
    response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "${API_URL}/health")
  
    if [ "$response" = "200" ]; then
        log "✅ Health check passed (HTTP $response)"
        return 0
    else
        log "❌ Health check failed (HTTP $response)"
      
        # Send alert
        if [ -n "$ALERT_WEBHOOK" ]; then
            curl -s -X POST "$ALERT_WEBHOOK" \
                -H 'Content-type: application/json' \
                -d "{\"text\":\"🚨 Interview API health check failed! HTTP $response\"}"
        fi
      
        # Try to restart
        log "Attempting to restart container..."
        cd /opt/interview-api/interview-app/backend
        docker compose restart app
        return 1
    fi
}

# Main
check_health
```

---

## Section 10: Troubleshooting Guide

### 10.1 Common Issues & Solutions

| Issue                      | Symptoms                                 | Solution                                                                                     |
| -------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------- |
| Container won't start      | `docker compose ps` shows "Restarting" | Check logs:`docker compose logs app`. Verify `.env` file exists and has correct values.  |
| 502 Bad Gateway            | Nginx returns 502                        | Backend not running. Check`docker compose ps`. Check if port 8000 is occupied.             |
| Connection refused         | Cannot connect to API                    | Check firewall:`sudo ufw status`. Check if Docker is binding to correct port.              |
| SSL certificate error      | Browser shows warning                    | Re-run certbot:`sudo certbot renew --force-renewal`. Check DNS resolves to EC2 IP.         |
| Database connection failed | Health check shows`supabase_*: false`  | Verify`SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in `.env`. Check network connectivity. |
| CORS errors                | Browser blocks requests                  | Update CORS in`main.py` to allow your frontend domain.                                     |
| High memory usage          | Server becomes slow                      | Reduce workers in uvicorn command. Add swap. Increase EC2 instance size.                     |

### 10.2 Debugging Commands

```bash
# View application logs
docker compose logs -f --tail=200 app

# View Nginx logs
sudo tail -f /var/log/nginx/interview-api-access.log
sudo tail -f /var/log/nginx/interview-api-error.log

# Check container resource usage
docker stats interview-api

# Enter running container
docker compose exec app /bin/bash

# Inspect container
docker compose inspect app

# Check network connectivity
docker compose exec app curl -I http://localhost:8000/health

# Check environment variables
docker compose exec app env | grep -E "(SUPABASE|GEMINI|CLOUDINARY)"

# Restart everything
docker compose down
docker compose up -d

# Full reset
docker compose down -v
docker compose build --no-cache
docker compose up -d
```

### 10.3 Rollback Procedure

```bash
# ============================================
# Rollback Procedure
# ============================================

# Option 1: Revert to previous Docker image
cd /opt/interview-api/interview-app/backend

# Find previous image
docker images | grep interview-api

# Tag and run previous image
docker tag ghcr.io/your-repo/interview-api:abc123 ghcr.io/your-repo/interview-api:previous
docker compose down
docker compose up -d

# Option 2: Git rollback
git log --oneline -10
git checkout <previous-commit-hash>

docker compose build --no-cache
docker compose up -d

# Option 3: Quick fix - restart containers
docker compose restart app

# Option 4: Nuclear option - clean slate
docker compose down -v
docker system prune -af
docker compose up -d --build
```

---

## Section 11: Monitoring & Logging Setup

### 11.1 Prometheus Configuration

Create file: `monitoring/prometheus.yml`

```yaml
# ============================================
# Prometheus Configuration
# ============================================

global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    monitor: 'interview-api'

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'interview-api'
    static_configs:
      - targets: ['app:8000']
    metrics_path: '/metrics'
    scheme: http

  - job_name: 'nginx'
    static_configs:
      - targets: ['localhost:9113']
```

### 11.2 Add Prometheus Instrumentation

Add to `main.py`:

```python
# Add Prometheus metrics (optional)
from prometheus_fastapi_instrumentator import Instrumentator

# After creating app
Instrumentator().instrument(app).expose(app)
```

Add to `requirements.txt`:

```
prometheus-fastapi-instrumentator>=7.0.0
```

### 11.3 Log Rotation

Create file: `/etc/logrotate.d/interview-api`

```
/var/log/interview-api-health.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0644 www-data www-data
}
```

---

## Section 12: Connecting Backend with Supabase

### 12.1 Verify Supabase Configuration

1. **Get Supabase credentials from dashboard:**

   - Go to: https://supabase.com/dashboard
   - Select your project
   - Navigate to: Settings → API
   - Copy:
     - Project URL → `SUPABASE_URL`
     - Anon Public → `SUPABASE_ANON_KEY`
     - Service Role → `SUPABASE_SERVICE_KEY` (⚠️ Keep secret!)
2. **Verify database schema:**

   ```bash
   # Test connection from EC2
   curl -X POST "${SUPABASE_URL}/rest/v1/rpc/verify" \
     -H "apikey: ${SUPABASE_SERVICE_KEY}" \
     -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}"
   ```
3. **Database connection flow:**

   ```
   Frontend → Supabase Auth → JWT Token
        ↓
   Backend receives JWT in Authorization header
        ↓
   Backend validates JWT using SUPABASE_SERVICE_KEY
        ↓
   Backend reads/writes data using Supabase client
   ```

### 12.2 Network Configuration

Supabase requires **no special configuration** since:

- Backend connects outbound to Supabase (HTTPS)
- Supabase IP addresses are publicly accessible
- No IP whitelisting needed by default

If you want to restrict access:

1. Go to Supabase Dashboard → Settings → Database
2. Add your EC2 Elastic IP to allowed IPs (optional)

---

## Section 13: Update Vercel Frontend API URL

### 13.1 Steps to Update Frontend

1. **Update `config.js` in your frontend:**

   ```javascript
   // File: interview-app/frontend/js/config.js
   const CONFIG = {
     // Change this to your new EC2 backend URL
     API_BASE_URL: "https://api.yourdomain.com",

     // Supabase config remains the same
     SUPABASE_URL: "https://armfnjzilchguppytyvm.supabase.co",
     SUPABASE_ANON_KEY: "your_anon_key",

     AUTH_IDLE_TIMEOUT_MS: 60 * 60 * 1000,
     AUTH_ACTIVITY_PING_MS: 30 * 1000,
   };
   ```
2. **Push changes and redeploy on Vercel:**

   ```bash
   git add interview-app/frontend/js/config.js
   git commit -m "Update API URL to AWS EC2 backend"
   git push origin main
   ```
3. **Vercel will auto-deploy (if connected)** or manually redeploy.

### 13.2 Environment Variables on Vercel

Alternatively, use environment variables in Vercel:

1. Go to Vercel Dashboard → Your Project → Settings → Environment Variables
2. Add:
   - `VITE_API_BASE_URL` = `https://api.yourdomain.com`
3. Update `config.js`:
   ```javascript
   const CONFIG = {
     API_BASE_URL: import.meta.env.VITE_API_BASE_URL || "https://api.yourdomain.com",
     // ...
   };
   ```

---

## Section 14: Quick Reference

### 14.1 All Files to Create

| File Path                                     | Purpose                      |
| --------------------------------------------- | ---------------------------- |
| `interview-app/backend/Dockerfile`          | Container image build        |
| `interview-app/backend/.dockerignore`       | Build context exclusions     |
| `interview-app/backend/docker-compose.yml`  | Container orchestration      |
| `interview-app/backend/.env.example`        | Environment template         |
| `.github/workflows/deploy.yml`              | CI/CD pipeline               |
| `scripts/healthcheck.sh`                    | Health monitoring            |
| `/etc/nginx/sites-available/interview-api`  | Nginx reverse proxy          |
| `/etc/systemd/system/interview-api.service` | Systemd service (non-Docker) |

### 14.2 Quick Deployment Commands

```bash
# One-time setup
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin nginx certbot python3-certbot-nginx

# Deploy application
cd /opt/interview-api/interview-app/backend
docker compose up -d

# Setup SSL
sudo certbot --nginx -d api.yourdomain.com

# Enable services
sudo systemctl enable --now nginx docker
```

### 14.3 Useful Commands

```bash
# View logs
docker compose logs -f app

# Restart application
docker compose restart app

# Update and redeploy
git pull && docker compose up -d --build

# Check health
curl http://localhost:8000/health
```

---

## Support

For issues or questions:

1. Check the [Troubleshooting Guide](#section-10-troubleshooting-guide)
2. Review application logs: `docker compose logs -f app`
3. Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`

---

**Document Version:** 1.0.0
**Last Updated:** June 2026
**Author:** DevOps Team
