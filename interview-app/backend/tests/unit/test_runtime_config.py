"""Unit tests for runtime configuration, environment validation, and secret isolation.

Verifies:
1. Environment variables are correctly read and validated by runtime config schemas.
2. Missing, empty, or placeholder asset configuration is strictly detected and rejected in production/staging mode.
3. Frontend environment templates and container configurations do not leak backend secrets.
4. Docker compose configurations consistently define staging defaults for S3 and CloudFront.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from services import s3_storage_service
from services.s3_storage_service import (
    S3StorageError,
    get_asset_base_url,
    get_s3_bucket,
    get_s3_region,
    reset_s3_client,
    validate_asset_base_url,
    validate_s3_bucket,
)

# Base directories
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


# -----------------------------------------------------------------------------
# RUNTIME CONFIG SCHEMAS (Pydantic V2)
# -----------------------------------------------------------------------------

FORBIDDEN_BASE_URL_PATTERNS = [
    r"d123456abcdef8",
    r"<distribution[-_]id>",
    r"<.*?>",
    r"placeholder",
]


class AssetStorageConfig(BaseModel):
    """Pydantic schema modeling authoritative AWS S3 and CloudFront runtime configuration."""

    model_config = ConfigDict(extra="forbid")

    s3_assets_bucket: str = Field(..., alias="S3_ASSETS_BUCKET")
    s3_assets_region: str = Field(default="ap-south-2", alias="S3_ASSETS_REGION")
    asset_base_url: str = Field(..., alias="ASSET_BASE_URL")
    environment: str = Field(default="production", alias="ENVIRONMENT")

    @field_validator("s3_assets_bucket")
    @classmethod
    def validate_bucket(cls, v: str) -> str:
        clean = (v or "").strip()
        if not clean:
            raise ValueError("S3_ASSETS_BUCKET cannot be empty")
        if "<" in clean or ">" in clean or "placeholder" in clean.lower():
            raise ValueError(f"S3_ASSETS_BUCKET contains invalid placeholder: {clean}")
        if not re.match(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$", clean):
            raise ValueError(f"Invalid S3 bucket name syntax: {clean}")
        return clean

    @field_validator("s3_assets_region")
    @classmethod
    def validate_region(cls, v: str) -> str:
        clean = (v or "").strip()
        if not clean:
            raise ValueError("S3_ASSETS_REGION cannot be empty")
        if not re.match(r"^[a-z]{2}-[a-z]+-\d+$", clean):
            raise ValueError(f"Invalid AWS region syntax: {clean}")
        return clean

    @field_validator("asset_base_url")
    @classmethod
    def validate_base_url(cls, v: str, info) -> str:
        clean = (v or "").strip().rstrip("/")
        if not clean:
            raise ValueError("ASSET_BASE_URL cannot be empty in production/staging")
        if not clean.startswith("https://"):
            raise ValueError(f"ASSET_BASE_URL must use HTTPS protocol: {clean}")
        for pat in FORBIDDEN_BASE_URL_PATTERNS:
            if re.search(pat, clean, re.IGNORECASE):
                raise ValueError(
                    f"ASSET_BASE_URL contains forbidden placeholder pattern '{pat}': {clean}"
                )
        return clean

    @classmethod
    def from_env(cls, env: Optional[Dict[str, str]] = None) -> "AssetStorageConfig":
        """Factory method to construct config directly from environment dict."""
        source = env if env is not None else os.environ
        return cls(
            S3_ASSETS_BUCKET=source.get("S3_ASSETS_BUCKET", ""),
            S3_ASSETS_REGION=source.get("S3_ASSETS_REGION", "ap-south-2"),
            ASSET_BASE_URL=source.get("ASSET_BASE_URL", ""),
            ENVIRONMENT=source.get("ENVIRONMENT", "production"),
        )


# -----------------------------------------------------------------------------
# FIXTURES
# -----------------------------------------------------------------------------

@pytest.fixture
def clean_env():
    """Isolate environment mutations during each test."""
    reset_s3_client()
    tracked_keys = [
        "S3_ASSETS_BUCKET",
        "S3_ASSETS_REGION",
        "AWS_REGION",
        "ASSET_BASE_URL",
        "ENVIRONMENT",
        "APP_ENV",
        "ENV",
        "TESTING",
    ]
    old_values = {k: os.environ.get(k) for k in tracked_keys}
    for k in tracked_keys:
        if k in os.environ:
            del os.environ[k]

    yield

    reset_s3_client()
    for k, val in old_values.items():
        if val is not None:
            os.environ[k] = val
        elif k in os.environ:
            del os.environ[k]


# -----------------------------------------------------------------------------
# 1. ENVIRONMENT VARIABLES READ BY CONFIG SCHEMAS
# -----------------------------------------------------------------------------

def test_config_schema_reads_staging_environment_successfully(clean_env):
    """Verify that AssetStorageConfig parses valid staging environment variables."""
    env = {
        "S3_ASSETS_BUCKET": "interview-prep-assets-808431466075-staging-ap-south-2",
        "S3_ASSETS_REGION": "ap-south-2",
        "ASSET_BASE_URL": "https://d3stagingxyz123.cloudfront.net",
        "ENVIRONMENT": "staging",
    }
    config = AssetStorageConfig.from_env(env)
    assert config.s3_assets_bucket == "interview-prep-assets-808431466075-staging-ap-south-2"
    assert config.s3_assets_region == "ap-south-2"
    assert config.asset_base_url == "https://d3stagingxyz123.cloudfront.net"
    assert config.environment == "staging"


def test_config_schema_strips_trailing_slash_from_base_url(clean_env):
    """Verify that trailing slashes in ASSET_BASE_URL are sanitized cleanly."""
    env = {
        "S3_ASSETS_BUCKET": "interview-prep-assets-808431466075-staging-ap-south-2",
        "S3_ASSETS_REGION": "ap-south-2",
        "ASSET_BASE_URL": "https://d3stagingxyz123.cloudfront.net///",
        "ENVIRONMENT": "staging",
    }
    config = AssetStorageConfig.from_env(env)
    assert config.asset_base_url == "https://d3stagingxyz123.cloudfront.net"


def test_s3_storage_service_reads_environment_variables(clean_env):
    """Verify that s3_storage_service functions read valid environment variables."""
    os.environ["S3_ASSETS_BUCKET"] = "interview-prep-assets-808431466075-staging-ap-south-2"
    os.environ["S3_ASSETS_REGION"] = "ap-south-2"
    os.environ["ASSET_BASE_URL"] = "https://d3stagingxyz123.cloudfront.net"
    os.environ["ENVIRONMENT"] = "staging"

    assert get_s3_bucket() == "interview-prep-assets-808431466075-staging-ap-south-2"
    assert get_s3_region() == "ap-south-2"
    assert get_asset_base_url() == "https://d3stagingxyz123.cloudfront.net"


# -----------------------------------------------------------------------------
# 2. MISSING OR EMPTY REQUIRED ASSET CONFIGURATION DETECTED IN PRODUCTION/STAGING
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("env_name", ["production", "prod", "staging"])
def test_production_mode_rejects_missing_s3_assets_bucket(clean_env, env_name):
    """In production or staging, missing or empty S3_ASSETS_BUCKET must fail fast."""
    os.environ["ENVIRONMENT"] = env_name
    os.environ["ASSET_BASE_URL"] = "https://d3stagingxyz123.cloudfront.net"

    # Schema validation
    with pytest.raises(ValidationError, match="S3_ASSETS_BUCKET cannot be empty"):
        AssetStorageConfig.from_env()

    # Service layer runtime validation
    with pytest.raises(S3StorageError, match="S3_ASSETS_BUCKET environment variable is required"):
        get_s3_bucket()


@pytest.mark.parametrize("env_name", ["production", "prod", "staging"])
def test_production_mode_rejects_empty_s3_assets_bucket(clean_env, env_name):
    """In production or staging, empty string or whitespace bucket must fail."""
    os.environ["ENVIRONMENT"] = env_name
    os.environ["S3_ASSETS_BUCKET"] = "   "
    os.environ["ASSET_BASE_URL"] = "https://d3stagingxyz123.cloudfront.net"

    with pytest.raises(ValidationError, match="S3_ASSETS_BUCKET cannot be empty"):
        AssetStorageConfig.from_env()

    with pytest.raises(S3StorageError, match="S3_ASSETS_BUCKET environment variable is required"):
        get_s3_bucket()


@pytest.mark.parametrize("env_name", ["production", "prod", "staging"])
def test_production_mode_rejects_missing_asset_base_url(clean_env, env_name):
    """In production or staging, missing or empty ASSET_BASE_URL must fail fast."""
    os.environ["ENVIRONMENT"] = env_name
    os.environ["S3_ASSETS_BUCKET"] = "interview-prep-assets-808431466075-staging-ap-south-2"

    with pytest.raises(ValidationError, match="ASSET_BASE_URL cannot be empty"):
        AssetStorageConfig.from_env()

    with pytest.raises(S3StorageError, match="ASSET_BASE_URL environment variable is required"):
        get_asset_base_url()


@pytest.mark.parametrize("placeholder_url", [
    "https://d123456abcdef8.cloudfront.net",
    "https://<your-staging-distribution-id>.cloudfront.net",
    "https://<distribution-id>.cloudfront.net",
    "https://placeholder.cloudfront.net",
])
def test_production_mode_rejects_forbidden_placeholder_asset_base_url(clean_env, placeholder_url):
    """Fictitious or template placeholders in ASSET_BASE_URL must be rejected."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["S3_ASSETS_BUCKET"] = "interview-prep-assets-808431466075-staging-ap-south-2"
    os.environ["ASSET_BASE_URL"] = placeholder_url

    with pytest.raises(ValidationError, match="forbidden placeholder pattern"):
        AssetStorageConfig.from_env()

    with pytest.raises(S3StorageError, match="placeholder or fictitious domain"):
        get_asset_base_url()


def test_production_mode_rejects_non_https_asset_base_url(clean_env):
    """Non-HTTPS base URL must be rejected for security."""
    os.environ["ENVIRONMENT"] = "production"
    os.environ["S3_ASSETS_BUCKET"] = "interview-prep-assets-808431466075-staging-ap-south-2"
    os.environ["ASSET_BASE_URL"] = "http://d3stagingxyz123.cloudfront.net"

    with pytest.raises(ValidationError, match="must use HTTPS"):
        AssetStorageConfig.from_env()

    with pytest.raises(S3StorageError, match="must use HTTPS protocol"):
        get_asset_base_url()


def test_test_mode_fallback_behavior(clean_env):
    """Outside production/staging, test mode (TESTING=1) permits fallback."""
    os.environ["TESTING"] = "1"
    os.environ["S3_ASSETS_BUCKET"] = "test-bucket"
    os.environ["S3_ASSETS_REGION"] = "ap-south-2"

    assert get_asset_base_url() == "https://test-bucket.s3.ap-south-2.amazonaws.com"


# -----------------------------------------------------------------------------
# 3. FRONTEND ENV FILES DO NOT LEAK BACKEND SECRETS
# -----------------------------------------------------------------------------

DISALLOWED_BACKEND_SECRETS = [
    "SUPABASE_SERVICE_KEY",
    "GEMINI_API_KEY",
    "RDS_SECRET_NAME",
    "RDS_SECRET_ARN",
    "DATABASE_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "CLOUDINARY_API_SECRET",
    "POSTGRES_PASSWORD",
    "RDS_POOL_MIN",
    "RDS_POOL_MAX",
]


def test_frontend_env_example_does_not_contain_backend_secrets():
    """Verify that frontend/.env.example contains zero backend secrets or write credentials."""
    frontend_env_file = FRONTEND_DIR / ".env.example"
    assert frontend_env_file.is_file(), f"Expected {frontend_env_file} to exist"

    content = frontend_env_file.read_text(encoding="utf-8")
    lines = content.splitlines()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Extract variable name from line (e.g. VAR=val)
        var_name = stripped.split("=")[0].strip()

        # Check against disallowed backend secrets
        for secret_key in DISALLOWED_BACKEND_SECRETS:
            assert secret_key not in var_name, (
                f"Security violation: Backend secret '{secret_key}' found in frontend/.env.example: {line}"
            )

        # Ensure all variables exposed to client build start with NEXT_PUBLIC_ or are internal server config
        allowed_non_public = {
            "BACKEND_INTERNAL_URL",
            "PORT",
            "AUTH_REDIRECT_URL",
            "FRONTEND_URL",
            "SUPABASE_URL",
            "SUPABASE_ANON_KEY",
        }
        if not var_name.startswith("NEXT_PUBLIC_"):
            assert var_name in allowed_non_public, (
                f"Unexpected private variable in frontend/.env.example: {var_name}"
            )


def test_frontend_env_example_has_no_secret_occurrences_in_comments():
    """Verify that sensitive secret keys are not even referenced as active values in comments."""
    frontend_env_file = FRONTEND_DIR / ".env.example"
    content = frontend_env_file.read_text(encoding="utf-8")

    strict_secrets = [
        "SUPABASE_SERVICE_KEY",
        "GEMINI_API_KEY",
        "RDS_SECRET_NAME",
        "RDS_SECRET_ARN",
        "AWS_SECRET_ACCESS_KEY",
    ]
    for secret in strict_secrets:
        assert secret not in content, (
            f"Sensitive secret token '{secret}' referenced in frontend/.env.example"
        )


def test_docker_compose_frontend_service_does_not_receive_backend_secrets():
    """Verify that root docker-compose.yml does not inject backend secrets into frontend container."""
    compose_file = ROOT_DIR / "docker-compose.yml"
    assert compose_file.is_file(), f"Expected {compose_file} to exist"

    raw_yaml = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    frontend_service = raw_yaml.get("services", {}).get("frontend", {})
    assert frontend_service, "frontend service not defined in docker-compose.yml"

    # Check environment block
    env_block = frontend_service.get("environment", [])
    if isinstance(env_block, list):
        env_keys = [item.split("=")[0].strip() for item in env_block]
    elif isinstance(env_block, dict):
        env_keys = list(env_block.keys())
    else:
        env_keys = []

    # Check build args block
    build_args = frontend_service.get("build", {}).get("args", [])
    if isinstance(build_args, list):
        arg_keys = [item.split("=")[0].strip() for item in build_args]
    elif isinstance(build_args, dict):
        arg_keys = list(build_args.keys())
    else:
        arg_keys = []

    all_frontend_keys = set(env_keys + arg_keys)

    for secret in DISALLOWED_BACKEND_SECRETS:
        assert secret not in all_frontend_keys, (
            f"Security violation: Backend secret '{secret}' is mapped to frontend in docker-compose.yml"
        )


# -----------------------------------------------------------------------------
# 4. DOCKER COMPOSE CONFIGURATION CONVENTION & DEFAULTS
# -----------------------------------------------------------------------------

def test_root_docker_compose_backend_s3_asset_environment_mapping():
    """Verify root docker-compose.yml maps S3 and CloudFront variables with staging defaults."""
    compose_file = ROOT_DIR / "docker-compose.yml"
    raw_yaml = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    backend_env = raw_yaml["services"]["backend"]["environment"]

    env_map = {}
    for item in backend_env:
        if "=" in item:
            k, v = item.split("=", 1)
            env_map[k.strip()] = v.strip()

    assert "S3_ASSETS_BUCKET" in env_map
    assert env_map["S3_ASSETS_BUCKET"] == "${S3_ASSETS_BUCKET:-interview-prep-assets-808431466075-personal-ap-south-2}"

    assert "S3_ASSETS_REGION" in env_map
    assert env_map["S3_ASSETS_REGION"] == "${S3_ASSETS_REGION:-ap-south-2}"

    assert "ASSET_BASE_URL" in env_map
    assert env_map["ASSET_BASE_URL"] == "${ASSET_BASE_URL:-}"

    # Verify existing variables are preserved
    assert "GEMINI_API_KEY" in env_map
    assert "SUPABASE_URL" in env_map
    assert "SUPABASE_SERVICE_KEY" in env_map
    assert "RDS_SECRET_NAME" in env_map
    assert "AWS_REGION" in env_map


def test_backend_docker_compose_s3_asset_environment_mapping():
    """Verify backend/docker-compose.yml maps S3 and CloudFront variables with personal defaults."""
    compose_file = BACKEND_DIR / "docker-compose.yml"
    raw_yaml = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    app_env = raw_yaml["services"]["app"]["environment"]

    env_map = {}
    for item in app_env:
        if "=" in item:
            k, v = item.split("=", 1)
            env_map[k.strip()] = v.strip()

    assert "S3_ASSETS_BUCKET" in env_map
    assert env_map["S3_ASSETS_BUCKET"] == "${S3_ASSETS_BUCKET:-interview-prep-assets-808431466075-personal-ap-south-2}"

    assert "S3_ASSETS_REGION" in env_map
    assert env_map["S3_ASSETS_REGION"] == "${S3_ASSETS_REGION:-ap-south-2}"

    assert "ASSET_BASE_URL" in env_map
    assert env_map["ASSET_BASE_URL"] == "${ASSET_BASE_URL:-}"

    # Verify existing variables are preserved
    assert "GEMINI_API_KEY" in env_map
    assert "SUPABASE_URL" in env_map
    assert "SUPABASE_SERVICE_KEY" in env_map
    assert "RDS_SECRET_NAME" in env_map
    assert "AWS_REGION" in env_map


def test_no_fictitious_placeholder_default_in_example_files():
    """Verify d123456abcdef8.cloudfront.net is eliminated from all example env files."""
    example_files = [
        ROOT_DIR / ".env.example",
        BACKEND_DIR / ".env.example",
        FRONTEND_DIR / ".env.example",
    ]
    for ef in example_files:
        assert ef.is_file(), f"File {ef} should exist"
        content = ef.read_text(encoding="utf-8")
        assert "d123456abcdef8" not in content, (
            f"Fictitious domain d123456abcdef8 found in {ef}"
        )
