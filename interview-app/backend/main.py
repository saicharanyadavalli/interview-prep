"""FastAPI application entry point for the Interview Practice Platform.

Run locally with:
    cd interview-app/backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

# ── Load Environment Variables ───────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_env_path_backend = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path_backend, override=False)

# ── Structured Logging & Context Tracing Setup ──────────────────────────────
from logger import get_logger, request_id_var, setup_logging

setup_logging()
logger = get_logger("main")

from limiter import limiter
from middleware.rate_limit_middleware import RateLimitAuthMiddleware
from middleware.request_tracing import AccessLoggingMiddleware, RequestIdMiddleware
from routes.assistant import router as assistant_router
from routes.auth import router as auth_router
from routes.comments import router as comments_router
from routes.courses import router as courses_router
from routes.leetcode import router as leetcode_router
from routes.profile import router as profile_router
from routes.progress import router as progress_router
from routes.questions import router as questions_router
from routes.revisit import router as revisit_router
from routes.system_design import router as system_design_router
from services.cache_service import get_cache_service
from services.rds_client import RDSConnectionPoolManager, check_rds_health


# ── Application Lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager: initializes shared services and handles graceful shutdown."""
    # ── Startup Phase ──────────────────────────────────────────────────────────
    logger.info("Initializing Interview Practice Platform API...")

    env = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("ENV") or "").lower()
    if env in ("production", "prod") and os.getenv("DISABLE_AUTH") == "true":
        raise RuntimeError("SECURITY INVARIANT VIOLATION: DISABLE_AUTH is strictly forbidden in production!")

    # 1. Initialize Amazon RDS connection pool
    try:
        RDSConnectionPoolManager.get_instance().initialize()
    except Exception as exc:
        logger.error("Failed to initialize RDS connection pool on startup: %s", exc)

    # 2. Initialize Redis/Valkey Cache Service (Fail-open)
    cache_svc = get_cache_service()
    await cache_svc.initialize()

    yield

    # ── Shutdown Phase ─────────────────────────────────────────────────────────
    logger.info("Shutting down Interview Practice Platform API...")

    # 1. Disconnect Redis Cache Service
    try:
        await cache_svc.close()
    except Exception as exc:
        logger.warning("Error disconnecting cache service pool: %s", exc)

    # 2. Disconnect Limiter Storage Pool
    try:
        storage = getattr(limiter, "_storage", None)
        if storage:
            raw_storage = getattr(storage, "storage", None)
            if raw_storage and hasattr(raw_storage, "close"):
                raw_storage.close()
            elif hasattr(storage, "close"):
                storage.close()
            if hasattr(storage, "connection_pool") and hasattr(storage.connection_pool, "disconnect"):
                storage.connection_pool.disconnect()
    except Exception as exc:
        logger.warning("Error closing rate limiter storage: %s", exc)

    # 3. Cleanly close RDS PostgreSQL connection pool
    try:
        if RDSConnectionPoolManager._instance:
            RDSConnectionPoolManager._instance.close()
    except Exception as exc:
        logger.warning("Error closing RDS connection pool during shutdown: %s", exc)


app = FastAPI(
    title="Interview Practice Platform API",
    description="Backend API for the Interview Practice Platform with AI assistant, progress tracking, and question management.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Middleware Registration ─────────────────────────────────────────────────
# Starlette wraps middleware in reverse order of addition.
# Execution order: RequestIdMiddleware -> AccessLoggingMiddleware -> CORSMiddleware -> RateLimitAuthMiddleware

# Injected user_id onto request.state for composite rate-limit keying
app.add_middleware(RateLimitAuthMiddleware)

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

# Structured JSON access logging
app.add_middleware(AccessLoggingMiddleware)

# Correlation ID propagation (runs first on request arrival)
app.add_middleware(RequestIdMiddleware)

# ── Rate Limiting Setup ──────────────────────────────────────────────────────

app.state.limiter = limiter


# ── Global Exception Handlers ────────────────────────────────────────────────

@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return RFC-7807 compliant 429 response with Retry-After and correlation headers."""
    retry_after = getattr(exc, "retry_after", 60)
    limit_str = str(getattr(exc, "detail", "rate limit exceeded"))
    req_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    user_id = getattr(request.state, "rate_limit_user_id", None) or ""
    client_ip = (
        request.headers.get("x-real-ip")
        or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "127.0.0.1")
    )

    logger.warning(
        "Rate limit exceeded: %s on %s %s (ip=%s, user=%s)",
        limit_str,
        request.method,
        request.url.path,
        client_ip,
        user_id,
        extra={
            "request_id": req_id,
            "path": request.url.path,
            "method": request.method,
            "client_ip": client_ip,
            "user_id": user_id,
            "limit": limit_str,
        },
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": f"Too many requests. {limit_str}",
            "retry_after_seconds": retry_after,
            "request_id": req_id,
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": limit_str,
            "X-Request-ID": req_id,
            "Content-Type": "application/json",
        },
    )


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Return structured JSON error response preserving detail and request_id."""
    req_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    status_code = exc.status_code

    if status_code >= 500:
        logger.error(
            "HTTP %d on %s %s: %s",
            status_code,
            request.method,
            request.url.path,
            exc.detail,
            extra={"request_id": req_id, "status_code": status_code, "path": request.url.path},
        )
    elif status_code >= 400:
        logger.warning(
            "HTTP %d on %s %s: %s",
            status_code,
            request.method,
            request.url.path,
            exc.detail,
            extra={"request_id": req_id, "status_code": status_code, "path": request.url.path},
        )

    headers = dict(exc.headers) if exc.headers else {}
    if req_id:
        headers["X-Request-ID"] = req_id

    # Preserve FastAPI's exact standard {"detail": exc.detail} response format
    # to maintain full backward compatibility with existing API contracts and test suites.
    return JSONResponse(status_code=status_code, content={"detail": exc.detail}, headers=headers)


from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def custom_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return sanitized 422 validation response with correlation ID."""
    req_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    logger.warning(
        "Validation error on %s %s (errors_count=%d)",
        request.method,
        request.url.path,
        len(exc.errors()),
        extra={"request_id": req_id, "path": request.url.path},
    )
    headers = {"X-Request-ID": req_id} if req_id else {}
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors())},
        headers=headers,
    )


@app.exception_handler(Exception)
async def custom_unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global catch-all 500 shield preventing leakage of stack traces or DB details to clients."""
    req_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    logger.error(
        "Unhandled 500 exception on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
        extra={"request_id": req_id, "path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred. Please try again later.",
                "request_id": req_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers={"X-Request-ID": req_id},
    )


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
async def health(response: Response):
    """Detailed health check for all platform services."""
    rds_ok = check_rds_health()
    cache_svc = get_cache_service()
    redis_ok = await cache_svc.ping()

    checks = {
        "rds_connected": rds_ok,
        "redis_connected": redis_ok,
        "redis_cache_enabled": cache_svc.is_available,
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "cognito_configured": bool(os.getenv("COGNITO_USER_POOL_ID", "").strip()),
    }

    if not rds_ok:
        response.status_code = 503
        status_label = "unhealthy"
    elif not redis_ok and cache_svc._enabled:
        status_label = "degraded"
    else:
        status_label = "ok"

    return {
        "status": status_label,
        "checks": checks,
    }


@app.get("/health/cache")
@limiter.limit("30/minute")
async def cache_diagnostics(request: Request):
    """Diagnostic telemetry endpoint for Redis/Valkey cache performance."""
    cache_svc = get_cache_service()
    is_live = await cache_svc.ping()
    return {
        "available": cache_svc.is_available,
        "ping_ok": is_live,
        "metrics": cache_svc.metrics.to_dict(),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=2)
