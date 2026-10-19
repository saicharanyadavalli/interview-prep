"""Auth routes — Amazon Cognito authentication and RDS identity continuity.

Authenticates user access tokens issued by Amazon Cognito via RS256 JWKS verification,
resolves external IdP identities to authoritative Amazon RDS user_profiles (preserving UUIDs,
history, progress, and comments), and validates username availability.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
import jwt
from limiter import limiter

from models.schemas import (
    SessionRequest,
    ProvisionRequest,
    UserResponse,
    LoginRequest,
    LoginResponse,
    ResolveUsernameRequest,
    ResolveUsernameResponse,
)
from services import rds_client
from services.cognito_auth import (
    CognitoAuthError,
    get_cognito_client_id,
    get_cognito_region,
    is_production_or_staging,
    verify_cognito_id_token,
    verify_cognito_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def resolve_user_identity(
    claims: dict[str, Any],
    provider: str = "cognito",
) -> dict[str, Any]:
    """Resolve an external identity (e.g. Cognito sub) to an authoritative RDS user profile.

    Identity Continuity Algorithm:
    1. Check user_identities WHERE provider = 'cognito' AND provider_sub = %s.
    2. If mapping exists, return existing user_profiles row (preserving existing UUID
       and all user history/progress!).
    3. If no mapping exists, check user_profiles WHERE LOWER(email) = LOWER(%s).
       If an unambiguous matching profile exists, link it by inserting into user_identities
       and return the existing profile.
    4. If no profile exists, create a new user_profiles record with a fresh UUID and link
       it into user_identities.
    """
    provider_sub = str(claims.get("sub") or "").strip()
    if not provider_sub:
        raise ValueError("Missing 'sub' identifier in verified token claims.")

    raw_email = str(claims.get("email") or "").strip()
    clean_email = raw_email.lower() if raw_email else ""
    username_claim = str(
        claims.get("preferred_username")
        or claims.get("username")
        or claims.get("cognito:username")
        or ""
    ).strip()
    if username_claim.lower().startswith("google_"):
        username_claim = ""
    name_claim = str(claims.get("name") or claims.get("full_name") or claims.get("given_name") or "").strip()
    avatar_claim = str(claims.get("avatar_url") or claims.get("picture") or "").strip()

    # 1. Check user_identities WHERE provider = 'cognito' AND provider_sub = %s
    mapping = rds_client.query(
        """
        SELECT user_id, email
        FROM user_identities
        WHERE provider = %s AND provider_sub = %s
        LIMIT 1;
        """,
        (provider, provider_sub),
        fetch="one",
    )

    # 2. If mapping exists, return existing user_profiles row
    if mapping and mapping.get("user_id"):
        user_id = str(mapping["user_id"])
        profile = rds_client.query(
            """
            SELECT id, email, username, name, phone, avatar_url, updated_at
            FROM user_profiles
            WHERE id = %s
            LIMIT 1;
            """,
            (user_id,),
            fetch="one",
        )
        if profile:
            # Sync email on identity if previously empty
            if clean_email and not mapping.get("email"):
                try:
                    rds_client.mutate(
                        "UPDATE user_identities SET email = %s, updated_at = now() WHERE provider = %s AND provider_sub = %s;",
                        (clean_email, provider, provider_sub),
                    )
                except Exception:
                    pass
            # If username in RDS was empty or provider ID, populate it safely (never overwrite existing valid username)
            existing_uname = (profile.get("username") or "").strip()
            if not existing_uname or existing_uname.lower().startswith("google_"):
                fallback_username = (
                    username_claim
                    or (clean_email.split("@")[0] if clean_email else f"user_{user_id[:8]}")
                ).lower()
                if fallback_username and not fallback_username.startswith("google_"):
                    try:
                        taken = rds_client.query(
                            "SELECT id FROM user_profiles WHERE LOWER(username) = LOWER(%s) AND id != %s LIMIT 1;",
                            (fallback_username, user_id),
                            fetch="one",
                        )
                        if not taken:
                            rds_client.mutate(
                                "UPDATE user_profiles SET username = %s, updated_at = now() WHERE id = %s;",
                                (fallback_username, user_id),
                            )
                            profile["username"] = fallback_username
                    except Exception:
                        pass
            return dict(profile)

    # 3. If no mapping exists, check user_profiles WHERE LOWER(email) = LOWER(%s)
    # Verified email linking policy: keep existing profile UUID and history intact.
    # CRITICAL: Missing, None, invalid, or False email_verified claim is NEVER treated as verified!
    # Only an explicit email_verified is True authorizes automatic linking to an existing account.
    email_verified_claim = claims.get("email_verified")
    is_email_verified = False
    if email_verified_claim is True or (isinstance(email_verified_claim, str) and email_verified_claim.lower() == "true"):
        is_email_verified = True

    if clean_email and is_email_verified:
        matching_profiles = rds_client.query(
            """
            SELECT id, email, username, name, phone, avatar_url, updated_at
            FROM user_profiles
            WHERE LOWER(email) = LOWER(%s);
            """,
            (clean_email,),
            fetch="all",
        )
        if matching_profiles:
            # Ambiguous email matches:
            # If > 1 match (multiple profiles sharing email): REJECT automatic linking!
            # Fail safely with descriptive log/error. Never arbitrarily pick the first result.
            if len(matching_profiles) > 1:
                logger.error(
                    "Identity linking rejected: Ambiguous email match with %d user profiles found for %s (provider_sub: %s).",
                    len(matching_profiles),
                    clean_email,
                    provider_sub,
                )
                raise ValueError(
                    f"Ambiguous identity linking rejected: Multiple existing user profiles ({len(matching_profiles)}) match email."
                )

            # Exactly 1 eligible match: link under verified-email policy
            profile = dict(matching_profiles[0])

            if profile and profile.get("id"):
                user_id = str(profile["id"])

                # Prevent identity reassignment:
                # Do NOT use ON CONFLICT DO UPDATE that silently reassigns an already-linked provider_sub to a different user_id!
                # Insert with DO NOTHING and verify no conflicting mapping exists.
                try:
                    rds_client.mutate(
                        """
                        INSERT INTO user_identities (user_id, provider, provider_sub, email)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (provider, provider_sub) DO NOTHING;
                        """,
                        (user_id, provider, provider_sub, clean_email),
                    )
                except Exception as exc:
                    logger.error("Failed inserting user_identity during email linking: %s", exc)
                    raise

                # Re-read mapping to verify or handle concurrent linking / reassignment attempt
                existing_mapping = rds_client.query(
                    """
                    SELECT user_id, email
                    FROM user_identities
                    WHERE provider = %s AND provider_sub = %s
                    LIMIT 1;
                    """,
                    (provider, provider_sub),
                    fetch="one",
                )
                if existing_mapping and str(existing_mapping.get("user_id")) != user_id:
                    logger.error(
                        "Identity reassignment conflict: provider_sub '%s' already mapped to user_id '%s', cannot reassign to '%s'.",
                        provider_sub,
                        existing_mapping.get("user_id"),
                        user_id,
                    )
                    raise ValueError(
                        f"Identity conflict: Identity '{provider_sub}' is already linked to another account."
                    )

                # If username in RDS was empty or provider ID, populate it safely (never overwrite existing valid username)
                existing_uname = (profile.get("username") or "").strip()
                if not existing_uname or existing_uname.lower().startswith("google_"):
                    fallback_username = (
                        username_claim
                        or (clean_email.split("@")[0] if clean_email else f"user_{user_id[:8]}")
                    ).lower()
                    if fallback_username and not fallback_username.startswith("google_"):
                        try:
                            taken = rds_client.query(
                                "SELECT id FROM user_profiles WHERE LOWER(username) = LOWER(%s) AND id != %s LIMIT 1;",
                                (fallback_username, user_id),
                                fetch="one",
                            )
                            if not taken:
                                rds_client.mutate(
                                    "UPDATE user_profiles SET username = %s, updated_at = now() WHERE id = %s;",
                                    (fallback_username, user_id),
                                )
                                profile["username"] = fallback_username
                        except Exception:
                            pass

                return profile

    # 4. If no profile exists, create new user_profiles record with fresh UUID and link it
    new_user_id = str(uuid.uuid4())
    raw_username = (
        username_claim
        or (clean_email.split("@")[0] if clean_email else f"user_{new_user_id[:8]}")
    ).lower()
    base_username = raw_username[:40]
    candidate_username = base_username

    taken = rds_client.query(
        "SELECT id FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
        (candidate_username,),
        fetch="one",
    )
    if taken:
        candidate_username = f"{base_username[:33]}_{new_user_id[:6]}".lower()

    rds_client.mutate(
        """
        INSERT INTO user_profiles (id, email, username, name, avatar_url)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING;
        """,
        (new_user_id, clean_email, candidate_username, name_claim, avatar_claim),
    )

    # Insert into user_identities with DO NOTHING to prevent silent reassignment
    # and handle concurrent first-time sign-ins gracefully
    rds_client.mutate(
        """
        INSERT INTO user_identities (user_id, provider, provider_sub, email)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (provider, provider_sub) DO NOTHING;
        """,
        (new_user_id, provider, provider_sub, clean_email),
    )

    # Re-read mapping on conflict or to ensure atomic identity resolution
    existing_ident = rds_client.query(
        """
        SELECT user_id, email
        FROM user_identities
        WHERE provider = %s AND provider_sub = %s
        LIMIT 1;
        """,
        (provider, provider_sub),
        fetch="one",
    )

    resolved_id = str(existing_ident["user_id"]) if existing_ident and existing_ident.get("user_id") else new_user_id

    resolved_profile = rds_client.query(
        """
        SELECT id, email, username, name, phone, avatar_url, updated_at
        FROM user_profiles
        WHERE id = %s
        LIMIT 1;
        """,
        (resolved_id,),
        fetch="one",
    )
    if resolved_profile:
        return dict(resolved_profile)

    return {
        "id": resolved_id,
        "email": clean_email,
        "username": candidate_username,
        "name": name_claim,
        "avatar_url": avatar_claim,
    }


def _ensure_user_in_rds(user: dict) -> None:
    """Ensure authenticated user exists in RDS user_profiles table (legacy sync helper)."""
    user_id = str(user.get("id", "")).strip()
    if not user_id:
        return

    try:
        existing = rds_client.query(
            "SELECT id FROM user_profiles WHERE id = %s LIMIT 1",
            (user_id,),
            fetch="one",
        )
        if existing:
            return

        email = str(user.get("email", "")).strip()
        raw_username = (
            str(user.get("username", "")).strip()
            or (email.split("@")[0] if email else f"user_{user_id[:8]}")
        ).lower()
        base_username = raw_username[:40]

        username = base_username
        taken = rds_client.query(
            "SELECT id FROM user_profiles WHERE LOWER(username) = %s LIMIT 1",
            (username,),
            fetch="one",
        )
        if taken:
            username = f"{base_username}_{user_id[:6]}".lower()

        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, username, name, avatar_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email;
            """,
            (
                user_id,
                email,
                username,
                user.get("name", "") or "",
                user.get("avatar_url", "") or "",
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Could not auto-sync user %s into RDS: %s", user.get("id"), exc)
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable. Could not initialize user profile.",
        ) from exc


def get_current_user(authorization: str | None = Header(None)) -> dict:
    """Extract and verify the Bearer token from the Authorization header.

    Validates against Amazon Cognito User Pool via RS256 JWKS verification,
    resolves the internal RDS user via user_identities, and returns the
    authoritative user dictionary. Raises 401 on authentication failure.
    """
    if os.getenv("DISABLE_AUTH") == "true":
        if is_production_or_staging():
            logger.critical("SECURITY INVARIANT VIOLATION: DISABLE_AUTH is strictly forbidden in production and staging!")
            raise HTTPException(
                status_code=500,
                detail="Security misconfiguration: DISABLE_AUTH is forbidden in production/staging environment.",
            )

        logger.warning("DISABLE_AUTH is enabled — all requests bypass authentication. DO NOT use in production/staging.")
        mock_user = {
            "id": "12345678-1234-1234-1234-123456789012",
            "email": "testuser@example.com",
            "username": "testuser",
            "name": "Test User",
            "avatar_url": "",
        }
        _ensure_user_in_rds(mock_user)
        return mock_user

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid authorization header.")

    try:
        claims = verify_cognito_token(token)
    except CognitoAuthError as exc:
        logger.warning("Cognito token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")
    except Exception as exc:
        logger.warning("Token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    try:
        user = resolve_user_identity(claims)
        return user
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Could not resolve user identity in RDS: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable. Could not resolve user identity.",
        ) from exc


def get_optional_current_user(authorization: str | None = Header(None)) -> dict | None:
    """Return current user when Authorization header is valid, else None."""
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None

    try:
        claims = verify_cognito_token(token)
        if claims:
            return resolve_user_identity(claims)
    except Exception:
        pass
    return None


@router.post("/session", response_model=UserResponse)
@limiter.limit("5000/minute")
def create_session(request: Request, response: Response, payload: SessionRequest):
    """Validate Cognito token and synchronize/resolve user into RDS."""
    try:
        claims = verify_cognito_token(payload.access_token)
    except Exception as exc:
        logger.warning("Session token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    if payload.id_token:
        try:
            id_claims = verify_cognito_id_token(payload.id_token)
            for key in ("email", "email_verified", "name", "preferred_username", "picture", "avatar_url"):
                if key in id_claims:
                    if key not in claims or not claims[key] or key == "email_verified":
                        claims[key] = id_claims[key]
        except Exception as exc:
            logger.warning("Session ID token verification failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid or expired ID token.")

    try:
        db_user = resolve_user_identity(claims)
        return UserResponse(
            id=str(db_user["id"]),
            email=db_user["email"],
            username=db_user.get("username"),
            name=db_user.get("name"),
            avatar_url=db_user.get("avatar_url"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Session RDS user sync error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable. Could not synchronize user session.",
        ) from exc


@router.post("/login", response_model=LoginResponse)
@limiter.limit("30/minute")
def login_with_credentials(request: Request, response: Response, payload: LoginRequest):
    """Authenticate user with username or email and password without disclosing emails.

    SECURITY INVARIANTS:
    - Never exposes registered email addresses to unauthenticated callers.
    - Resolves username -> email privately within RDS.
    - Authenticates against Amazon Cognito using USER_PASSWORD_AUTH flow.
    - Handles unconfirmed users with 403 and needs_confirmation: true.
    - Returns uniform 401 'Invalid email/username or password.' for both non-existent
      users and incorrect passwords to prevent account enumeration.
    """
    raw_ident = payload.identifier.strip()
    if "@" in raw_ident:
        target_email = raw_ident.lower()
    else:
        try:
            row = rds_client.query(
                "SELECT email FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
                (raw_ident.lower(),),
                fetch="one",
            )
        except Exception as exc:
            logger.error("Database error during username lookup for %s: %s", raw_ident, exc)
            raise HTTPException(
                status_code=503,
                detail="Authentication service temporarily unavailable.",
            ) from exc

        if not row or not row.get("email"):
            raise HTTPException(status_code=401, detail="Invalid email/username or password.")
        target_email = row["email"].lower()

    region = get_cognito_region()
    client_id = get_cognito_client_id()
    cognito_client = boto3.client("cognito-idp", region_name=region)

    try:
        auth_res = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": target_email,
                "PASSWORD": payload.password,
            },
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "UserNotConfirmedException":
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "User is not confirmed. Please verify your email with the confirmation code.",
                    "needs_confirmation": True,
                },
            )
        elif error_code in ("NotAuthorizedException", "UserNotFoundException"):
            raise HTTPException(
                status_code=401,
                detail="Invalid email/username or password.",
            )
        else:
            logger.warning("Cognito initiate_auth ClientError (%s): %s", error_code, exc)
            raise HTTPException(
                status_code=401,
                detail="Invalid email/username or password.",
            )
    except Exception as exc:
        exc_type = type(exc).__name__
        if exc_type == "UserNotConfirmedException":
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "User is not confirmed. Please verify your email with the confirmation code.",
                    "needs_confirmation": True,
                },
            )
        elif exc_type in ("NotAuthorizedException", "UserNotFoundException"):
            raise HTTPException(
                status_code=401,
                detail="Invalid email/username or password.",
            )
        logger.error("Cognito initiate_auth unexpected error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Authentication service temporarily unavailable.",
        ) from exc

    auth_result = auth_res.get("AuthenticationResult")
    if not auth_result or "AccessToken" not in auth_result:
        logger.warning("Cognito initiate_auth succeeded but missing AuthenticationResult: %s", auth_res)
        raise HTTPException(status_code=401, detail="Invalid email/username or password.")

    access_token = auth_result["AccessToken"]
    refresh_token = auth_result.get("RefreshToken", "")
    id_token = auth_result.get("IdToken", "")
    expires_in = auth_result.get("ExpiresIn", 3600)

    try:
        claims = verify_cognito_token(access_token)
    except Exception as exc:
        logger.error("Failed to verify access token returned by Cognito: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Authentication token validation failed.",
        ) from exc

    if not claims.get("email"):
        claims["email"] = target_email

    if id_token:
        try:
            id_claims = verify_cognito_id_token(id_token)
            for key in ("email", "email_verified", "name", "preferred_username", "picture", "avatar_url"):
                if key in id_claims:
                    if key not in claims or not claims[key] or key == "email_verified":
                        claims[key] = id_claims[key]
        except Exception as exc:
            logger.warning("Cryptographic verification of Cognito ID token failed: %s", exc)

    try:
        db_user = resolve_user_identity(claims)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Session RDS user sync error during login: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Database service temporarily unavailable. Could not synchronize user session.",
        ) from exc

    # If login was performed with email, ensure RDS profile has preferred_username persisted
    if "@" in raw_ident and not db_user.get("username") and claims.get("preferred_username"):
        uname = str(claims["preferred_username"]).strip().lower()
        if uname and not uname.startswith("google_"):
            try:
                rds_client.mutate(
                    "UPDATE user_profiles SET username = %s, updated_at = now() WHERE id = %s AND (username IS NULL OR username = '');",
                    (uname, str(db_user["id"])),
                )
                db_user["username"] = uname
            except Exception:
                pass

    user_resp = UserResponse(
        id=str(db_user["id"]),
        email=str(db_user["email"]),
        username=db_user.get("username"),
        name=db_user.get("name"),
        avatar_url=db_user.get("avatar_url"),
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=user_resp,
    )


@router.post("/resolve-username")
@limiter.limit("30/minute")
def resolve_username(request: Request, response: Response, payload: ResolveUsernameRequest):
    """Deprecated endpoint disabled to prevent unauthenticated email harvesting."""
    raise HTTPException(
        status_code=404,
        detail="Deprecated: Unauthenticated username-to-email resolution has been removed for privacy protection. Use POST /auth/login instead.",
    )


@router.get("/check-username")
@limiter.limit("120/minute")
def check_username_availability(request: Request, response: Response, username: str = Query(..., min_length=3, max_length=50)):
    """Check if a username is available in RDS user_profiles (for client-side signup validation)."""
    try:
        clean = username.strip().lower()
        row = rds_client.query(
            "SELECT id FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
            (clean,),
            fetch="one",
        )
        return {"available": row is None, "username": clean}
    except Exception as exc:
        logger.warning("Error checking username availability for %s: %s", username, exc)
        raise HTTPException(
            status_code=503,
            detail="Database check failed. Unable to verify username availability.",
        )


@router.post("/provision", response_model=UserResponse)
@limiter.limit("120/minute")
def provision_user_profile(request: Request, response: Response, payload: ProvisionRequest):
    """Pre-provision or reconcile a user profile in RDS during registration.

    SECURITY INVARIANTS:
    - Never accepts or stores passwords in RDS.
    - Idempotent: safe for retries via ON CONFLICT handling.
    - Validates email and username format.
    - Preserves existing valid usernames (never overwrites an existing username with empty/provider ID).
    - Links user_identities if user_id (Cognito sub) is provided.
    """
    clean_email = payload.email.strip().lower()
    clean_username = payload.username.strip().lower()
    clean_name = payload.name.strip() if payload.name else ""
    provided_sub = payload.user_id.strip() if payload.user_id else ""

    if "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email format.")

    # Check if username is taken by a different email
    try:
        taken = rds_client.query(
            "SELECT id, email FROM user_profiles WHERE LOWER(username) = LOWER(%s) LIMIT 1;",
            (clean_username,),
            fetch="one",
        )
    except Exception as exc:
        logger.error("Database error checking username availability during provision: %s", exc)
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.") from exc

    if taken and taken.get("email", "").lower() != clean_email:
        raise HTTPException(
            status_code=409,
            detail=f"Username '{clean_username}' is already taken. Please choose another username.",
        )

    # Check if a profile already exists for this email
    try:
        existing = rds_client.query(
            "SELECT id, email, username, name, phone, avatar_url FROM user_profiles WHERE LOWER(email) = LOWER(%s) LIMIT 1;",
            (clean_email,),
            fetch="one",
        )
    except Exception as exc:
        logger.error("Database error checking existing profile during provision: %s", exc)
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.") from exc

    if existing:
        user_id = str(existing["id"])
        existing_username = (existing.get("username") or "").strip()
        final_username = (
            existing_username
            if (existing_username and not existing_username.lower().startswith("google_"))
            else clean_username
        )
        final_name = existing.get("name") or clean_name

        try:
            rds_client.mutate(
                """
                UPDATE user_profiles
                SET username = %s,
                    name = COALESCE(NULLIF(name, ''), %s),
                    updated_at = now()
                WHERE id = %s;
                """,
                (final_username, final_name, user_id),
            )

            if provided_sub:
                rds_client.mutate(
                    """
                    INSERT INTO user_identities (user_id, provider, provider_sub, email)
                    VALUES (%s, 'cognito', %s, %s)
                    ON CONFLICT (provider, provider_sub) DO NOTHING;
                    """,
                    (user_id, provided_sub, clean_email),
                )
        except Exception as exc:
            logger.error("Database error updating profile during provision: %s", exc)
            raise HTTPException(status_code=503, detail="Database service temporarily unavailable.") from exc

        return UserResponse(
            id=user_id,
            email=clean_email,
            username=final_username,
            name=final_name,
            avatar_url=existing.get("avatar_url") or "",
        )

    # Create new profile
    profile_id = ""
    if provided_sub:
        try:
            profile_id = str(uuid.UUID(provided_sub))
        except (ValueError, TypeError, AttributeError):
            profile_id = ""
    if not profile_id:
        profile_id = str(uuid.uuid4())

    try:
        rds_client.mutate(
            """
            INSERT INTO user_profiles (id, email, username, name, avatar_url)
            VALUES (%s, %s, %s, %s, '')
            ON CONFLICT (id) DO UPDATE
            SET email = EXCLUDED.email,
                username = COALESCE(NULLIF(user_profiles.username, ''), EXCLUDED.username),
                name = COALESCE(NULLIF(user_profiles.name, ''), EXCLUDED.name);
            """,
            (profile_id, clean_email, clean_username, clean_name),
        )

        if provided_sub:
            rds_client.mutate(
                """
                INSERT INTO user_identities (user_id, provider, provider_sub, email)
                VALUES (%s, 'cognito', %s, %s)
                ON CONFLICT (provider, provider_sub) DO NOTHING;
                """,
                (profile_id, provided_sub, clean_email),
            )
    except Exception as exc:
        logger.error("Database error inserting profile during provision: %s", exc)
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable.") from exc

    return UserResponse(
        id=profile_id,
        email=clean_email,
        username=clean_username,
        name=clean_name,
        avatar_url="",
    )

