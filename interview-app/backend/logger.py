import logging
import json
import contextvars
from datetime import datetime, timezone

request_id_var = contextvars.ContextVar("request_id", default="")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get()
        }
        
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        
        # Add extra attributes (contextual info)
        for key, value in record.__dict__.items():
            if key not in ["args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName", "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process", "processName", "relativeCreated", "stack_info", "thread", "threadName", "taskName", "color_message"]:
                log_record[key] = value

        return json.dumps(self._sanitize(log_record))
    
    def _sanitize(self, data):
        sensitive_keys = {"password", "token", "access_token", "api_key", "secret", "authorization"}
        if isinstance(data, dict):
            return {k: ("***" if k.lower() in sensitive_keys else self._sanitize(v)) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._sanitize(v) for v in data]
        return data

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    
    from logging.handlers import RotatingFileHandler
    import os
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"), maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)
    
    # Redirect uvicorn and fastapi loggers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]:
        l = logging.getLogger(logger_name)
        l.handlers = [handler]
        l.propagate = False
        
    return logger

def get_logger(name):
    return logging.getLogger(name)
