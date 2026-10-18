"""Unit tests for Amazon Cognito authentication and RDS identity resolution.

Tests:
- Valid RS256 access token verification.
- Expired token rejection (exp).
- Future active window rejection (nbf).
- Wrong issuer rejection (iss).
- ID token rejection (token_use='id' rejected for protected API endpoints).
- Wrong client_id rejection.
- Invalid signature rejection.
- Missing / unknown kid rejection.
- JWKS network fetching and in-memory caching.
- Safe local mock token handling in test mode.
- RDS Identity Continuity:
  - Existing user_identities mapping lookup (preserves existing UUID and history).
  - Unambiguous email match linking to user_identities.
  - New user profile creation with fresh UUID and linking to user_identities.
  - Username collision resolution during new profile creation.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import jwt
from jwt.algorithms import RSAAlgorithm
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from services import cognito_auth
from services.cognito_auth import (
    CognitoAuthError,
    InvalidClientIdError,
    InvalidIssuerError,
    InvalidTokenError,
    InvalidTokenUseError,
    TokenExpiredError,
    TokenNotBeforeError,
    clear_jwks_cache,
    fetch_jwks,
    get_cognito_client_id,
    get_cognito_issuer,
    get_cognito_region,
    get_cognito_user_pool_id,
    resolve_user_identity,
    set_cached_jwks,
    verify_cognito_token,
)


# ── FIXTURES ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def cognito_test_env():
    """Configure clean environment variables for Cognito tests."""
    clear_jwks_cache()
    old_env = {
        k: os.environ.get(k)
        for k in (
            "COGNITO_REGION",
            "COGNITO_USER_POOL_ID",
            "COGNITO_CLIENT_ID",
            "AWS_REGION",
            "TESTING",
            "ENV",
            "ENVIRONMENT",
            "DISABLE_AUTH",
        )
    }

    os.environ["TESTING"] = "1"
    os.environ["COGNITO_REGION"] = "ap-south-2"
    os.environ["COGNITO_USER_POOL_ID"] = "ap-south-2_testPoolId"
    os.environ["COGNITO_CLIENT_ID"] = "test-client-id-123"
    os.environ["DISABLE_AUTH"] = "false"

    yield

    clear_jwks_cache()
    for k, v in old_env.items():
        if v is not None:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]


@pytest.fixture
def rsa_key_pair():
    """Generate a real 2048-bit RSA key pair and corresponding JWK for unit testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = "test-key-id-001"
    jwk_dict["use"] = "sig"
    jwk_dict["alg"] = "RS256"

    # Pre-populate JWKS cache so verification works offline
    set_cached_jwks({"keys": [jwk_dict]})

    return {
        "private_key": private_key,
        "public_key": public_key,
        "jwk": jwk_dict,
        "kid": "test-key-id-001",
    }


def make_test_token(
    private_key: Any,
    kid: str | None = "test-key-id-001",
    sub: str = "test-user-sub-1234",
    email: str = "test@example.com",
    username: str = "testuser",
    token_use: str = "access",
    client_id: str = "test-client-id-123",
    iss: str = "https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_testPoolId",
    exp_offset: int = 3600,
    nbf_offset: int | None = None,
    extra_claims: dict | None = None,
) -> str:
    """Helper to generate RS256 signed JWT tokens with customizable claims."""
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "username": username,
        "token_use": token_use,
        "client_id": client_id,
        "iss": iss,
        "exp": now + exp_offset,
        "iat": now,
        "auth_time": now,
    }
    if nbf_offset is not None:
        payload["nbf"] = now + nbf_offset
    if extra_claims:
        payload.update(extra_claims)

    headers = {}
    if kid is not None:
        headers["kid"] = kid

    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


# ── TOKEN VERIFICATION TESTS ──────────────────────────────────────────────────

def test_valid_rs256_access_token_verification(rsa_key_pair):
    """Verify that a valid RS256 Cognito access token passes verification."""
    token = make_test_token(rsa_key_pair["private_key"], sub="valid-user-uuid-999")
    claims = verify_cognito_token(token)

    assert claims is not None
    assert claims["sub"] == "valid-user-uuid-999"
    assert claims["token_use"] == "access"
    assert claims["client_id"] == "test-client-id-123"
    assert claims["iss"] == "https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_testPoolId"
    assert "exp" in claims


def test_expired_token_rejection(rsa_key_pair):
    """Verify that an expired Cognito token (exp in past) is rejected."""
    token = make_test_token(rsa_key_pair["private_key"], exp_offset=-3600)

    with pytest.raises(TokenExpiredError) as exc_info:
        verify_cognito_token(token)
    assert "expired" in str(exc_info.value).lower()


def test_future_nbf_token_rejection(rsa_key_pair):
    """Verify that a token with nbf in the future is rejected as not yet active."""
    token = make_test_token(rsa_key_pair["private_key"], nbf_offset=1800)

    with pytest.raises(TokenNotBeforeError) as exc_info:
        verify_cognito_token(token)
    assert "not yet active" in str(exc_info.value).lower()


def test_wrong_issuer_rejection(rsa_key_pair):
    """Verify that a token with an invalid issuer URL is rejected."""
    token = make_test_token(
        rsa_key_pair["private_key"],
        iss="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_otherPool",
    )

    with pytest.raises(InvalidIssuerError) as exc_info:
        verify_cognito_token(token)
    assert "issuer is invalid" in str(exc_info.value).lower()


def test_id_token_rejection(rsa_key_pair):
    """Verify that Cognito ID tokens (token_use='id') are strictly rejected for access endpoints."""
    token = make_test_token(
        rsa_key_pair["private_key"],
        token_use="id",  # ID token instead of access token
    )

    with pytest.raises(InvalidTokenUseError) as exc_info:
        verify_cognito_token(token)
    assert "token_use 'id'" in str(exc_info.value)
    assert "require token_use='access'" in str(exc_info.value)


def test_wrong_client_id_rejection(rsa_key_pair):
    """Verify that a token issued for a different client_id is rejected."""
    token = make_test_token(
        rsa_key_pair["private_key"],
        client_id="attacker-client-id-000",
    )

    with pytest.raises(InvalidClientIdError) as exc_info:
        verify_cognito_token(token)
    assert "client_id 'attacker-client-id-000' does not match" in str(exc_info.value)


def test_invalid_signature_rejection(rsa_key_pair):
    """Verify that a token signed with an untrusted private key is rejected."""
    different_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_test_token(different_private_key, kid=rsa_key_pair["kid"])

    with pytest.raises(InvalidTokenError) as exc_info:
        verify_cognito_token(token)
    assert "signature verification failed" in str(exc_info.value).lower()


def test_missing_kid_header_rejection(rsa_key_pair):
    """Verify that a token missing kid in its JOSE header is rejected."""
    token = make_test_token(rsa_key_pair["private_key"], kid=None)

    with pytest.raises(InvalidTokenError) as exc_info:
        verify_cognito_token(token)
    assert "missing 'kid'" in str(exc_info.value).lower()


def test_unknown_kid_rejection(rsa_key_pair):
    """Verify that a token with a kid not present in JWKS is rejected."""
    token = make_test_token(rsa_key_pair["private_key"], kid="unknown-kid-999")

    # Mock fetch_jwks to return empty so refresh also fails to find unknown kid
    with patch("services.cognito_auth.fetch_jwks", return_value={}):
        with pytest.raises(InvalidTokenError) as exc_info:
            verify_cognito_token(token)
        assert "not found in cognito jwks" in str(exc_info.value).lower()


def test_jwks_network_fetching_and_caching(rsa_key_pair):
    """Verify that JWKS is fetched from Cognito endpoint and cached in memory."""
    clear_jwks_cache()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": [rsa_key_pair["jwk"]]}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        # First call: triggers HTTP fetch
        keys_1 = fetch_jwks()
        assert rsa_key_pair["kid"] in keys_1
        assert mock_get.call_count == 1
        expected_url = "https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_testPoolId/.well-known/jwks.json"
        mock_get.assert_called_with(expected_url, timeout=5)

        # Second call: served from in-memory cache
        keys_2 = fetch_jwks()
        assert rsa_key_pair["kid"] in keys_2
        assert mock_get.call_count == 1  # Not called again!


def test_local_mock_token_in_test_mode():
    """Verify safe local mock token returns test claims in test mode."""
    token = "mock-access-token"
    claims = verify_cognito_token(token)

    assert claims is not None
    assert claims["sub"] == "11111111-2222-3333-4444-555555555555"
    assert claims["email"] == "testuser@example.com"
    assert claims["token_use"] == "access"
    assert claims["client_id"] == "test-client-id-123"


def test_local_mock_token_with_custom_sub():
    """Verify mock token format mock:sub:email:username works in test mode."""
    token = "mock:custom-sub-99:custom@example.com:customuser"
    claims = verify_cognito_token(token)

    assert claims["sub"] == "custom-sub-99"
    assert claims["email"] == "custom@example.com"
    assert claims["username"] == "customuser"
    assert claims["token_use"] == "access"


# ── RDS IDENTITY CONTINUITY TESTS ─────────────────────────────────────────────

def test_identity_resolution_existing_mapping():
    """Step 1 & 2: When mapping exists in user_identities, return existing user_profiles row.

    Preserves existing user UUID and all associated history/progress.
    """
    existing_uuid = "22222222-3333-4444-5555-666666666666"
    mock_identity = {
        "user_id": existing_uuid,
        "email": "alice@example.com",
    }
    mock_profile = {
        "id": existing_uuid,
        "email": "alice@example.com",
        "username": "alice",
        "name": "Alice Smith",
        "avatar_url": "https://example.com/alice.png",
    }

    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            assert params == ("cognito", "cognito-sub-alice")
            return mock_identity
        if "FROM user_profiles" in sql and "id = %s" in sql:
            assert params == (existing_uuid,)
            return mock_profile
        return None

    with patch("services.rds_client.query", side_effect=mock_query), \
         patch("services.rds_client.mutate") as mock_mutate:
        claims = {
            "sub": "cognito-sub-alice",
            "email": "alice@example.com",
            "username": "alice",
        }
        profile = resolve_user_identity(claims)

        assert profile["id"] == existing_uuid
        assert profile["email"] == "alice@example.com"
        assert profile["username"] == "alice"
        # Verify no insert into user_profiles was performed!
        mock_mutate.assert_not_called()


def test_identity_resolution_email_link():
    """Step 3: When no mapping exists, but email matches an existing user_profile, link it.

    Ensures seamless migration from Supabase/prior accounts to Cognito.
    """
    existing_uuid = "33333333-4444-5555-6666-777777777777"
    mock_existing_profile = {
        "id": existing_uuid,
        "email": "bob@example.com",
        "username": "bob",
        "name": "Bob Jones",
        "avatar_url": "",
    }

    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            return None  # No prior mapping
        if "FROM user_profiles" in sql and "LOWER(email) = LOWER(%s)" in sql:
            assert params == ("bob@example.com",)
            return [mock_existing_profile]  # Unambiguous single match
        return None

    with patch("services.rds_client.query", side_effect=mock_query), \
         patch("services.rds_client.mutate") as mock_mutate:
        claims = {
            "sub": "cognito-sub-bob",
            "email": "bob@example.com",
            "username": "bob",
        }
        profile = resolve_user_identity(claims)

        assert profile["id"] == existing_uuid
        assert profile["email"] == "bob@example.com"

        # Assert linking insert into user_identities was called
        mock_mutate.assert_called_once()
        insert_args = mock_mutate.call_args[0]
        assert "INSERT INTO user_identities" in insert_args[0]
        assert insert_args[1] == (existing_uuid, "cognito", "cognito-sub-bob", "bob@example.com")


def test_identity_resolution_new_profile_creation():
    """Step 4: When no mapping and no profile exist, create fresh user_profiles and link it."""
    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            return None
        if "FROM user_profiles" in sql and "LOWER(email) = LOWER(%s)" in sql:
            return []  # No profile with this email
        if "FROM user_profiles" in sql and "LOWER(username) = LOWER(%s)" in sql:
            return None  # Username not taken
        if "FROM user_profiles" in sql and "id = %s" in sql:
            # Query after insert
            new_id = params[0]
            return {
                "id": new_id,
                "email": "charlie@example.com",
                "username": "charlie",
                "name": "Charlie Brown",
                "avatar_url": "",
            }
        return None

    mutations = []

    def mock_mutate(sql, params=None, returning=False):
        mutations.append((sql, params))
        return 1

    with patch("services.rds_client.query", side_effect=mock_query), \
         patch("services.rds_client.mutate", side_effect=mock_mutate):
        claims = {
            "sub": "cognito-sub-charlie",
            "email": "charlie@example.com",
            "username": "charlie",
            "name": "Charlie Brown",
        }
        profile = resolve_user_identity(claims)

        assert profile["email"] == "charlie@example.com"
        assert profile["username"] == "charlie"
        assert profile["name"] == "Charlie Brown"

        # Verify mutations: user_profiles INSERT + user_identities INSERT
        assert len(mutations) == 2
        profile_sql, profile_params = mutations[0]
        assert "INSERT INTO user_profiles" in profile_sql
        new_uuid = profile_params[0]
        assert profile_params[1] == "charlie@example.com"
        assert profile_params[2] == "charlie"

        identity_sql, identity_params = mutations[1]
        assert "INSERT INTO user_identities" in identity_sql
        assert identity_params == (new_uuid, "cognito", "cognito-sub-charlie", "charlie@example.com")


def test_identity_resolution_username_collision_handling():
    """Step 4 edge case: If candidate username is already taken, suffix it uniquely."""
    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            return None
        if "FROM user_profiles" in sql and "LOWER(email) = LOWER(%s)" in sql:
            return []
        if "FROM user_profiles" in sql and "LOWER(username) = LOWER(%s)" in sql:
            # Candidate username "dave" is already taken
            return {"id": "other-user-uuid"}
        if "FROM user_profiles" in sql and "id = %s" in sql:
            new_id = params[0]
            return {
                "id": new_id,
                "email": "dave@example.com",
                "username": f"dave_{new_id[:6]}",
                "name": "Dave",
                "avatar_url": "",
            }
        return None

    mutations = []

    with patch("services.rds_client.query", side_effect=mock_query), \
         patch("services.rds_client.mutate", side_effect=lambda sql, params=None, returning=False: mutations.append((sql, params)) or 1):
        claims = {
            "sub": "cognito-sub-dave",
            "email": "dave@example.com",
            "username": "dave",
        }
        profile = resolve_user_identity(claims)

        profile_sql, profile_params = mutations[0]
        new_uuid = profile_params[0]
        inserted_username = profile_params[2]
        # Should have appended suffix derived from UUID
        assert inserted_username == f"dave_{new_uuid[:6]}".lower()


def test_unknown_kid_triggers_jwks_refresh_success(rsa_key_pair):
    """When a token has an unknown kid, trigger a single force-refresh of JWKS.
    If the refresh returns the key, verification should succeed.
    """
    key_2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_2 = json.loads(RSAAlgorithm.to_jwk(key_2.public_key()))
    jwk_2["kid"] = "rotated-key-id-002"
    jwk_2["use"] = "sig"
    jwk_2["alg"] = "RS256"

    # Cache only has key 1 initially
    set_cached_jwks({"keys": [rsa_key_pair["jwk"]]})

    token = make_test_token(key_2, kid="rotated-key-id-002", sub="user-rotated-key")

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": [rsa_key_pair["jwk"], jwk_2]}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        claims = verify_cognito_token(token)
        assert claims["sub"] == "user-rotated-key"
        assert mock_get.call_count == 1
        expected_url = "https://cognito-idp.ap-south-2.amazonaws.com/ap-south-2_testPoolId/.well-known/jwks.json"
        mock_get.assert_called_with(expected_url, timeout=5)


def test_cross_pool_cache_isolation(rsa_key_pair):
    """JWKS cache uses compound key (user_pool_id, kid); keys from pool A must not bleed into pool B."""
    clear_jwks_cache()

    pool_a = "ap-south-2_poolA"
    pool_b = "ap-south-2_poolB"

    # Populate cache for pool_a
    set_cached_jwks({"keys": [rsa_key_pair["jwk"]]}, user_pool_id=pool_a)

    # Token issued for pool_b with same kid
    token_b = make_test_token(
        rsa_key_pair["private_key"],
        kid=rsa_key_pair["kid"],
        iss=f"https://cognito-idp.ap-south-2.amazonaws.com/{pool_b}",
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"keys": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_resp) as mock_get:
        with pytest.raises(InvalidTokenError) as exc_info:
            verify_cognito_token(token_b, user_pool_id=pool_b)
        assert "not found in cognito jwks" in str(exc_info.value).lower()
        mock_get.assert_called_with(
            f"https://cognito-idp.ap-south-2.amazonaws.com/{pool_b}/.well-known/jwks.json",
            timeout=5,
        )


def test_strict_mock_guard_in_production(monkeypatch):
    """In production environment, mock tokens must fail closed with CognitoAuthError."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TESTING", raising=False)

    with pytest.raises(CognitoAuthError) as exc_info:
        verify_cognito_token("mock-access-token")
    assert "forbidden in production" in str(exc_info.value).lower()


def test_strict_mock_guard_when_not_in_test_mode(monkeypatch):
    """When TESTING is false or unset, mock tokens must fail closed with CognitoAuthError."""
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    with pytest.raises(CognitoAuthError) as exc_info:
        verify_cognito_token("mock:sub123:email@test.com:username")
    assert "forbidden in production and staging" in str(exc_info.value).lower()


def test_production_default_pool_and_client_id_eliminated(monkeypatch):
    """In production environment, test default IDs are eliminated and raise CognitoAuthError."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("COGNITO_USER_POOL_ID", raising=False)
    monkeypatch.delenv("COGNITO_CLIENT_ID", raising=False)

    with pytest.raises(CognitoAuthError) as exc_pool:
        get_cognito_user_pool_id()
    assert "missing or invalid cognito_user_pool_id" in str(exc_pool.value).lower()

    with pytest.raises(CognitoAuthError) as exc_client:
        get_cognito_client_id()
    assert "missing or invalid cognito_client_id" in str(exc_client.value).lower()

    with pytest.raises(CognitoAuthError) as exc_attr:
        _ = getattr(cognito_auth, "DEFAULT_USER_POOL_ID")
    assert "forbidden in production/staging" in str(exc_attr.value).lower()


def test_unverified_email_linking_policy():
    """If email_verified is explicitly False in claims, do NOT link to existing profile."""
    existing_uuid = "33333333-4444-5555-6666-777777777777"
    mock_existing_profile = {
        "id": existing_uuid,
        "email": "eve@example.com",
        "username": "eve",
        "name": "Eve Real",
        "avatar_url": "",
    }

    def mock_query(sql, params=None, fetch="all"):
        if "FROM user_identities" in sql:
            return None
        if "FROM user_profiles" in sql and "LOWER(email) = LOWER(%s)" in sql:
            return [mock_existing_profile]
        if "FROM user_profiles" in sql and "LOWER(username) = LOWER(%s)" in sql:
            return None
        if "FROM user_profiles" in sql and "id = %s" in sql:
            return {
                "id": params[0],
                "email": "eve@example.com",
                "username": "eve_fake",
                "name": "Eve Impostor",
                "avatar_url": "",
            }
        return None

    mutations = []
    with patch("services.rds_client.query", side_effect=mock_query), \
         patch("services.rds_client.mutate", side_effect=lambda sql, params=None, returning=False: mutations.append((sql, params)) or 1):
        claims = {
            "sub": "attacker-cognito-sub",
            "email": "eve@example.com",
            "email_verified": False,
            "username": "eve_fake",
            "name": "Eve Impostor",
        }
        profile = resolve_user_identity(claims)

        assert profile["id"] != existing_uuid
        assert len(mutations) == 2
        new_uuid = mutations[0][1][0]
        assert new_uuid != existing_uuid
