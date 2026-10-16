# AWS EC2 Deployment Guide (Legacy Notice)

> [!IMPORTANT]
> **This document has been superseded by the canonical deployment runbook.**
>
> Please refer to [DEPLOYMENT.md](DEPLOYMENT.md) for the authoritative, verified manual deployment guide for the Interview Prep platform on AWS EC2 (`ap-south-2` Hyderabad).

---

## Architecture Summary

The deployment architecture consists of:
- **Compute Instance**: AWS EC2 `m7i-flex.large` (2 vCPUs, 8 GiB RAM, 30 GiB `gp3` root volume) running Ubuntu Server 24.04 LTS (x86_64).
- **Network**: Deployed in `interview-prep-vpc` on public subnet `interview-prep-public-a` with Security Group `interview-prep-app-sg` and IAM Role `InterviewPrepEC2Role` (enabling AWS Systems Manager Session Manager access).
- **Container Runtime**: Docker Compose managing:
  - **Frontend**: Next.js 16 container bound to host loopback `127.0.0.1:3000`.
  - **Backend**: FastAPI (Python 3.12) container bound to host loopback `127.0.0.1:8000`.
- **Reverse Proxy**: Host-level Nginx listening on port 80 (HTTP) / 443 (HTTPS), proxying `/` to Next.js and `/api/backend/` (and `/health`) to FastAPI.
- **External Services**:
  - **Database & Auth**: Supabase Cloud PostgreSQL & Supabase Auth.
  - **AI Doubt Assistant**: Google Gemini API.
  - **Media & Diagrams**: Cloudinary CDN.

All deployment files (`docker-compose.yml`, Dockerfiles, Nginx configurations, and environment templates) are fully tracked and verified in the [`aws-migration`](https://github.com/saicharanyadavalli/interview-prep/tree/aws-migration) branch.

Please navigate to [DEPLOYMENT.md](DEPLOYMENT.md) for the complete, step-by-step instructions.
