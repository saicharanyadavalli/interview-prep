"""Unit tests for services.leetcode_sync_service."""

from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional
import pytest

from services.leetcode_parser import ParsedApproach, ParsedProblem
from services.leetcode_sync_service import LeetCodeSyncService


class MockCursor:
    """Mock database cursor that records executed queries and returns simulated rows."""

    def __init__(self, handlers: Optional[Dict[str, Any]] = None) -> None:
        self.executed: List[tuple[str, Any]] = []
        self.handlers = handlers or {}
        self._current_results: List[Any] = []
        self._idx = 0
        self.description = None

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        normalized = " ".join(sql.split())

        matched = False
        for pattern, handler in self.handlers.items():
            if pattern in normalized:
                res = handler(normalized, params) if callable(handler) else handler
                self._current_results = list(res) if isinstance(res, (list, tuple)) else ([res] if res is not None else [])
                self._idx = 0
                matched = True
                break

        if not matched:
            self._current_results = []
            self._idx = 0

    def fetchone(self) -> Any:
        if self._idx < len(self._current_results):
            r = self._current_results[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self) -> List[Any]:
        res = self._current_results[self._idx :]
        self._idx = len(self._current_results)
        return res

    def close(self) -> None:
        pass


class MockConnection:
    """Mock database connection supporting commit and rollback tracking."""

    def __init__(self, cursor: MockCursor) -> None:
        self.cur = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, cursor_factory: Any = None) -> MockCursor:
        return self.cur

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class MockRDSClient:
    """Mock RDS client module exposing get_connection context manager."""

    def __init__(self, conn: MockConnection) -> None:
        self.conn = conn

    @contextmanager
    def get_connection(self):
        yield self.conn

    def execute_query(self, sql: str, params: Any = None, fetch: str = "all") -> Any:
        self.conn.cur.execute(sql, params)
        if fetch == "all":
            return self.conn.cur.fetchall()
        elif fetch == "one":
            return self.conn.cur.fetchone()
        elif fetch == "scalar":
            r = self.conn.cur.fetchone()
            return next(iter(r.values())) if isinstance(r, dict) else (r[0] if r else None)
        return None

    def execute_mutation(self, sql: str, params: Any = None) -> int:
        self.conn.cur.execute(sql, params)
        return 1


@pytest.fixture
def sample_problem() -> ParsedProblem:
    return ParsedProblem(
        qnum=1,
        title="Two Sum",
        slug="two-sum",
        difficulty="Easy",
        topic_tags=["Array", "Hash Table"],
        description_md="Given an array of integers nums and an integer target...",
        approaches=[
            ParsedApproach(
                approach_index=1,
                title="Hash Table",
                intuition_md="Use a hash table to find complement.",
                time_complexity="$O(n)$",
                space_complexity="$O(n)$",
                explanation_md="Full explanation...",
            )
        ],
        code_solutions={
            "python": "class Solution: ...",
            "java": "class Solution { ... }",
        },
    )


def test_sync_problem_validation_error():
    """Verify sync_problem returns error status when problem validation fails."""
    invalid_prob = ParsedProblem(
        qnum=0,  # Invalid qnum <= 0
        title="",
        slug="",
        difficulty="Invalid",
    )
    cursor = MockCursor()
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(invalid_prob)
    assert res["status"] == "error"
    assert "Validation failed" in res["details"]
    assert len(cursor.executed) == 0


def test_sync_problem_insert_new(sample_problem):
    """Verify new problem is inserted with approaches and solutions inside a transaction."""
    cursor = MockCursor(
        handlers={
            # Slug collision check returns None
            "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s": None,
            # Problem lookup returns None (new problem)
            "SELECT qnum, title, slug, difficulty, topic_tags, description_md FROM public.leetcode_problems WHERE qnum = %s": None,
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(sample_problem, dry_run=False)

    assert res["status"] == "added"
    assert res["qnum"] == 1
    assert conn.committed is True
    assert conn.rolled_back is False

    # Verify executed SQL mutations
    sql_texts = [sql for sql, _ in cursor.executed]
    assert any("INSERT INTO public.leetcode_problems" in s for s in sql_texts)
    assert any("INSERT INTO public.leetcode_approaches" in s for s in sql_texts)
    assert any("DELETE FROM public.leetcode_approaches WHERE qnum = %s AND approach_index > %s" in s for s in sql_texts)
    assert any("INSERT INTO public.leetcode_code_solutions" in s for s in sql_texts)
    assert any("DELETE FROM public.leetcode_code_solutions WHERE qnum = %s AND NOT (language = ANY(%s))" in s for s in sql_texts)


def test_sync_problem_update_existing(sample_problem):
    """Verify existing problem with updated title or tags produces 'updated' status."""
    existing_row = {
        "qnum": 1,
        "title": "Old Two Sum Title",  # Differs from sample_problem.title
        "slug": "two-sum",
        "difficulty": "Easy",
        "topic_tags": ["Array"],  # Differs
        "description_md": sample_problem.description_md,
    }
    existing_approaches = [
        {
            "approach_index": 1,
            "title": "Hash Table",
            "intuition_md": "Use a hash table to find complement.",
            "time_complexity": "$O(n)$",
            "space_complexity": "$O(n)$",
            "explanation_md": "Full explanation...",
        }
    ]
    existing_solutions = [
        {"language": "python", "code_content": "class Solution: ..."},
        {"language": "java", "code_content": "class Solution { ... }"},
    ]

    cursor = MockCursor(
        handlers={
            "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s": None,
            "SELECT qnum, title, slug, difficulty, topic_tags, description_md FROM public.leetcode_problems WHERE qnum = %s": existing_row,
            "SELECT approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md FROM public.leetcode_approaches": existing_approaches,
            "SELECT language, code_content FROM public.leetcode_code_solutions": existing_solutions,
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(sample_problem, dry_run=False)

    assert res["status"] == "updated"
    assert "title" in res["details"] or "topic_tags" in res["details"]
    assert conn.committed is True


def test_sync_problem_unchanged(sample_problem):
    """Verify problem with identical attributes produces 'unchanged' status."""
    existing_row = {
        "qnum": 1,
        "title": "Two Sum",
        "slug": "two-sum",
        "difficulty": "Easy",
        "topic_tags": ["Array", "Hash Table"],
        "description_md": sample_problem.description_md,
    }
    existing_approaches = [
        {
            "approach_index": 1,
            "title": "Hash Table",
            "intuition_md": "Use a hash table to find complement.",
            "time_complexity": "$O(n)$",
            "space_complexity": "$O(n)$",
            "explanation_md": "Full explanation...",
        }
    ]
    existing_solutions = [
        {"language": "python", "code_content": "class Solution: ..."},
        {"language": "java", "code_content": "class Solution { ... }"},
    ]

    cursor = MockCursor(
        handlers={
            "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s": None,
            "SELECT qnum, title, slug, difficulty, topic_tags, description_md FROM public.leetcode_problems WHERE qnum = %s": existing_row,
            "SELECT approach_index, title, intuition_md, time_complexity, space_complexity, explanation_md FROM public.leetcode_approaches": existing_approaches,
            "SELECT language, code_content FROM public.leetcode_code_solutions": existing_solutions,
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(sample_problem, dry_run=False)

    assert res["status"] == "unchanged"
    assert conn.committed is True


def test_sync_problem_dry_run_modes(sample_problem):
    """Verify dry_run=True performs inspections without executing any INSERT/UPDATE/DELETE mutations."""
    # 1. Non-existent problem -> would be added
    cursor_new = MockCursor(handlers={"SELECT": None})
    conn_new = MockConnection(cursor_new)
    service_new = LeetCodeSyncService(rds_client_module=MockRDSClient(conn_new))

    res_add = service_new.sync_problem(sample_problem, dry_run=True)
    assert res_add["status"] == "added"
    assert conn_new.committed is False
    assert not any("INSERT" in s or "UPDATE" in s or "DELETE" in s for s, _ in cursor_new.executed)

    # 2. Existing modified problem -> would be updated
    existing_row = {
        "qnum": 1,
        "title": "Different Title",
        "slug": "two-sum",
        "difficulty": "Easy",
        "topic_tags": ["Array"],
        "description_md": sample_problem.description_md,
    }
    cursor_mod = MockCursor(
        handlers={
            "SELECT qnum FROM public.leetcode_problems WHERE slug": None,
            "SELECT qnum, title": existing_row,
            "SELECT approach_index": [],
            "SELECT language": [],
        }
    )
    conn_mod = MockConnection(cursor_mod)
    service_mod = LeetCodeSyncService(rds_client_module=MockRDSClient(conn_mod))

    res_upd = service_mod.sync_problem(sample_problem, dry_run=True)
    assert res_upd["status"] == "updated"
    assert conn_mod.committed is False
    assert not any("INSERT" in s or "UPDATE" in s or "DELETE" in s for s, _ in cursor_mod.executed)


def test_sync_problem_slug_collision_sanitized(sample_problem):
    """Verify that if slug collides with a different question, slug is suffixed with qnum."""
    # Simulate slug conflict with question 99
    def slug_check_handler(sql, params):
        slug, qnum = params
        if slug == "two-sum" and qnum != 99:
            return {"qnum": 99}  # Another question holds 'two-sum'
        return None  # 'two-sum-1' is free

    cursor = MockCursor(
        handlers={
            "SELECT qnum FROM public.leetcode_problems WHERE slug = %s AND qnum != %s": slug_check_handler,
            "SELECT qnum, title, slug, difficulty, topic_tags, description_md FROM public.leetcode_problems WHERE qnum = %s": None,
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(sample_problem, dry_run=False)
    assert res["status"] == "added"

    # Find the problem insert statement
    prob_insert = next(
        params for sql, params in cursor.executed if "INSERT INTO public.leetcode_problems" in sql
    )
    # Target slug must be two-sum-1
    assert prob_insert[2] == "two-sum-1"


def test_sync_problem_preserves_user_tables(sample_problem):
    """Ensure no operations touch user_progress, user_comments, custom_folders, or delete master problems."""
    cursor = MockCursor(handlers={"SELECT": None})
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    service.sync_problem(sample_problem, dry_run=False)

    for sql, _ in cursor.executed:
        lower_sql = sql.lower()
        assert "user_progress" not in lower_sql
        assert "user_comments" not in lower_sql
        assert "user_custom_folders" not in lower_sql
        assert "practice_history" not in lower_sql
        assert "user_profiles" not in lower_sql
        assert "delete from public.leetcode_problems" not in lower_sql


def test_sync_problem_rollback_on_error(sample_problem):
    """Verify transaction is rolled back when a mutation fails."""
    cursor = MockCursor(handlers={"SELECT": None})

    # Intercept execute to simulate a DB query failure
    orig_execute = cursor.execute

    def failing_execute(sql, params=None):
        if "INSERT INTO public.leetcode_approaches" in sql:
            raise RuntimeError("Database write disk error")
        return orig_execute(sql, params)

    cursor.execute = failing_execute
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    res = service.sync_problem(sample_problem, dry_run=False)
    assert res["status"] == "error"
    assert "Database write disk error" in res["details"]
    assert conn.rolled_back is True
    assert conn.committed is False


def test_record_sync_start():
    """Verify record_sync_start writes in_progress entry to leetcode_sync_history."""
    cursor = MockCursor()
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    service.record_sync_start(
        delivery_id="deliv-abc-123",
        commit_sha="commit-sha-999",
        repo="doocs/leetcode",
        branch="main",
    )

    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert "INSERT INTO public.leetcode_sync_history" in sql
    assert params == ("deliv-abc-123", "doocs/leetcode", "main", "commit-sha-999")


def test_record_sync_completion_success():
    """Verify record_sync_completion updates history and updates state on success."""
    cursor = MockCursor(
        handlers={
            "SELECT source_repo, source_branch FROM public.leetcode_sync_history": {
                "source_repo": "doocs/leetcode",
                "source_branch": "main",
            }
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    service.record_sync_completion(
        delivery_id="deliv-abc-123",
        commit_sha="commit-sha-999",
        status="success",
        files_processed=50,
        files_added=20,
        files_updated=30,
        files_ignored=0,
        files_failed=0,
    )

    sql_texts = [sql for sql, _ in cursor.executed]
    assert any("UPDATE public.leetcode_sync_history" in s for s in sql_texts)
    assert any("INSERT INTO public.leetcode_sync_state" in s for s in sql_texts)


def test_record_sync_completion_failed():
    """Verify record_sync_completion on failure does NOT update leetcode_sync_state."""
    cursor = MockCursor()
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    service.record_sync_completion(
        delivery_id="deliv-fail-456",
        commit_sha="commit-fail-000",
        status="failed",
        files_processed=10,
        files_added=2,
        files_updated=1,
        files_ignored=0,
        files_failed=7,
        error_summary="Timeout reaching GitHub raw API",
    )

    sql_texts = [sql for sql, _ in cursor.executed]
    assert any("UPDATE public.leetcode_sync_history" in s for s in sql_texts)
    assert not any("leetcode_sync_state" in s for s in sql_texts)


def test_get_last_sync_sha():
    """Verify get_last_sync_sha retrieves last recorded commit sha."""
    cursor = MockCursor(
        handlers={
            "SELECT last_sync_commit_sha FROM public.leetcode_sync_state": {
                "last_sync_commit_sha": "git-sha-fedcba9876543210"
            }
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    sha = service.get_last_sync_sha("doocs/leetcode", "main")
    assert sha == "git-sha-fedcba9876543210"

    # When not found
    cursor_none = MockCursor(handlers={"SELECT last_sync_commit_sha": None})
    conn_none = MockConnection(cursor_none)
    service_none = LeetCodeSyncService(rds_client_module=MockRDSClient(conn_none))
    assert service_none.get_last_sync_sha("doocs/leetcode", "dev") is None


def test_get_delivery_status():
    """Verify get_delivery_status queries leetcode_sync_history for status."""
    cursor = MockCursor(
        handlers={
            "SELECT status FROM public.leetcode_sync_history WHERE delivery_id = %s;": {
                "status": "success"
            }
        }
    )
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    status = service.get_delivery_status("del-12345")
    assert status == "success"
    assert len(cursor.executed) == 1
    assert cursor.executed[0][1] == ("del-12345",)

    # When not found
    cursor_missing = MockCursor(handlers={"SELECT status FROM public.leetcode_sync_history": None})
    conn_missing = MockConnection(cursor_missing)
    service_missing = LeetCodeSyncService(rds_client_module=MockRDSClient(conn_missing))
    assert service_missing.get_delivery_status("del-nonexistent") is None


def test_record_sync_start_preserves_existing_success():
    """Verify record_sync_start query includes CASE WHEN status = 'success' to guard idempotency."""
    cursor = MockCursor()
    conn = MockConnection(cursor)
    service = LeetCodeSyncService(rds_client_module=MockRDSClient(conn))

    service.record_sync_start("del-abc", "sha-123", "doocs/leetcode", "main")
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    normalized_sql = " ".join(sql.split())
    assert "INSERT INTO public.leetcode_sync_history" in normalized_sql
    assert "CASE WHEN public.leetcode_sync_history.status = 'success'" in normalized_sql
    assert params == ("del-abc", "doocs/leetcode", "main", "sha-123")
