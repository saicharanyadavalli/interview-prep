"""FastAPI application entry point in app/main.py."""

import sys
from pathlib import Path

# Add backend directory to python path if not present
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from main import app

__all__ = ["app"]
