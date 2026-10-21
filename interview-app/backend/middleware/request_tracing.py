"""Request tracing and structured access logging middleware for FastAPI."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from logger import request_id_var

access_logger = logging.getLogger("middleware.access")

_REQ_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SENSITIVE_QUERY_PARAMS = {"token", "code", "key", "password", "secret", "access_token", "api_key"}


def sanitize_url_path(url_str: str) -> str:
    """Scrub sensitive query parameters from URLs."""
    try:
        parts = urlsplit(url_str)
        if not parts.query:
            return parts.path
        query_params = parse_qsl(parts.query, keep_blank_values=True)
        sanitized = [
            (k, "***" if k.lower() in _SENSITIVE_QUERY_PARAMS else v)
            for k, v in query_params
        ]
        return urlunsplit(("", "", parts.path, urlencode(sanitized), ""))
    except Exception:
        return url_str.split("?")[0]


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generates or propagates X-Request-ID correlation headers for distributed tracing."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        inbound_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
        if inbound_id and _REQ_ID_PATTERN.match(inbound_id.strip()):
            req_id = inbound_id.strip()
        else:
            req_id = str(uuid.uuid4())

        token = request_id_var.set(req_id)
        request.state.request_id = req_id

        try:
            response = await call_next(request)
            response.headers["x-request-id"] = req_id
            return response
        finally:
            request_id_var.reset(token)


class AccessLoggingMiddleware(BaseHTTPMiddleware):
    """Emits single-line structured JSON access logs to stdout for CloudWatch ingestion."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        status_code = 500
        response: Response | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            cache_outcome = getattr(request.state, "cache_outcome", None)
            if cache_outcome:
                response.headers["X-Cache"] = cache_outcome
            return response
        except Exception:
            status_code = 500
            raise
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            path = sanitize_url_path(request.url.path + (f"?{request.url.query}" if request.url.query else ""))

            # Filter out noisy successful liveness probes from access logs
            is_health_poll = path in ("/health/live", "/health/ready", "/health")
            if is_health_poll and status_code < 400:
                return response  # type: ignore[return-value]

            # Extract client IP
            client_ip = (
                request.headers.get("x-real-ip")
                or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
                or (request.client.host if request.client else "127.0.0.1")
            )

            req_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
            user_id = getattr(request.state, "rate_limit_user_id", None) or ""
            cache_outcome = getattr(request.state, "cache_outcome", None)

            extra = {
                "request_id": req_id,
                "path": path,
                "method": request.method,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "client_ip": client_ip,
                "user_id": user_id,
            }
            if cache_outcome:
                extra["cache"] = cache_outcome

            msg = f"{request.method} {path} -> {status_code} ({duration_ms}ms)"
            if status_code >= 500:
                access_logger.error(msg, extra=extra)
            elif status_code >= 400:
                access_logger.warning(msg, extra=extra)
            else:
                access_logger.info(msg, extra=extra)
