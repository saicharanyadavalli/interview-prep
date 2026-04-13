"""FastAPI application entry point for the Interview Practice Platform.

Run locally with:
    cd interview-app/backend
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


app = FastAPI(
    title="Interview Practice Platform API",
    description="Backend API for the Interview Practice Platform with AI assistant, progress tracking, and question management.",
    version="1.0.0",
)

# CORS — allow all origins in development.
# In production, restrict to your deployed frontend URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(auth_router)
app.include_router(questions_router)
app.include_router(assistant_router)
app.include_router(progress_router)
app.include_router(revisit_router)
app.include_router(comments_router)
app.include_router(profile_router)
app.include_router(system_design_router)


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
