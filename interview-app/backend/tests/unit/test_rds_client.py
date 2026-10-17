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
    url = "postgresql://my_user:super_secret_pw123!@rds-endpoint.us-east-1.rds.amazonaws.com:5432/interview_prep_db"
    masked = mask_db_url(url)
    assert "super_secret_pw123!" not in masked
    assert "my_user" in masked
    assert "rds-endpoint.us-east-1.rds.amazonaws.com" in masked
    assert "interview_prep_db" in masked
    assert "****" in masked


def test_mask_db_url_empty_or_safe():
    """Verify mask_db_url safely handles empty strings or strings without passwords."""
    assert mask_db_url("") == ""
    assert mask_db_url("postgresql://localhost:5432/db") == "postgresql://localhost:5432/db"


def test_get_rds_credentials_from_database_url_env(monkeypatch):
    """Verify get_rds_credentials prioritizes DATABASE_URL environment variable."""
    test_url = "postgresql://app_user:testpass@localhost:5432/interview_prep_db"
    monkeypatch.setenv("DATABASE_URL", test_url)

    creds = get_rds_credentials()
    assert creds["source"] == "DATABASE_URL"
    assert creds["connection_url"] == test_url
    assert "testpass" not in creds["masked_url"]


def test_get_rds_credentials_from_secrets_manager(monkeypatch):
    """Verify get_rds_credentials resolves credentials from AWS Secrets Manager."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RDS_DATABASE_URL", raising=False)
    monkeypatch.setenv("RDS_SECRET_NAME", "interview-prep/rds/app")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    secret_payload = json.dumps({
        "username": "interview_prep_app",
        "password": "RdsSecurePassword456!",
        "host": "test-rds.cluster-xyz.us-east-1.rds.amazonaws.com",
        "port": 5432,
        "dbname": "interview_prep_db",
    })

    mock_boto_client = MagicMock()
    mock_boto_client.get_secret_value.return_value = {"SecretString": secret_payload}

    with patch("boto3.client", return_value=mock_boto_client):
        creds = get_rds_credentials()
        assert creds["source"] == "SECRETS_MANAGER"
        assert creds["username"] == "interview_prep_app"
        assert creds["host"] == "test-rds.cluster-xyz.us-east-1.rds.amazonaws.com"
        assert "RdsSecurePassword456!" not in creds["masked_url"]
        assert creds["connection_url"].startswith("postgresql://interview_prep_app:")


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
