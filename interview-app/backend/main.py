"""FastAPI application entry point for the Interview Practice Platform.

Run locally with:
    cd interview-app/backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from limiter import limiter

# Load environment variables from .env file in the project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Also try the backend directory .env as fallback
_env_path_backend = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path_backend, override=False)

# Import routers
from routes.auth import router as auth_router
from routes.questions import router as questions_router
from routes.assistant import router as assistant_router
from routes.progress import router as progress_router
from routes.revisit import router as revisit_router
from routes.comments import router as comments_router
from routes.profile import router as profile_router
from routes.system_design import router as system_design_router
from routes.courses import router as courses_router
from routes.leetcode import router as leetcode_router
from middleware.rate_limit_middleware import RateLimitAuthMiddleware


app = FastAPI(
    title="Interview Practice Platform API",
    description="Backend API for the Interview Practice Platform with AI assistant, progress tracking, and question management.",
    version="1.0.0",
)

# ── Middleware ───────────────────────────────────────────────────────────────

# CORS — allow specific origins in production
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").strip()
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if frontend_url and frontend_url not in origins:
    origins.append(frontend_url)

if allowed_origins_env:
    for o in allowed_origins_env.split(","):
        o_clean = o.strip()
        if o_clean and o_clean not in origins:
            origins.append(o_clean)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Inject user_id onto request.state for composite rate-limit keying.
app.add_middleware(RateLimitAuthMiddleware)

# ── Rate Limiting ────────────────────────────────────────────────────────────

app.state.limiter = limiter


async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return RFC-7807 compliant 429 response with Retry-After and quota headers."""
    retry_after = getattr(exc, "retry_after", 60)
    limit_str = str(getattr(exc, "detail", "rate limit exceeded"))
    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Too many requests. {limit_str}",
            "retry_after_seconds": retry_after,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": limit_str,
            "Content-Type": "application/json",
        },
    )


app.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)

# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(assistant_router)
app.include_router(progress_router)
app.include_router(revisit_router)
app.include_router(comments_router)
app.include_router(profile_router)
app.include_router(system_design_router)
app.include_router(courses_router)
app.include_router(leetcode_router)


# ── Health checks ────────────────────────────────────────────────────────────

from services.rds_client import check_rds_health


@app.on_event("startup")
def validate_production_environment():
    """Fail-fast validation for critical security invariants at startup."""
    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
    if env in ("production", "prod") and os.getenv("DISABLE_AUTH") == "true":
        raise RuntimeError("SECURITY INVARIANT VIOLATION: DISABLE_AUTH is strictly forbidden in production!")


# ── Health & Diagnostics ──────────────────────────────────────────────────────

@app.get("/")
def root():
    """Default service status endpoint."""
    return {
        "status": "ok",
        "app": "Interview Practice Platform",
        "version": "1.0.0",
    }


@app.get("/health/live")
def liveness():
    """Process liveness probe: verifies application process is running and responding."""
    return {
        "status": "live",
        "app": "Interview Practice Platform",
        "version": "1.0.0",
    }


@app.get("/health/ready")
def readiness(response: Response):
    """Database readiness probe: verifies Amazon RDS connection pool and connectivity."""
    db_ok = check_rds_health()
    if not db_ok:
        response.status_code = 503
        return {
            "status": "not_ready",
            "database": "disconnected",
            "detail": "Amazon RDS PostgreSQL connectivity check failed",
        }
    return {
        "status": "ready",
        "database": "connected",
    }


@app.get("/health")
def health(response: Response):
    """Detailed health check for all platform services."""
    rds_ok = check_rds_health()
    checks = {
        "rds_connected": rds_ok,
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "supabase_url_set": bool(os.getenv("SUPABASE_URL", "").strip()),
        "supabase_key_set": bool(os.getenv("SUPABASE_SERVICE_KEY", "").strip()),
    }
    all_ok = all(checks.values())
    if not rds_ok:
        response.status_code = 503
    return {
        "status": "ok" if all_ok else ("degraded" if rds_ok else "unhealthy"),
        "checks": checks,
    }


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=2)
