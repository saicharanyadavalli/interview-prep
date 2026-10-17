"""Regression tests verifying RDS application database isolation and connection robustness."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from main import app
from routes.auth import get_current_user
from services.rds_client import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RDSConnectionPoolManager,
)


def test_rds_pool_putconn_closes_broken_connection():
    """Verify that when a leased connection becomes closed, putconn is called with close=True."""
    mgr = RDSConnectionPoolManager()
    mgr._pool = MagicMock()

    mock_conn = MagicMock()
    mock_conn.closed = 0
    mgr._pool.getconn.return_value = mock_conn

    with mgr.get_connection() as conn:
        assert conn is mock_conn
        # Connection becomes closed during execution
        conn.closed = 1

    # Check putconn was invoked with close=True in finally
    mgr._pool.putconn.assert_called_once_with(mock_conn, close=True)


def test_rds_pool_putconn_returns_healthy_connection():
    """Verify that healthy active connections are returned to the pool with close=False."""
    mgr = RDSConnectionPoolManager()
    mgr._pool = MagicMock()

    mock_conn = MagicMock()
    mock_conn.closed = 0  # connection is active and healthy
    mgr._pool.getconn.return_value = mock_conn

    with mgr.get_connection() as conn:
        assert conn is mock_conn

    mgr._pool.putconn.assert_called_once_with(mock_conn, close=False)


def test_rds_pool_operational_error_raises_database_connection_error():
    """Verify that OperationalError when creating pool raises DatabaseConnectionError."""
    import psycopg2
    mgr = RDSConnectionPoolManager()
    mgr._pool = None

    with patch("psycopg2.pool.ThreadedConnectionPool", side_effect=psycopg2.OperationalError("could not connect to server: Connection refused")):
        with patch("services.rds_client.get_rds_credentials", return_value={"connection_url": "postgresql://mock", "masked_url": "postgresql://mock", "region": "ap-south-2"}):
            with pytest.raises(DatabaseConnectionError) as exc_info:
                mgr.initialize()
            assert "Unable to establish RDS connection pool" in str(exc_info.value)


def test_profile_me_rds_failure_never_falls_back_to_supabase():
    """Architectural invariant: when RDS query fails on /profile/me, backend returns 500

    and NEVER invokes supabase.table or any Supabase database fallback.
    """
    client = TestClient(app)
    mock_user = {
        "id": "test-user-uuid-1234",
        "email": "test@example.com",
        "username": "testuser",
        "name": "Test User",
    }

    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with patch("routes.profile.rds_client.query", side_effect=DatabaseQueryError("RDS unreachable")):
            with patch("services.supabase_client.get_supabase_client") as mock_supabase_getter:
                response = client.get("/profile/me")
                # Must return error, NOT fallback to Supabase table
                assert response.status_code in (500, 503)
                # Ensure get_supabase_client was NOT called to fetch table data
                mock_supabase_getter.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_progress_update_rds_failure_never_falls_back_to_supabase():
    """Architectural invariant: when RDS mutation fails on /progress/update, backend returns 500

    and NEVER attempts Supabase DB fallback.
    """
    client = TestClient(app)
    mock_user = {
        "id": "test-user-uuid-1234",
        "email": "test@example.com",
    }

    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with patch("routes.progress.rds_client.mutate", side_effect=DatabaseQueryError("RDS error")):
            with patch("services.supabase_client.get_supabase_client") as mock_supabase_getter:
                response = client.post(
                    "/progress/update",
                    json={"qnum": 1, "is_solved": True, "revisit": False},
                )
                assert response.status_code in (500, 503)
                mock_supabase_getter.assert_not_called()
    finally:
        app.dependency_overrides.clear()


def test_user_profile_update_enforces_current_user_isolation():
    """Security check: user profile update strictly binds current_user.id and cannot update other users."""
    client = TestClient(app)
    mock_user = {
        "id": "legitimate-user-id",
        "email": "legit@example.com",
        "username": "legit",
    }

    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        updated_row = {
            "id": "legitimate-user-id",
            "name": "New Name",
            "email": "legit@example.com",
            "username": "legit",
            "phone": "1234567890",
            "avatar_url": "",
        }
        with patch("routes.profile.rds_client.mutate", return_value=[updated_row]) as mock_mutate:
            with patch("routes.profile.rds_client.query", return_value=updated_row):
                response = client.put(
                    "/profile/me",
                    json={"name": "New Name", "phone": "1234567890"},
                )
                assert response.status_code == 200
                # Inspect SQL arguments passed to mutate
                call_args = mock_mutate.call_args
                sql_query, sql_params = call_args[0]
                assert "WHERE id = %s" in sql_query
                # Ensure the bound parameter is the authenticated user's ID
                assert "legitimate-user-id" in sql_params
    finally:
        app.dependency_overrides.clear()
