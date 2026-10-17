"""Amazon RDS PostgreSQL connection and query layer.

Authoritative application-data database layer for Amazon RDS PostgreSQL 17.11 (database: interview_prep_db).
Supports credential resolution via AWS Secrets Manager using EC2 IAM role,
as well as local/test server-side DATABASE_URL override.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional
from urllib.parse import quote_plus, urlparse

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Base exception for database layer failures."""
    pass


class DatabaseConnectionError(DatabaseError):
    """Raised when connecting to the database or acquiring a connection fails."""
    pass


class DatabaseQueryError(DatabaseError):
    """Raised when executing a query or mutation fails."""
    pass


def mask_db_url(url: str) -> str:
    """Mask credentials in a PostgreSQL connection string for safe logging."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if "@" in parsed.netloc:
            userinfo, hostport = parsed.netloc.rsplit("@", 1)
            if ":" in userinfo:
                username, _ = userinfo.split(":", 1)
                masked_netloc = f"{username}:****@{hostport}"
                return parsed._replace(netloc=masked_netloc).geturl()
            else:
                return parsed._replace(netloc=f":****@{hostport}").geturl()
    except Exception:
        pass
    return re.sub(r"(://|^)([^:@]*):([^@]+)@", r"\1\2:****@", url)


def get_rds_credentials() -> dict[str, Any]:
    """Resolve database connection parameters from environment or AWS Secrets Manager.

    Priority:
    1. DATABASE_URL / RDS_DATABASE_URL environment variable (local dev, CI/CD, tests)
    2. AWS Secrets Manager secret (identified by RDS_SECRET_ARN or RDS_SECRET_NAME)
    """
    # 1. Local / CI / Test override
    direct_url = os.getenv("DATABASE_URL") or os.getenv("RDS_DATABASE_URL")
    if direct_url and direct_url.strip():
        clean_url = direct_url.strip()
        return {
            "connection_url": clean_url,
            "source": "DATABASE_URL",
            "masked_url": mask_db_url(clean_url),
        }

    # 2. Production AWS Secrets Manager resolution
    secret_id = (
        os.getenv("RDS_SECRET_ARN")
        or os.getenv("RDS_SECRET_NAME")
        or "interview-prep/rds/app"
    ).strip()

    # Extract region from ARN if provided, else check env, default to ap-south-2 (target region)
    arn_region = None
    if secret_id.startswith("arn:aws:secretsmanager:"):
        arn_parts = secret_id.split(":")
        if len(arn_parts) >= 4 and arn_parts[3]:
            arn_region = arn_parts[3]

    region = (
        os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or arn_region
        or "ap-south-2"
    ).strip()

    if not region:
        raise DatabaseConnectionError("AWS region cannot be empty. Configure AWS_REGION or use a valid secret ARN.")

    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_id)
        secret_str = response.get("SecretString")
        if not secret_str:
            raise DatabaseConnectionError(
                f"Secrets Manager secret '{secret_id}' contains no SecretString."
            )

        secret_data = json.loads(secret_str)
        username = secret_data.get("username") or secret_data.get("user") or "interview_prep_app"
        password = secret_data.get("password") or ""
        host = secret_data.get("host") or "localhost"
        port = int(secret_data.get("port", 5432))
        dbname = secret_data.get("dbname") or secret_data.get("database") or "interview_prep_db"

        safe_user = quote_plus(str(username))
        safe_pass = quote_plus(str(password))
        conn_url = f"postgresql://{safe_user}:{safe_pass}@{host}:{port}/{dbname}"

        logger.info(
            "Resolved RDS credentials from Secrets Manager secret '%s' in region '%s'",
            secret_id,
            region,
        )

        return {
            "connection_url": conn_url,
            "source": "SECRETS_MANAGER",
            "masked_url": mask_db_url(conn_url),
            "host": host,
            "port": port,
            "dbname": dbname,
            "username": username,
            "region": region,
        }
    except ImportError as err:
        logger.error("boto3 is required for AWS Secrets Manager integration: %s", err)
        raise DatabaseConnectionError("boto3 is not installed; cannot resolve AWS Secrets.") from err
    except Exception as exc:
        logger.error(
            "Failed to retrieve RDS credentials from Secrets Manager (%s): %s",
            secret_id,
            type(exc).__name__,
        )
        raise DatabaseConnectionError(
            f"Failed to resolve RDS secret '{secret_id}': {type(exc).__name__}"
        ) from exc


class RDSConnectionPoolManager:
    """Thread-safe connection pool manager for Amazon RDS PostgreSQL."""

    _instance: Optional[RDSConnectionPoolManager] = None
    _lock = threading.Lock()

    def __init__(self, minconn: Optional[int] = None, maxconn: Optional[int] = None):
        try:
            self.minconn = minconn or max(1, int(os.getenv("RDS_POOL_MIN", "2")))
        except ValueError:
            self.minconn = 2
        try:
            self.maxconn = maxconn or max(self.minconn, int(os.getenv("RDS_POOL_MAX", "10")))
        except ValueError:
            self.maxconn = 10
        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._pool_lock = threading.Lock()
        self._config: Optional[dict[str, Any]] = None

    @classmethod
    def get_instance(cls) -> RDSConnectionPoolManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (primarily for tests)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def initialize(self) -> None:
        """Initialize connection pool if not already initialized."""
        if self._pool is not None:
            return

        with self._pool_lock:
            if self._pool is not None:
                return

            self._config = get_rds_credentials()
            conn_url = self._config["connection_url"]

            try:
                self._pool = pool.ThreadedConnectionPool(
                    minconn=self.minconn,
                    maxconn=self.maxconn,
                    dsn=conn_url,
                    cursor_factory=RealDictCursor,
                )
                logger.info(
                    "Initialized RDS PostgreSQL connection pool (min=%d, max=%d) -> %s",
                    self.minconn,
                    self.maxconn,
                    self._config.get("masked_url"),
                )
            except Exception as exc:
                logger.error("Failed to connect to RDS PostgreSQL: %s", type(exc).__name__)
                raise DatabaseConnectionError(
                    f"Unable to establish RDS connection pool: {type(exc).__name__}"
                ) from exc

    @contextmanager
    def get_connection(self) -> Generator[Any, None, None]:
        """Context manager yielding an active connection from the pool."""
        self.initialize()
        assert self._pool is not None

        conn = None
        try:
            conn = self._pool.getconn()
            if conn.closed:
                # Discard dead connection and reacquire
                try:
                    self._pool.putconn(conn, close=True)
                except Exception:
                    pass
                conn = self._pool.getconn()
            yield conn
        except pool.PoolError as exc:
            logger.error("RDS connection pool exhausted (maxconn=%d): %s", self.maxconn, exc)
            raise DatabaseConnectionError(f"RDS connection pool exhausted: {exc}") from exc
        except Exception as exc:
            if conn and not conn.closed:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn and self._pool and not conn.closed:
                self._pool.putconn(conn)

    @contextmanager
    def get_cursor(self, commit: bool = False) -> Generator[RealDictCursor, None, None]:
        """Context manager yielding a RealDictCursor with optional auto-commit."""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception:
                if not conn.closed:
                    conn.rollback()
                raise
            finally:
                cursor.close()

    def execute_query(
        self,
        query: str,
        params: Optional[tuple | list | dict] = None,
        fetch: str = "all",
    ) -> Any:
        """Execute a read query and return dictionary rows."""
        with self.get_cursor(commit=False) as cursor:
            try:
                cursor.execute(query, params)
                if fetch == "all":
                    return [dict(row) for row in cursor.fetchall()]
                elif fetch == "one":
                    row = cursor.fetchone()
                    return dict(row) if row else None
                elif fetch == "scalar":
                    row = cursor.fetchone()
                    if row:
                        return next(iter(row.values()))
                    return None
                return None
            except Exception as exc:
                logger.error("Query execution error: %s [Query: %s]", exc, query[:200])
                raise DatabaseQueryError(f"Database query failed: {exc}") from exc

    def execute_mutation(
        self,
        query: str,
        params: Optional[tuple | list | dict] = None,
        returning: bool = False,
    ) -> Any:
        """Execute an INSERT, UPDATE, or DELETE inside a transaction."""
        with self.get_cursor(commit=True) as cursor:
            try:
                cursor.execute(query, params)
                if returning:
                    rows = cursor.fetchall()
                    return [dict(r) for r in rows]
                return cursor.rowcount
            except Exception as exc:
                logger.error("Mutation execution error: %s [Query: %s]", exc, query[:200])
                raise DatabaseQueryError(f"Database mutation failed: {exc}") from exc

    def check_health(self) -> bool:
        """Check database health by running SELECT 1."""
        try:
            val = self.execute_query("SELECT 1 AS healthy;", fetch="scalar")
            return val == 1
        except Exception as exc:
            logger.warning("RDS health check failed: %s", type(exc).__name__)
            return False

    def close(self) -> None:
        """Close the connection pool."""
        with self._pool_lock:
            if self._pool is not None:
                try:
                    self._pool.closeall()
                except Exception:
                    pass
                self._pool = None


# Module-level convenience functions
def get_db_pool() -> RDSConnectionPoolManager:
    return RDSConnectionPoolManager.get_instance()


def query(sql: str, params: Optional[tuple | list | dict] = None, fetch: str = "all") -> Any:
    return get_db_pool().execute_query(sql, params, fetch=fetch)


def mutate(sql: str, params: Optional[tuple | list | dict] = None, returning: bool = False) -> Any:
    return get_db_pool().execute_mutation(sql, params, returning=returning)


def check_rds_health() -> bool:
    return get_db_pool().check_health()
