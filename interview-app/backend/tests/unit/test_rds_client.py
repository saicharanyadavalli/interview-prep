"""Unit tests for services.rds_client database connection and query layer."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from services.rds_client import (
    DatabaseConnectionError,
    DatabaseQueryError,
    RDSConnectionPoolManager,
    get_rds_credentials,
    mask_db_url,
)


def test_mask_db_url_masks_password():
    """Verify mask_db_url removes plain text passwords from connection strings."""
    dummy_pass = "synthetic_dummy_pw_not_real"
    url = f"postgresql://test_user:{dummy_pass}@db.example.invalid:5432/interview_prep_test_db"
    masked = mask_db_url(url)
    assert dummy_pass not in masked
    assert "test_user" in masked
    assert "db.example.invalid:5432" in masked
    assert "interview_prep_test_db" in masked
    assert "****" in masked


def test_mask_db_url_encoded_password():
    """Verify mask_db_url masks percent-encoded passwords."""
    url = "postgresql://test_user:p%40ss%21word@db.example.invalid:5432/test_db"
    masked = mask_db_url(url)
    assert "p%40ss%21word" not in masked
    assert "p@ss!word" not in masked
    assert "test_user" in masked
    assert "****" in masked


def test_mask_db_url_password_without_username():
    """Verify mask_db_url masks password even when username is omitted."""
    url = "postgresql://:dummy_pass@db.example.invalid:5432/test_db"
    masked = mask_db_url(url)
    assert "dummy_pass" not in masked
    assert "****" in masked
    assert "db.example.invalid" in masked


def test_mask_db_url_preserves_query_and_fragment():
    """Verify mask_db_url preserves non-secret query params and fragments."""
    url = "postgresql://test_user:dummy_pass@db.example.invalid:5432/test_db?sslmode=require#pool"
    masked = mask_db_url(url)
    assert "dummy_pass" not in masked
    assert "sslmode=require" in masked
    assert "#pool" in masked
    assert "test_user" in masked


def test_mask_db_url_empty_or_safe():
    """Verify mask_db_url safely handles empty strings or strings without passwords."""
    assert mask_db_url("") == ""
    assert mask_db_url("postgresql://localhost:5432/db") == "postgresql://localhost:5432/db"
    assert mask_db_url("postgresql://db.example.invalid:5432/test_db") == "postgresql://db.example.invalid:5432/test_db"


def test_mask_db_url_malformed():
    """Verify mask_db_url safely handles malformed strings without raising exceptions."""
    assert mask_db_url("not_a_valid_url") == "not_a_valid_url"
    assert "****" in mask_db_url("postgresql://test_user:dummy_pass@")


def test_get_rds_credentials_from_database_url_env(monkeypatch):
    """Verify get_rds_credentials prioritizes DATABASE_URL environment variable."""
    test_url = "postgresql://test_user:test_dummy_pass@localhost:5432/interview_prep_test_db"
    monkeypatch.setenv("DATABASE_URL", test_url)

    creds = get_rds_credentials()
    assert creds["source"] == "DATABASE_URL"
    assert creds["connection_url"] == test_url
    assert "test_dummy_pass" not in creds["masked_url"]


def test_get_rds_credentials_from_secrets_manager(monkeypatch):
    """Verify get_rds_credentials resolves credentials from AWS Secrets Manager."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    monkeypatch.setenv("RDS_SECRET_NAME", "interview-prep/rds/app")
    monkeypatch.setenv("AWS_REGION", "ap-south-2")

    secret_payload = json.dumps({
        "username": "test_app_user",
        "password": "synthetic_mock_pw_789",
        "host": "db.example.invalid",
        "port": 5432,
        "dbname": "interview_prep_test_db",
    })

    mock_boto_client = MagicMock()
    mock_boto_client.get_secret_value.return_value = {"SecretString": secret_payload}

    with patch("boto3.client", return_value=mock_boto_client):
        creds = get_rds_credentials()
        assert creds["source"] == "SECRETS_MANAGER"
        assert creds["username"] == "test_app_user"
        assert creds["host"] == "db.example.invalid"
        assert "synthetic_mock_pw_789" not in creds["masked_url"]
        assert creds["connection_url"].startswith("postgresql://test_app_user:")


def test_get_rds_credentials_missing_secret_raises_error(monkeypatch):
    """Verify get_rds_credentials raises DatabaseConnectionError when secret cannot be retrieved."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)

    mock_boto_client = MagicMock()
    mock_boto_client.get_secret_value.side_effect = Exception("ResourceNotFoundException")

    with patch("boto3.client", return_value=mock_boto_client):
        with pytest.raises(DatabaseConnectionError) as exc_info:
            get_rds_credentials()
        assert "Failed to resolve RDS secret" in str(exc_info.value)


def test_rds_pool_execute_query_error_handling():
    """Verify execute_query wraps psycopg2 errors in DatabaseQueryError."""
    pool_mgr = RDSConnectionPoolManager()

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("syntax error at or near 'INVALID'")

    with patch.object(pool_mgr, "get_cursor") as mock_get_cursor:
        mock_get_cursor.return_value.__enter__.return_value = mock_cursor
        with pytest.raises(DatabaseQueryError) as exc_info:
            pool_mgr.execute_query("INVALID SQL SYNTAX;")
        assert "Database query failed" in str(exc_info.value)


def test_rds_pool_execute_mutation_error_handling():
    """Verify execute_mutation wraps psycopg2 errors in DatabaseQueryError and rolls back."""
    pool_mgr = RDSConnectionPoolManager()

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("violates foreign key constraint")

    with patch.object(pool_mgr, "get_cursor") as mock_get_cursor:
        mock_get_cursor.return_value.__enter__.return_value = mock_cursor
        with pytest.raises(DatabaseQueryError) as exc_info:
            pool_mgr.execute_mutation("INSERT INTO missing_table VALUES (1);")
        assert "Database mutation failed" in str(exc_info.value)


def test_rds_pool_check_health_true():
    """Verify check_health returns True when SELECT 1 succeeds."""
    pool_mgr = RDSConnectionPoolManager()
    with patch.object(pool_mgr, "execute_query", return_value=1):
        assert pool_mgr.check_health() is True


def test_rds_pool_check_health_false():
    """Verify check_health returns False when database is unreachable."""
    pool_mgr = RDSConnectionPoolManager()
    with patch.object(pool_mgr, "execute_query", side_effect=Exception("Connection refused")):
        assert pool_mgr.check_health() is False


def test_get_rds_credentials_default_region_is_ap_south_2(monkeypatch):
    """Verify get_rds_credentials defaults to ap-south-2 when AWS_REGION is unset."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("RDS_SECRET_NAME", "interview-prep/rds/app")

    secret_payload = json.dumps({"username": "test_user", "password": "dummy_password", "host": "db.example.invalid", "port": 5432, "dbname": "test_db"})
    mock_boto = MagicMock()
    mock_boto.get_secret_value.return_value = {"SecretString": secret_payload}

    with patch("boto3.client") as mock_client_factory:
        mock_client_factory.return_value = mock_boto
        creds = get_rds_credentials()
        assert creds["region"] == "ap-south-2"
        mock_client_factory.assert_called_with("secretsmanager", region_name="ap-south-2")


def test_get_rds_credentials_extracts_region_from_arn(monkeypatch):
    """Verify get_rds_credentials extracts region directly from RDS_SECRET_ARN."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    arn = "arn:aws:secretsmanager:ap-south-2:123456789012:secret:interview-prep/rds/app-dummy123"
    monkeypatch.setenv("RDS_SECRET_ARN", arn)

    secret_payload = json.dumps({"username": "test_user", "password": "dummy_password", "host": "db.example.invalid", "port": 5432, "dbname": "test_db"})
    mock_boto = MagicMock()
    mock_boto.get_secret_value.return_value = {"SecretString": secret_payload}

    with patch("boto3.client") as mock_client_factory:
        mock_client_factory.return_value = mock_boto
        creds = get_rds_credentials()
        assert creds["region"] == "ap-south-2"
        mock_client_factory.assert_called_with("secretsmanager", region_name="ap-south-2")


def test_rds_pool_custom_min_max_env(monkeypatch):
    """Verify RDSConnectionPoolManager respects RDS_POOL_MIN and RDS_POOL_MAX."""
    monkeypatch.setenv("RDS_POOL_MIN", "4")
    monkeypatch.setenv("RDS_POOL_MAX", "16")
    mgr = RDSConnectionPoolManager()
    assert mgr.minconn == 4
    assert mgr.maxconn == 16


def test_rds_pool_exhausted_raises_database_connection_error():
    """Verify pool.PoolError is converted to DatabaseConnectionError."""
    from psycopg2 import pool as psycopg2_pool
    mgr = RDSConnectionPoolManager()
    mgr._pool = MagicMock()
    mgr._pool.getconn.side_effect = psycopg2_pool.PoolError("connection pool exhausted")

    with pytest.raises(DatabaseConnectionError) as exc_info:
        with mgr.get_connection():
            pass
    assert "connection pool exhausted" in str(exc_info.value).lower()

