"""FastAPI application entry point for the Interview Practice Platform.

Run locally with:
    cd interview-app/backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
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
origins = [
    "http://localhost:3000",
]
if frontend_url and frontend_url not in origins:
    origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
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

@app.get("/")
def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "app": "Interview Practice Platform",
        "version": "1.0.0",
    }


@app.get("/health")
def health():
    """Detailed health check."""
    checks = {
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "supabase_url_set": bool(os.getenv("SUPABASE_URL", "").strip()),
        "supabase_key_set": bool(os.getenv("SUPABASE_SERVICE_KEY", "").strip()),
    }
    return {
        "status": "ok" if all(checks.values()) else "partial",
        "checks": checks,
    }

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=2)
