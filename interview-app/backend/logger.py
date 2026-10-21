"""Structured JSON logging and context-aware sanitization for FastAPI & CloudWatch."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# Regular expressions for string-level redaction
_REGEX_PATTERNS = [
    (re.compile(r"(postgres(?:ql)?://[^:]+:)([^@]+)(@)", re.IGNORECASE), r"\1****\3"),
    (re.compile(r"(redis(?:s)?://:[^:]+)(@)", re.IGNORECASE), r"redis://:****\2"),
    (re.compile(r"(redis(?:s)?://[^:]+:)([^@]+)(@)", re.IGNORECASE), r"\1****\3"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"\1***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), r"AKIA****"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), r"AIza****"),
]


def redact_string(val: str) -> str:
    """Scrub sensitive patterns from string values."""
    if not val:
        return val
    for pattern, replacement in _REGEX_PATTERNS:
        val = pattern.sub(replacement, val)
    return val


def sanitize_log_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and patterns from log records."""
    sensitive_keys = {
        "password",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "secret",
        "authorization",
        "cookie",
        "credential",
        "client_secret",
        "auth_token",
    }
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            if str(k).lower() in sensitive_keys:
                cleaned[k] = "***"
            else:
                cleaned[k] = sanitize_log_data(v)
        return cleaned
    elif isinstance(data, list):
        return [sanitize_log_data(item) for item in data]
    elif isinstance(data, str):
        return redact_string(data)
    return data


class JSONFormatter(logging.Formatter):
    """CloudWatch-compatible single-line JSON log formatter."""

    _sanitize = staticmethod(sanitize_log_data)

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_string(record.getMessage()),
            "request_id": request_id_var.get() or "",
        }

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)

        # Append extra contextual attributes
        excluded = {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "message",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",
            "color_message",
        }
        for key, value in record.__dict__.items():
            if key not in excluded:
                log_record[key] = value

        return json.dumps(sanitize_log_data(log_record), default=str)


def setup_logging() -> logging.Logger:
    """Configure root logger to emit single-line JSON records to stdout."""
    root_logger = logging.getLogger()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Standard stdout StreamHandler (CloudWatch container agent ingestion)
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(JSONFormatter())
    root_logger.addHandler(stdout_handler)

    # Optional local file handler (only if explicitly enabled via LOG_TO_FILE=true)
    if os.getenv("LOG_TO_FILE", "false").lower() in ("true", "1", "yes"):
        from logging.handlers import RotatingFileHandler

        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "app.log"), maxBytes=10 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(file_handler)

    # Synchronize uvicorn and fastapi loggers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
        l = logging.getLogger(logger_name)
        l.handlers = [stdout_handler]
        l.propagate = False

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
