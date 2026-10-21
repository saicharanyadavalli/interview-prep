"""Unit tests for Docker Compose configuration and environment variable propagation.

Verifies:
1. Both root and backend docker-compose.yml files are valid YAML without obsolete attributes.
2. All 12 centralized caching and rate-limiting configuration variables are declared and passed
   into the backend container environment without duplicates:
   - ENVIRONMENT
   - AWS_REGION
   - CACHE_ENABLED
   - CACHE_URL
   - CACHE_HOST
   - CACHE_PORT
   - CACHE_TLS_ENABLED
   - CACHE_SECRET_NAME
   - CACHE_DB
   - CACHE_KEY_PREFIX
   - RATE_LIMIT_STORAGE_URI
   - RATE_LIMIT_KEY_PREFIX
3. Precise POSIX parameter expansion rules:
   - When CACHE_URL is unset, it defaults to redis://redis:6379/0 via ${CACHE_URL-redis://redis:6379/0}.
   - When CACHE_URL is explicitly empty (CACHE_URL=""), it MUST evaluate to "" and NOT default to redis://redis:6379/0,
     unblocking CACHE_HOST and Secrets Manager dynamic resolution.
   - CACHE_DB evaluates to "0" when unset or empty.
   - RATE_LIMIT_STORAGE_URI evaluates to "" when empty.
4. Both .env.example files document local Redis and AWS Valkey configuration examples without plaintext secrets.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Tuple
import pytest
import yaml

# Directory anchors
BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent

ROOT_COMPOSE_PATH = ROOT_DIR / "docker-compose.yml"
BACKEND_COMPOSE_PATH = BACKEND_DIR / "docker-compose.yml"

ROOT_ENV_EXAMPLE_PATH = ROOT_DIR / ".env.example"
BACKEND_ENV_EXAMPLE_PATH = BACKEND_DIR / ".env.example"

EXPECTED_12_VARIABLES: List[str] = [
    "ENVIRONMENT",
    "AWS_REGION",
    "CACHE_ENABLED",
    "CACHE_URL",
    "CACHE_HOST",
    "CACHE_PORT",
    "CACHE_TLS_ENABLED",
    "CACHE_SECRET_NAME",
    "CACHE_DB",
    "CACHE_KEY_PREFIX",
    "RATE_LIMIT_STORAGE_URI",
    "RATE_LIMIT_KEY_PREFIX",
]


def _extract_env_items(env_list_or_dict: Any) -> List[Tuple[str, str]]:
    """Extract list of (VAR_NAME, RAW_VALUE_EXPRESSION) from Compose environment definition."""
    items: List[Tuple[str, str]] = []
    if isinstance(env_list_or_dict, list):
        for entry in env_list_or_dict:
            if not isinstance(entry, str):
                continue
            if "=" in entry:
                var_name, val_expr = entry.split("=", 1)
                items.append((var_name.strip(), val_expr.strip()))
            else:
                items.append((entry.strip(), f"${{{entry.strip()}}}"))
    elif isinstance(env_list_or_dict, dict):
        for k, v in env_list_or_dict.items():
            items.append((str(k).strip(), str(v) if v is not None else ""))
    return items


def _posix_expand(expr: str, env: Dict[str, str]) -> str:
    """Simulate POSIX / Docker Compose parameter expansion for expressions like:

    - ${VAR-default}  : default ONLY if VAR is unset in env (not if empty)
    - ${VAR:-default} : default if VAR is unset OR empty in env
    - ${VAR}          : direct substitution (empty string if unset)
    """
    pattern = re.compile(r"\$\{([A-Za-z0-9_]+)(:?[-?])?([^}]*)\}")

    def replace_match(match: re.Match[str]) -> str:
        var_name = match.group(1)
        separator = match.group(2)
        default_val = match.group(3) or ""

        if separator == ":-":
            # Default if unset OR empty
            val = env.get(var_name)
            return default_val if (val is None or val == "") else val
        elif separator == "-":
            # Default ONLY if unset
            return default_val if var_name not in env else env[var_name]
        elif separator == ":?":
            # Required non-empty
            val = env.get(var_name)
            if val is None or val == "":
                raise ValueError(default_val or f"{var_name} is required")
            return val
        elif separator == "?":
            # Required set
            if var_name not in env:
                raise ValueError(default_val or f"{var_name} is required")
            return env[var_name]
        else:
            return env.get(var_name, "")

    return pattern.sub(replace_match, expr)


# ===========================================================================
# 1. Compose File Existence & YAML Validity
# ===========================================================================

def test_compose_files_exist_and_are_valid_yaml() -> None:
    """Verify that both compose files exist and parse cleanly as valid YAML."""
    assert ROOT_COMPOSE_PATH.is_file(), f"Root docker-compose.yml not found at {ROOT_COMPOSE_PATH}"
    assert BACKEND_COMPOSE_PATH.is_file(), f"Backend docker-compose.yml not found at {BACKEND_COMPOSE_PATH}"

    with open(ROOT_COMPOSE_PATH, "r", encoding="utf-8") as f:
        root_data = yaml.safe_load(f)
    assert isinstance(root_data, dict)
    assert "services" in root_data
    assert "backend" in root_data["services"]

    with open(BACKEND_COMPOSE_PATH, "r", encoding="utf-8") as f:
        backend_data = yaml.safe_load(f)
    assert isinstance(backend_data, dict)
    assert "services" in backend_data
    assert "app" in backend_data["services"]

    # Obsolete version field should not be present in modern Compose files
    assert "version" not in backend_data, "Backend docker-compose.yml should omit obsolete 'version' attribute"


# ===========================================================================
# 2. Variable Declaration and Deduplication
# ===========================================================================

@pytest.mark.parametrize(
    "compose_path,service_name",
    [
        (ROOT_COMPOSE_PATH, "backend"),
        (BACKEND_COMPOSE_PATH, "app"),
    ],
)
def test_all_12_variables_declared_without_duplicates(compose_path: Path, service_name: str) -> None:
    """Verify that all 12 configuration variables are declared in the backend service without duplicates."""
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    env_raw = data["services"][service_name]["environment"]
    env_items = _extract_env_items(env_raw)
    declared_names = [name for name, _ in env_items]

    # Check for duplicates
    seen = set()
    duplicates = []
    for name in declared_names:
        if name in seen:
            duplicates.append(name)
        seen.add(name)
    assert not duplicates, f"{compose_path.name} ({service_name}) contains duplicate environment keys: {duplicates}"

    # Check all 12 expected variables are present
    missing = [var for var in EXPECTED_12_VARIABLES if var not in declared_names]
    assert not missing, f"{compose_path.name} ({service_name}) is missing expected variables: {missing}"


# ===========================================================================
# 3. Parameter Expansion Syntax Checks
# ===========================================================================

@pytest.mark.parametrize(
    "compose_path,service_name",
    [
        (ROOT_COMPOSE_PATH, "backend"),
        (BACKEND_COMPOSE_PATH, "app"),
    ],
)
def test_exact_expansion_syntax_in_compose(compose_path: Path, service_name: str) -> None:
    """Verify exact parameter expansion syntax:

    - CACHE_URL uses '${CACHE_URL-redis://redis:6379/0}' (no colon)
    - CACHE_DB uses '${CACHE_DB:-0}'
    - RATE_LIMIT_STORAGE_URI uses '${RATE_LIMIT_STORAGE_URI:-}'
    """
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    env_items = dict(_extract_env_items(data["services"][service_name]["environment"]))

    cache_url_expr = env_items.get("CACHE_URL")
    assert cache_url_expr == "${CACHE_URL-redis://redis:6379/0}", (
        f"{compose_path.name}: CACHE_URL expression must be '${{CACHE_URL-redis://redis:6379/0}}' (no colon) "
        f"to preserve explicit empty string; found: {cache_url_expr}"
    )

    cache_db_expr = env_items.get("CACHE_DB")
    assert cache_db_expr == "${CACHE_DB:-0}", (
        f"{compose_path.name}: CACHE_DB expression must be '${{CACHE_DB:-0}}'; found: {cache_db_expr}"
    )

    rl_uri_expr = env_items.get("RATE_LIMIT_STORAGE_URI")
    assert rl_uri_expr in ("${RATE_LIMIT_STORAGE_URI:-}", "${RATE_LIMIT_STORAGE_URI-}"), (
        f"{compose_path.name}: RATE_LIMIT_STORAGE_URI must evaluate to empty; found: {rl_uri_expr}"
    )


# ===========================================================================
# 4. Programmatic Evaluation: Unset vs. Explicitly Empty
# ===========================================================================

@pytest.mark.parametrize(
    "compose_path,service_name",
    [
        (ROOT_COMPOSE_PATH, "backend"),
        (BACKEND_COMPOSE_PATH, "app"),
    ],
)
def test_cache_url_empty_does_not_default(compose_path: Path, service_name: str) -> None:
    """When CACHE_URL is explicitly set to empty (CACHE_URL=""), it MUST evaluate to ""

    and NOT default to redis://redis:6379/0.
    """
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    env_items = dict(_extract_env_items(data["services"][service_name]["environment"]))

    cache_url_expr = env_items["CACHE_URL"]

    # Case A: CACHE_URL is explicitly empty
    env_empty = {"CACHE_URL": ""}
    resolved_empty = _posix_expand(cache_url_expr, env_empty)
    assert resolved_empty == "", (
        f"When CACHE_URL is empty, resolved value must be empty string, but got: '{resolved_empty}'"
    )

    # Case B: CACHE_URL is unset
    env_unset: Dict[str, str] = {}
    resolved_unset = _posix_expand(cache_url_expr, env_unset)
    assert resolved_unset == "redis://redis:6379/0", (
        f"When CACHE_URL is unset, resolved value must default to 'redis://redis:6379/0', but got: '{resolved_unset}'"
    )

    # Case C: CACHE_URL is explicitly set to custom URL
    custom_url = "rediss://master.node.aps2.cache.amazonaws.com:6379/0"
    env_custom = {"CACHE_URL": custom_url}
    resolved_custom = _posix_expand(cache_url_expr, env_custom)
    assert resolved_custom == custom_url


@pytest.mark.parametrize(
    "compose_path,service_name",
    [
        (ROOT_COMPOSE_PATH, "backend"),
        (BACKEND_COMPOSE_PATH, "app"),
    ],
)
def test_all_12_variables_propagation_simulation(compose_path: Path, service_name: str) -> None:
    """Simulate complete container environment evaluation under both local and staging scenarios."""
    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    env_items = dict(_extract_env_items(data["services"][service_name]["environment"]))

    # Scenario 1: EC2 Staging with Valkey
    staging_env = {
        "ENVIRONMENT": "personal",
        "AWS_REGION": "ap-south-2",
        "CACHE_ENABLED": "true",
        "CACHE_URL": "",
        "CACHE_HOST": "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com",
        "CACHE_PORT": "6379",
        "CACHE_TLS_ENABLED": "true",
        "CACHE_SECRET_NAME": "interview-prep/elasticache/auth-personal",
        "CACHE_DB": "0",
        "RATE_LIMIT_STORAGE_URI": "",
        "CACHE_KEY_PREFIX": "ip:personal:cache:v1:",
        "RATE_LIMIT_KEY_PREFIX": "ip:personal:rl:",
    }

    evaluated_staging = {k: _posix_expand(env_items[k], staging_env) for k in EXPECTED_12_VARIABLES}
    assert evaluated_staging["ENVIRONMENT"] == "personal"
    assert evaluated_staging["AWS_REGION"] == "ap-south-2"
    assert evaluated_staging["CACHE_ENABLED"] == "true"
    assert evaluated_staging["CACHE_URL"] == ""
    assert evaluated_staging["CACHE_HOST"] == "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com"
    assert evaluated_staging["CACHE_PORT"] == "6379"
    assert evaluated_staging["CACHE_TLS_ENABLED"] == "true"
    assert evaluated_staging["CACHE_SECRET_NAME"] == "interview-prep/elasticache/auth-personal"
    assert evaluated_staging["CACHE_DB"] == "0"
    assert evaluated_staging["RATE_LIMIT_STORAGE_URI"] == ""
    assert evaluated_staging["CACHE_KEY_PREFIX"] == "ip:personal:cache:v1:"
    assert evaluated_staging["RATE_LIMIT_KEY_PREFIX"] == "ip:personal:rl:"

    # Scenario 2: Local Development with default Redis container (CACHE_URL unset)
    local_env: Dict[str, str] = {
        "ENVIRONMENT": "local",
    }
    evaluated_local = {k: _posix_expand(env_items[k], local_env) for k in EXPECTED_12_VARIABLES}
    assert evaluated_local["CACHE_URL"] == "redis://redis:6379/0"
    assert evaluated_local["CACHE_DB"] == "0"
    assert evaluated_local["RATE_LIMIT_STORAGE_URI"] == ""


# ===========================================================================
# 5. Native Docker Compose CLI Verification (when docker is installed)
# ===========================================================================

DOCKER_AVAILABLE = shutil.which("docker") is not None


@pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker CLI not available on host")
@pytest.mark.parametrize(
    "compose_path,service_name",
    [
        (ROOT_COMPOSE_PATH, "backend"),
        (BACKEND_COMPOSE_PATH, "app"),
    ],
)
def test_docker_compose_cli_cache_url_behavior(compose_path: Path, service_name: str) -> None:
    """Verify that 'docker compose config' strictly implements empty CACHE_URL vs. unset default."""
    base_env = os.environ.copy()
    base_env["GEMINI_API_KEY"] = "dummy_for_compose_cli_validation"

    # Test 1: CACHE_URL is explicitly empty
    empty_env = base_env.copy()
    empty_env["CACHE_URL"] = ""
    res_empty = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config"],
        capture_output=True,
        text=True,
        env=empty_env,
        check=False,
    )
    assert res_empty.returncode == 0, f"docker compose config failed: {res_empty.stderr}"
    parsed_empty = yaml.safe_load(res_empty.stdout)
    backend_env_empty = parsed_empty["services"][service_name]["environment"]
    assert backend_env_empty.get("CACHE_URL") == "", (
        f"Docker Compose CLI must leave CACHE_URL as empty string when CACHE_URL='', got: "
        f"{repr(backend_env_empty.get('CACHE_URL'))}"
    )

    # Test 2: CACHE_URL is unset
    unset_env = base_env.copy()
    unset_env.pop("CACHE_URL", None)
    res_unset = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "config"],
        capture_output=True,
        text=True,
        env=unset_env,
        check=False,
    )
    assert res_unset.returncode == 0, f"docker compose config failed: {res_unset.stderr}"
    parsed_unset = yaml.safe_load(res_unset.stdout)
    backend_env_unset = parsed_unset["services"][service_name]["environment"]
    assert backend_env_unset.get("CACHE_URL") == "redis://redis:6379/0", (
        f"Docker Compose CLI must default CACHE_URL to 'redis://redis:6379/0' when unset, got: "
        f"{repr(backend_env_unset.get('CACHE_URL'))}"
    )


# ===========================================================================
# 6. Environment Example Documentation & Secrets Security
# ===========================================================================

@pytest.mark.parametrize(
    "env_example_path",
    [ROOT_ENV_EXAMPLE_PATH, BACKEND_ENV_EXAMPLE_PATH],
)
def test_env_example_documentation_and_security(env_example_path: Path) -> None:
    """Verify that .env.example files document both local and Valkey patterns without plaintext secrets."""
    assert env_example_path.is_file(), f"File {env_example_path} does not exist"
    content = env_example_path.read_text(encoding="utf-8")

    # Verify all 12 variable names appear in the example file
    for var in EXPECTED_12_VARIABLES:
        assert var in content, f"{env_example_path.name} is missing reference to {var}"

    # Verify Valkey staging/production host endpoint example
    assert "master.interview-prep-node-personal.gmgjlz.aps2.cache.amazonaws.com" in content
    assert "interview-prep/elasticache/auth-personal" in content
    assert "CACHE_DB=0" in content

    # Verify explanation of empty CACHE_URL requirement
    assert "CACHE_URL=" in content

    # Security check: Ensure NO plaintext credentials or dummy Redis auth tokens are present
    assert "CACHE_AUTH_TOKEN=" not in content, "Found forbidden CACHE_AUTH_TOKEN in example file"
    assert "REDIS_PASSWORD=" not in content, "Found forbidden REDIS_PASSWORD in example file"
    assert "user:pass" not in content, "Found unmasked user:pass credential placeholder in example file"
