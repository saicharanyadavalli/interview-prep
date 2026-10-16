# syntax=docker/dockerfile:1

# ============================================
# Interview Practice Platform - Production Dockerfile
# Multi-stage build for optimized image size
# ============================================

# --- Stage 1: Builder ---
FROM python:3.12-slim-bookworm AS builder

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
FROM python:3.12-slim-bookworm AS runtime

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
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Labels for transparency
LABEL org.opencontainers.image.title="Interview Practice Platform"
LABEL org.opencontainers.image.description="FastAPI backend for interview practice"
LABEL org.opencontainers.image.version="1.0.0"

# Production startup command - Use PORT env var for Render/Heroku support
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
