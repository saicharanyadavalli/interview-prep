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
os.environ["TESTING"] = "1"
os.environ["DISABLE_AUTH"] = "false"
os.environ["COGNITO_REGION"] = "ap-south-2"
os.environ["COGNITO_USER_POOL_ID"] = "ap-south-2_testPoolId"
os.environ["COGNITO_CLIENT_ID"] = "test-client-id-123"
os.environ["GEMINI_API_KEY"] = "mock-test-gemini-key"
os.environ["SUPABASE_URL"] = "https://mock-test.supabase.co"
os.environ["SUPABASE_SERVICE_KEY"] = "mock-test-supabase-service-key"
os.environ["RATE_LIMIT_STORAGE_URI"] = "memory://"
os.environ["DATABASE_URL"] = "postgresql://test_user:dummy_password@localhost:5432/interview_prep_test_db"

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

    def neq(self, column: str, value: Any):
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


class MockRDSStore:
    """In-memory mock database store intercepting rds_client.query and rds_client.mutate."""

    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def query(self, sql: str, params: Any = None, fetch: str = "all") -> Any:
        import re
        sql_clean = sql.strip()
        params = list(params) if isinstance(params, (tuple, list)) else ([params] if params is not None else [])

        # Health check
        if "SELECT 1" in sql_clean:
            if fetch == "scalar":
                return 1
            return [{"healthy": 1}]

        # Extract table name
        match = re.search(r"FROM\s+(?:[a-zA-Z0-9_]+\.)?([a-zA-Z0-9_]+)", sql_clean, re.IGNORECASE)
        if not match:
            return [] if fetch == "all" else None

        table = match.group(1).lower()
        rows = [dict(r) for r in self._tables.get(table, [])]

        # DISTINCT track_id
        if "distinct track_id" in sql_clean.lower():
            seen = set()
            res = []
            for r in rows:
                t = r.get("track_id")
                if t and t not in seen:
                    seen.add(t)
                    res.append({"track_id": t})
            return res

        # DISTINCT unnest(company_tags)
        if "distinct unnest(company_tags)" in sql_clean.lower():
            seen = set()
            for r in rows:
                for c in r.get("company_tags", []):
                    seen.add(c)
            return [{"company": c} for c in sorted(seen)]

        # Specific filters
        if "id !=" in sql_clean.lower() and len(params) >= 2:
            uname = str(params[0]).lower()
            not_id = str(params[1])
            rows = [r for r in rows if str(r.get("username", "")).lower() == uname and str(r.get("id")) != not_id]
        elif "lower(username) = lower(%s)" in sql_clean.lower() and params:
            uname = str(params[0]).lower()
            rows = [r for r in rows if str(r.get("username", "")).lower() == uname]
        elif "username = %s" in sql_clean.lower() and params:
            uname = str(params[0]).lower()
            rows = [r for r in rows if str(r.get("username", "")).lower() == uname]

        if "lower(email) = lower(%s)" in sql_clean.lower() and params:
            em = str(params[0]).lower()
            rows = [r for r in rows if str(r.get("email", "")).lower() == em]
        elif "email = %s" in sql_clean.lower() and params:
            em = str(params[0]).lower()
            rows = [r for r in rows if str(r.get("email", "")).lower() == em]

        if "provider = %s and provider_sub = %s" in sql_clean.lower() and len(params) >= 2:
            prov = str(params[0]).lower()
            psub = str(params[1])
            rows = [r for r in rows if str(r.get("provider", "")).lower() == prov and str(r.get("provider_sub", "")) == psub]

        if "user_id = %s" in sql_clean and params:
            uid = str(params[0])
            if any("user_id" in r for r in rows):
                rows = [r for r in rows if str(r.get("user_id")) == uid]

        if "where id = %s" in sql_clean.lower() and params:
            target_id = str(params[0])
            rows = [r for r in rows if str(r.get("id")) == target_id]

        if "source_qnum = %s" in sql_clean and params:
            sq = params[0]
            rows = [r for r in rows if r.get("source_qnum") == sq]

        if "qnum = any(%s)" in sql_clean.lower() or "qnum in" in sql_clean.lower():
            for p in params:
                if isinstance(p, (list, tuple, set)):
                    rows = [r for r in rows if r.get("qnum") in p]
                    break
        elif "qnum = %s" in sql_clean:
            q_val = None
            for p in params:
                if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
                    q_val = int(p)
                    break
            if q_val is not None:
                if any("qnum" in r for r in rows):
                    rows = [r for r in rows if r.get("qnum") == q_val]

        if "user_id = %s" in sql_clean and params:
            uid = str(params[0])
            if any("user_id" in r for r in rows):
                rows = [r for r in rows if str(r.get("user_id")) == uid]

        if "track_id = %s" in sql_clean:
            tid = None
            for p in params:
                if isinstance(p, str) and ("design" in p or "course" in p or "-" in p):
                    tid = p
                    break
            if tid is None and params:
                tid = str(params[-1])
            if tid is not None and any("track_id" in r for r in rows):
                rows = [r for r in rows if r.get("track_id") == tid]
        elif "track_id = 'system-design'" in sql_clean.lower() and any("track_id" in r for r in rows):
            rows = [r for r in rows if r.get("track_id") == "system-design"]

        if "is_revisit = true" in sql_clean.lower():
            rows = [r for r in rows if r.get("is_revisit") is True]

        if "is_solved = true" in sql_clean.lower():
            rows = [r for r in rows if r.get("is_solved") is True]

        if "difficulty = %s" in sql_clean:
            for p in params:
                if str(p).lower() in ("easy", "medium", "hard"):
                    rows = [r for r in rows if str(r.get("difficulty", "")).lower() == str(p).lower()]
                    break

        # Aggregate / Count
        if "count(*)" in sql_clean.lower():
            if fetch == "scalar":
                return len(rows)
            return [{"count": len(rows)}]

        # Information schema table existence checks
        if "information_schema.tables" in sql_clean.lower():
            for t_name in ("user_identities", "user_profiles", "user_progress", "learning_track_progress", "practice_history", "user_comments"):
                if t_name in sql_clean.lower():
                    exists = t_name in self._tables
                    if fetch == "scalar":
                        return exists
                    return [{"exists": exists}] if exists else []
            if fetch == "scalar":
                return True
            return [{"exists": True}]

        # Sorting
        if "order by created_at desc" in sql_clean.lower() and table != "user_comments":
            rows = sorted(rows, key=lambda x: str(x.get("created_at", "")), reverse=True)
        elif "order by updated_at desc" in sql_clean.lower():
            rows = sorted(rows, key=lambda x: str(x.get("updated_at", "")), reverse=True)
        elif "order by step_no asc" in sql_clean.lower():
            rows = sorted(rows, key=lambda x: int(x.get("step_no", 0)))
        elif "order by approach_index asc" in sql_clean.lower():
            rows = sorted(rows, key=lambda x: int(x.get("approach_index", 0)))
        elif "order by rating desc" in sql_clean.lower():
            rows = sorted(rows, key=lambda x: float(x.get("rating", 0) or 0), reverse=True)
        elif "order by rating asc" in sql_clean.lower():
            rows = sorted(rows, key=lambda x: float(x.get("rating", 0) or 0))

        # Fetch mode
        if fetch == "one":
            return rows[0] if rows else None
        elif fetch == "scalar":
            if rows:
                return next(iter(rows[0].values()))
            return None
        return rows

    def mutate(self, sql: str, params: Any = None, returning: bool = False) -> Any:
        import re
        sql_clean = sql.strip()
        params = list(params) if isinstance(params, (tuple, list)) else ([params] if params is not None else [])

        # INSERT
        m_ins = re.search(r"INSERT\s+INTO\s+(?:[a-zA-Z0-9_]+\.)?([a-zA-Z0-9_]+)", sql_clean, re.IGNORECASE)
        if m_ins:
            table = m_ins.group(1).lower()
            table_rows = self._tables.setdefault(table, [])
            m_cols = re.search(r"\(([^)]+)\)\s+VALUES", sql_clean, re.IGNORECASE)
            new_row = {}
            if m_cols:
                cols = [c.strip() for c in m_cols.group(1).split(",")]
                for i, col in enumerate(cols):
                    if i < len(params):
                        new_row[col] = params[i]

            if "id" not in new_row and table in ("user_profiles", "user_comments", "practice_history", "learning_track_progress"):
                new_row["id"] = f"{table}-{len(table_rows)+1}"

            if "on conflict" in sql_clean.lower():
                if "(id)" in sql_clean.lower() and "id" in new_row:
                    for idx, r in enumerate(table_rows):
                        if str(r.get("id")) == str(new_row["id"]):
                            table_rows[idx].update(new_row)
                            return [table_rows[idx]] if returning else 1
                elif "(user_id, qnum)" in sql_clean.lower() and "user_id" in new_row and "qnum" in new_row:
                    for idx, r in enumerate(table_rows):
                        if str(r.get("user_id")) == str(new_row["user_id"]) and r.get("qnum") == new_row["qnum"]:
                            table_rows[idx].update(new_row)
                            return [table_rows[idx]] if returning else 1
                elif "(user_id, track_id, step_no)" in sql_clean.lower():
                    for idx, r in enumerate(table_rows):
                        if (str(r.get("user_id")) == str(new_row.get("user_id")) and
                            r.get("track_id") == new_row.get("track_id") and
                            r.get("step_no") == new_row.get("step_no")):
                            table_rows[idx].update(new_row)
                            return [table_rows[idx]] if returning else 1

            table_rows.append(new_row)
            return [new_row] if returning else 1

        # UPDATE
        m_upd = re.search(r"UPDATE\s+(?:[a-zA-Z0-9_]+\.)?([a-zA-Z0-9_]+)", sql_clean, re.IGNORECASE)
        if m_upd:
            table = m_upd.group(1).lower()
            table_rows = self._tables.get(table, [])
            updated_rows = []

            if "is_revisit = false" in sql_clean.lower():
                for r in table_rows:
                    if len(params) >= 2 and (r.get("qnum") == params[1] or str(r.get("qnum")) == str(params[1])):
                        r["is_revisit"] = False
                        updated_rows.append(r)
            elif table == "user_comments":
                for r in table_rows:
                    if len(params) >= 2 and str(r.get("id")) == str(params[1]):
                        r["comment_text"] = params[0]
                        updated_rows.append(r)
            elif table == "user_profiles":
                target_id = params[-1] if params else None
                for r in table_rows:
                    if str(r.get("id")) == str(target_id):
                        if "username = %s" in sql_clean and len(params) >= 3:
                            r["username"] = params[0]
                            r["name"] = params[1]
                            r["phone"] = params[2]
                        if "avatar_url = %s" in sql_clean and len(params) >= 1:
                            r["avatar_url"] = params[0]
                        updated_rows.append(r)

            return updated_rows if returning else (len(updated_rows) or 1)

        # DELETE
        m_del = re.search(r"DELETE\s+FROM\s+(?:[a-zA-Z0-9_]+\.)?([a-zA-Z0-9_]+)", sql_clean, re.IGNORECASE)
        if m_del:
            table = m_del.group(1).lower()
            table_rows = self._tables.get(table, [])
            before_len = len(table_rows)
            if "where id = %s and user_id = %s" in sql_clean.lower() and len(params) >= 2:
                target_id = str(params[0])
                uid = str(params[1])
                self._tables[table] = [r for r in table_rows if not (str(r.get("id")) == target_id and str(r.get("user_id")) == uid)]
                return (before_len - len(self._tables[table])) if before_len > 0 else 1
            elif "where id = %s" in sql_clean.lower() and params:
                target_id = str(params[0])
                self._tables[table] = [r for r in table_rows if str(r.get("id")) != target_id]
                return (before_len - len(self._tables[table])) if before_len > 0 else 1
            elif "where user_id = %s and qnum = %s" in sql_clean.lower() and len(params) >= 2:
                target_qnum = params[1]
                self._tables[table] = [r for r in table_rows if r.get("qnum") != target_qnum]
                return before_len - len(self._tables[table])
            elif "where user_id = %s" in sql_clean.lower() and params:
                uid = str(params[0])
                self._tables[table] = [r for r in table_rows if str(r.get("user_id")) != uid]
                return before_len - len(self._tables[table])
            return 1

        return 1

    def execute_transaction(self, statements: list[tuple[str, Any]]) -> list[int]:
        results = []
        for sql, params in statements:
            count = self.mutate(sql, params)
            results.append(count if isinstance(count, int) else 0)
        return results


@pytest.fixture
def mock_supabase() -> Generator[MockSupabaseClient, None, None]:
    """Fixture providing a configurable MockSupabaseClient and mock RDS layer."""
    mock_client = MockSupabaseClient()
    mock_rds = MockRDSStore(mock_client._tables)
    with patch("services.supabase_client.get_supabase_client", return_value=mock_client), \
         patch("services.rds_client.query", side_effect=mock_rds.query), \
         patch("services.rds_client.mutate", side_effect=mock_rds.mutate), \
         patch("services.rds_client.execute_transaction", side_effect=mock_rds.execute_transaction), \
         patch("services.rds_client.check_rds_health", return_value=True):
        yield mock_client


# ── Global Test Cleansing & Limiter Reset ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state_and_rate_limits():
    """Reset slowapi limiter storage and clear dependency overrides between tests."""
    limiter.reset()
    yield
    app.dependency_overrides.clear()
    limiter.reset()


@pytest.fixture(autouse=True)
def _mock_default_rds_health():
    """Mock RDS health check to return True by default so tests don't make real network calls."""
    with patch("services.rds_client.check_rds_health", return_value=True), \
         patch("main.check_rds_health", return_value=True):
        yield


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
