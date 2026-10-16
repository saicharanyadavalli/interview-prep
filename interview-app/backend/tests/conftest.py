"""Shared Pytest fixtures and mock configurations for FastAPI backend test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure interview-app/backend is at the root of sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Mock google.generativeai before any application module imports it to prevent gRPC C-extension hang
if "google.generativeai" not in sys.modules:
    sys.modules["google.generativeai"] = MagicMock()

# Ensure test execution does not use live external credentials
os.environ["DISABLE_AUTH"] = "false"
os.environ["GEMINI_API_KEY"] = "mock-test-gemini-key"
os.environ["SUPABASE_URL"] = "https://mock-test.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock-test-supabase-service-key"
os.environ["RATE_LIMIT_STORAGE_URI"] = "memory://"

from limiter import limiter
from main import app
from routes.auth import get_current_user, get_optional_current_user


# ── Mock User Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_user() -> dict[str, Any]:
    """Standard authenticated user dict matching Supabase auth user model."""
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "email": "testuser@example.com",
        "username": "testuser",
        "name": "Test User",
        "avatar_url": "https://example.com/avatar.png",
    }


@pytest.fixture
def mock_other_user() -> dict[str, Any]:
    """Second authenticated user dict for testing multi-user isolation."""
    return {
        "id": "99999999-8888-7777-6666-555555555555",
        "email": "otheruser@example.com",
        "username": "otheruser",
        "name": "Other User",
        "avatar_url": "https://example.com/other.png",
    }


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """HTTP headers with standard Bearer token."""
    return {"Authorization": "Bearer mock-valid-jwt-token"}


# ── Mock Supabase Query Builder ───────────────────────────────────────────────

class MockQueryBuilder:
    """Fluent mock query builder for Supabase PostgREST table operations."""

    def __init__(self, table_name: str, initial_data: list[dict] | None = None):
        self.table_name = table_name
        self.data: list[dict] = initial_data or []
        self._count = len(self.data)

    def select(self, *args, **kwargs):
        return self

    def eq(self, column: str, value: Any):
        return self

    def in_(self, column: str, values: list[Any]):
        return self

    def ilike(self, column: str, pattern: str):
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def upsert(self, payload: dict | list[dict], on_conflict: str = ""):
        rows = [payload] if isinstance(payload, dict) else payload
        self.data = rows
        return self

    def insert(self, payload: dict | list[dict]):
        rows = [payload] if isinstance(payload, dict) else payload
        self.data = rows
        return self

    def update(self, payload: dict):
        self.data = [payload]
        return self

    def delete(self):
        self.data = [{"id": "deleted-row-id"}]
        return self

    def execute(self):
        res = MagicMock()
        res.data = self.data
        res.count = self._count
        return res


class MockSupabaseClient:
    """Mock Supabase client providing table query builders and auth mock."""

    def __init__(self):
        self._tables: dict[str, list[dict]] = {}
        self.auth = MagicMock()
        mock_auth_user = MagicMock()
        mock_auth_user.user.id = "11111111-2222-3333-4444-555555555555"
        mock_auth_user.user.email = "testuser@example.com"
        mock_auth_user.user.user_metadata = {
            "username": "testuser",
            "full_name": "Test User",
            "avatar_url": "https://example.com/avatar.png",
        }
        self.auth.get_user.return_value = mock_auth_user

    def set_table_data(self, table_name: str, rows: list[dict]):
        self._tables[table_name] = rows

    def table(self, table_name: str) -> MockQueryBuilder:
        return MockQueryBuilder(table_name, self._tables.get(table_name, []))


@pytest.fixture
def mock_supabase() -> Generator[MockSupabaseClient, None, None]:
    """Fixture providing a configurable MockSupabaseClient patched across all service/route imports."""
    mock_client = MockSupabaseClient()
    with patch("services.supabase_client.get_supabase_client", return_value=mock_client), \
         patch("services.courses_service.get_supabase_client", return_value=mock_client), \
         patch("services.questions_service.get_supabase_client", return_value=mock_client), \
         patch("routes.auth.get_supabase_client", return_value=mock_client), \
         patch("routes.questions.get_supabase_client", return_value=mock_client), \
         patch("routes.progress.get_supabase_client", return_value=mock_client), \
         patch("routes.revisit.get_supabase_client", return_value=mock_client), \
         patch("routes.comments.get_supabase_client", return_value=mock_client), \
         patch("routes.profile.get_supabase_client", return_value=mock_client), \
         patch("routes.system_design.get_supabase_client", return_value=mock_client), \
         patch("routes.leetcode.get_supabase_client", return_value=mock_client):
        yield mock_client


# ── Global Test Cleansing & Limiter Reset ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state_and_rate_limits():
    """Reset slowapi limiter storage and clear dependency overrides between tests."""
    limiter.reset()
    yield
    app.dependency_overrides.clear()
    limiter.reset()


# ── TestClient Fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def client(mock_user: dict[str, Any]) -> Generator[TestClient, None, None]:
    """TestClient with authenticated user dependency overrides active by default."""
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_optional_current_user] = lambda: mock_user
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client() -> Generator[TestClient, None, None]:
    """TestClient representing an unauthenticated anonymous user."""
    app.dependency_overrides.clear()
    with TestClient(app) as tc:
        yield tc


# ── External Service Mocks (Gemini AI & Cloudinary) ───────────────────────────

@pytest.fixture
def mock_gemini_stream() -> Generator[MagicMock, None, None]:
    """Mock Gemini streaming generator yielding deterministic text chunks."""
    def dummy_stream(*args, **kwargs):
        yield "Consider using a "
        yield "hash table with O(N) "
        yield "time complexity."

    with patch("services.gemini_service.ask_gemini_stream", side_effect=dummy_stream) as stream_mock, \
         patch("routes.assistant.ask_gemini_stream", side_effect=dummy_stream):
        yield stream_mock


@pytest.fixture
def mock_cloudinary() -> Generator[MagicMock, None, None]:
    """Mock Cloudinary upload result."""
    with patch("routes.profile.cloudinary.uploader.upload") as upload_mock:
        upload_mock.return_value = {
            "secure_url": "https://res.cloudinary.com/demo/image/upload/avatar.png",
            "url": "http://res.cloudinary.com/demo/image/upload/avatar.png",
        }
        yield upload_mock
