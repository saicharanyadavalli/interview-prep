"""Amazon Cognito authentication service.

Validates RS256 JWT access tokens issued by Amazon Cognito User Pools
against public JSON Web Keys (JWKS) with in-memory caching and identity validation.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import jwt
from jwt.algorithms import RSAAlgorithm
import requests

logger = logging.getLogger(__name__)

# Default configurations
DEFAULT_COGNITO_REGION = "ap-south-2"
_DEFAULT_USER_POOL_ID = "ap-south-2_testPoolId"
_DEFAULT_CLIENT_ID = "test-client-id-123"


def __getattr__(name: str) -> Any:
    """Safely expose DEFAULT constants only in test mode and not in production/staging."""
    if name in ("DEFAULT_USER_POOL_ID", "DEFAULT_CLIENT_ID"):
        if is_production_or_staging() or not is_test_mode():
            raise CognitoAuthError(
                f"{name} is only accessible in test mode and is forbidden in production/staging."
            )
        if name == "DEFAULT_USER_POOL_ID":
            return _DEFAULT_USER_POOL_ID
        if name == "DEFAULT_CLIENT_ID":
            return _DEFAULT_CLIENT_ID
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


# In-memory JWKS cache: {(user_pool_id, kid): jwk_dict}
_JWKS_CACHE: Dict[tuple[str, str], Dict[str, Any]] = {}
_JWKS_LAST_FETCH: Dict[str, float] = {}  # {user_pool_id: timestamp}
_JWKS_LOCK = threading.Lock()
JWKS_CACHE_TTL = 3600.0  # 1 hour cache TTL


class CognitoAuthError(Exception):
    """Base exception for all Cognito authentication failures."""
    pass


class TokenExpiredError(CognitoAuthError):
    """Raised when token signature is expired."""
    pass


class TokenNotBeforeError(CognitoAuthError):
    """Raised when token is received before its nbf window."""
    pass


class InvalidIssuerError(CognitoAuthError):
    """Raised when token issuer does not match Cognito User Pool URL."""
    pass


class InvalidTokenUseError(CognitoAuthError):
    """Raised when token_use is not 'access' (e.g. ID token received)."""
    pass


class InvalidClientIdError(CognitoAuthError):
    """Raised when token client_id does not match configured COGNITO_CLIENT_ID."""
    pass


class InvalidTokenError(CognitoAuthError):
    """Raised when token is malformed, signature is invalid, or kid is missing/unknown."""
    pass


def is_production_or_staging() -> bool:
    """Return True if running in production, staging, or personal cloud environment."""
    env = (
        os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("ENV")
        or ""
    ).lower().strip()
    return env in ("production", "prod", "staging", "personal")


def is_test_mode() -> bool:
    """Return True if running in explicit unit/integration test mode."""
    if is_production_or_staging():
        return False
    return (
        os.getenv("TESTING") == "1"
        or os.getenv("TESTING", "").lower() in ("true", "yes")
        or (os.getenv("ENV") or "").lower() == "test"
        or (os.getenv("ENVIRONMENT") or "").lower() == "test"
        or (os.getenv("APP_ENV") or "").lower() == "test"
    )


def get_cognito_region() -> str:
    """Resolve AWS region for Cognito."""
    region = (
        os.getenv("COGNITO_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or DEFAULT_COGNITO_REGION
    ).strip()
    return region


def get_cognito_user_pool_id() -> str:
    """Resolve Cognito User Pool ID from environment.

    In production/staging, requires explicit COGNITO_USER_POOL_ID and rejects test defaults.
    """
    pool_id = os.getenv("COGNITO_USER_POOL_ID", "").strip()
    if is_production_or_staging():
        if not pool_id or pool_id == _DEFAULT_USER_POOL_ID:
            raise CognitoAuthError(
                "Missing or invalid COGNITO_USER_POOL_ID environment variable in production/staging environment."
            )
        return pool_id

    if not pool_id:
        if is_test_mode():
            return _DEFAULT_USER_POOL_ID
        raise CognitoAuthError(
            "Missing COGNITO_USER_POOL_ID environment variable."
        )
    return pool_id


def get_cognito_client_id() -> str:
    """Resolve Cognito App Client ID from environment.

    In production/staging, requires explicit COGNITO_CLIENT_ID and rejects test defaults.
    """
    client_id = os.getenv("COGNITO_CLIENT_ID", "").strip()
    if is_production_or_staging():
        if not client_id or client_id == _DEFAULT_CLIENT_ID:
            raise CognitoAuthError(
                "Missing or invalid COGNITO_CLIENT_ID environment variable in production/staging environment."
            )
        return client_id

    if not client_id:
        if is_test_mode():
            return _DEFAULT_CLIENT_ID
        raise CognitoAuthError(
            "Missing COGNITO_CLIENT_ID environment variable."
        )
    return client_id


def get_cognito_issuer(region: Optional[str] = None, user_pool_id: Optional[str] = None) -> str:
    """Build authoritative issuer URL for Cognito User Pool."""
    reg = region or get_cognito_region()
    pool = user_pool_id or get_cognito_user_pool_id()
    return f"https://cognito-idp.{reg}.amazonaws.com/{pool}"


def get_jwks_url(region: Optional[str] = None, user_pool_id: Optional[str] = None) -> str:
    """Build authoritative JWKS endpoint URL for Cognito User Pool."""
    issuer = get_cognito_issuer(region=region, user_pool_id=user_pool_id)
    return f"{issuer}/.well-known/jwks.json"


def clear_jwks_cache() -> None:
    """Clear in-memory JWKS cache (primarily used in unit test cleanup)."""
    global _JWKS_CACHE, _JWKS_LAST_FETCH
    with _JWKS_LOCK:
        _JWKS_CACHE.clear()
        _JWKS_LAST_FETCH.clear()


def set_cached_jwks(jwks_data: Dict[str, Any], user_pool_id: Optional[str] = None) -> None:
    """Explicitly populate the JWKS cache with JWK dictionary keys for a pool."""
    global _JWKS_CACHE, _JWKS_LAST_FETCH
    pool_id = user_pool_id or get_cognito_user_pool_id()
    with _JWKS_LOCK:
        # Clear existing keys for this pool
        keys_to_delete = [k for k in _JWKS_CACHE if k[0] == pool_id]
        for k in keys_to_delete:
            del _JWKS_CACHE[k]
        keys = jwks_data.get("keys", [])
        for key in keys:
            kid = key.get("kid")
            if kid:
                _JWKS_CACHE[(pool_id, kid)] = key
        _JWKS_LAST_FETCH[pool_id] = time.time()


def fetch_jwks(
    region: Optional[str] = None,
    user_pool_id: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Fetch and cache JWKS from Cognito User Pool .well-known/jwks.json."""
    global _JWKS_CACHE, _JWKS_LAST_FETCH

    pool_id = user_pool_id or get_cognito_user_pool_id()
    reg = region or get_cognito_region()

    with _JWKS_LOCK:
        now = time.time()
        last_fetch = _JWKS_LAST_FETCH.get(pool_id, 0.0)
        pool_keys = {kid: key for (p, kid), key in _JWKS_CACHE.items() if p == pool_id}
        if pool_keys and not force_refresh and (now - last_fetch < JWKS_CACHE_TTL):
            return pool_keys

    url = get_jwks_url(region=reg, user_pool_id=pool_id)
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        jwks_payload = response.json()
    except Exception as exc:
        logger.error("Failed to fetch Cognito JWKS from %s: %s", url, exc)
        raise CognitoAuthError(f"Failed to fetch Cognito JWKS from {url}: {exc}") from exc

    with _JWKS_LOCK:
        # Clear previous keys for this pool
        for k in [k for k in _JWKS_CACHE if k[0] == pool_id]:
            del _JWKS_CACHE[k]
        result: Dict[str, Dict[str, Any]] = {}
        for key in jwks_payload.get("keys", []):
            kid = key.get("kid")
            if kid:
                _JWKS_CACHE[(pool_id, kid)] = key
                result[kid] = key
        _JWKS_LAST_FETCH[pool_id] = time.time()
        return result


def verify_cognito_token(
    token: str,
    region: Optional[str] = None,
    user_pool_id: Optional[str] = None,
    client_id: Optional[str] = None,
    allow_mock: bool = True,
) -> Dict[str, Any]:
    """Validate a Cognito access token against authoritative User Pool JWKS.

    Performs:
    1. Strict mock token guard: ONLY accept mock tokens when is_test_mode() AND
       NOT is_production_or_staging(). In production/staging, fail closed with CognitoAuthError.
    2. Extract unverified header to locate key ID (kid) and algorithm (must be RS256).
    3. Compound key cache lookup (user_pool_id, kid). If kid is unknown, trigger a single
       safe force-refresh of JWKS from Cognito before failing.
    4. RS256 signature verification using public key from JWKS.
    5. Expiration (exp), active window (nbf), and issuer (iss) validation against expected
       Cognito User Pool URL.
    6. token_use == 'access' enforcement (rejects ID tokens).
    7. client_id validation against configured COGNITO_CLIENT_ID.

    Returns the decoded token claims dictionary.
    Raises specific subclasses of CognitoAuthError on failure.
    """
    if not token or not isinstance(token, str):
        raise InvalidTokenError("Token must be a non-empty string.")

    token = token.strip()

    # 1. Strict mock token guard
    is_mock = (
        token.startswith("mock-")
        or token.startswith("mock:")
        or token.startswith("test-")
        or token == "mock_token"
    )

    if is_mock:
        if is_production_or_staging() or not is_test_mode():
            raise CognitoAuthError(
                "Mock tokens are strictly forbidden in production and staging environments."
            )
        if not allow_mock:
            raise CognitoAuthError("Mock tokens are not allowed for this operation.")

        expected_pool = user_pool_id or get_cognito_user_pool_id()
        expected_reg = region or get_cognito_region()
        expected_client = client_id or get_cognito_client_id()
        expected_iss = get_cognito_issuer(region=expected_reg, user_pool_id=expected_pool)

        mock_sub = "11111111-2222-3333-4444-555555555555"
        mock_email = "testuser@example.com"
        mock_username = "testuser"

        # Allow encoded mock parameters, e.g. mock:sub:email:username
        if token.startswith("mock:"):
            parts = token.split(":")
            if len(parts) >= 2 and parts[1]:
                mock_sub = parts[1]
            if len(parts) >= 3 and parts[2]:
                mock_email = parts[2]
            if len(parts) >= 4 and parts[3]:
                mock_username = parts[3]

        return {
            "sub": mock_sub,
            "email": mock_email,
            "username": mock_username,
            "token_use": "access",
            "client_id": expected_client,
            "iss": expected_iss,
            "exp": int(time.time()) + 3600,
        }

    # 2. Extract unverified header to locate key ID (kid) and algorithm
    try:
        unverified_headers = jwt.get_unverified_header(token)
    except Exception as exc:
        raise InvalidTokenError(f"Invalid token header format: {exc}") from exc

    alg = unverified_headers.get("alg")
    if alg != "RS256":
        raise InvalidTokenError(f"Unsupported token algorithm '{alg}'. Only RS256 is supported.")

    kid = unverified_headers.get("kid")
    if not kid:
        raise InvalidTokenError("Token header is missing 'kid' (key ID).")

    expected_pool_id = user_pool_id or get_cognito_user_pool_id()
    expected_reg = region or get_cognito_region()
    expected_iss = get_cognito_issuer(region=expected_reg, user_pool_id=expected_pool_id)
    expected_client_id = client_id or get_cognito_client_id()

    # 3. Locate public key JWK in cached JWKS or trigger a single safe force-refresh
    jwk_dict: Optional[Dict[str, Any]] = None
    with _JWKS_LOCK:
        jwk_dict = _JWKS_CACHE.get((expected_pool_id, kid))

    if not jwk_dict:
        # Key not in compound cache — trigger a single safe force-refresh of JWKS from Cognito
        fresh_cache = fetch_jwks(region=expected_reg, user_pool_id=expected_pool_id, force_refresh=True)
        jwk_dict = fresh_cache.get(kid)

    if not jwk_dict:
        raise InvalidTokenError(f"Public key for kid '{kid}' not found in Cognito JWKS.")

    # 4. Construct RSA public key from JWK
    try:
        public_key = RSAAlgorithm.from_jwk(jwk_dict)
    except Exception as exc:
        raise InvalidTokenError(f"Failed to parse public key from JWK: {exc}") from exc

    # 5. Decode and cryptographically verify signature, exp, nbf, iss
    expected_pool_id = user_pool_id or get_cognito_user_pool_id()
    expected_reg = region or get_cognito_region()
    expected_iss = get_cognito_issuer(region=expected_reg, user_pool_id=expected_pool_id)
    expected_client_id = client_id or get_cognito_client_id()

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=expected_iss,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": False,  # Cognito access tokens use client_id, not aud
                "require": ["exp", "iss", "token_use", "client_id", "sub"],
            },
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError(f"Token has expired: {exc}") from exc
    except jwt.ImmatureSignatureError as exc:
        raise TokenNotBeforeError(f"Token is not yet active (nbf): {exc}") from exc
    except jwt.InvalidIssuerError as exc:
        raise InvalidIssuerError(f"Token issuer is invalid: {exc}") from exc
    except jwt.InvalidSignatureError as exc:
        raise InvalidTokenError(f"Token signature verification failed: {exc}") from exc
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(f"Token verification error: {exc}") from exc

    # 6. Validate token_use == 'access' (reject ID tokens for protected API endpoints)
    token_use = payload.get("token_use")
    if token_use != "access":
        raise InvalidTokenUseError(
            f"Invalid token_use '{token_use}'. Protected API endpoints strictly require token_use='access'."
        )

    # 7. Validate client_id matching configured COGNITO_CLIENT_ID
    token_client_id = payload.get("client_id")
    if token_client_id != expected_client_id:
        raise InvalidClientIdError(
            f"Token client_id '{token_client_id}' does not match expected '{expected_client_id}'."
        )

    return payload


def resolve_user_identity(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Convenience alias delegating to routes.auth.resolve_user_identity."""
    from routes.auth import resolve_user_identity as _resolve
    return _resolve(*args, **kwargs)
