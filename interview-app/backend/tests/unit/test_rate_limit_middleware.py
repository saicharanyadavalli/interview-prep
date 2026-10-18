"""Unit tests for RateLimitAuthMiddleware."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from starlette.requests import Request
from starlette.responses import Response

from middleware.rate_limit_middleware import RateLimitAuthMiddleware


@pytest.mark.asyncio
async def test_middleware_extracts_user_id_on_valid_bearer_token():
    """Verify middleware extracts user_id from verified token onto request.state."""
    middleware = RateLimitAuthMiddleware(app=MagicMock())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [(b"authorization", b"Bearer valid-user-token")],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        return Response("ok", status_code=200)

    with patch("middleware.rate_limit_middleware.verify_supabase_token", return_value={"id": "user-uuid-123"}):
        await middleware.dispatch(request, call_next)

    assert request.state.rate_limit_user_id == "user-uuid-123"


@pytest.mark.asyncio
async def test_middleware_extracts_user_id_on_valid_cognito_token():
    """Verify middleware extracts user sub/id from verified Cognito token onto request.state."""
    middleware = RateLimitAuthMiddleware(app=MagicMock())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [(b"authorization", b"Bearer cognito-token-xyz")],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        return Response("ok", status_code=200)

    with patch("middleware.rate_limit_middleware.verify_cognito_token", return_value={"sub": "cognito-user-sub-456"}):
        await middleware.dispatch(request, call_next)

    assert request.state.rate_limit_user_id == "cognito-user-sub-456"


@pytest.mark.asyncio
async def test_middleware_sets_none_when_no_auth_header():
    """Verify middleware sets rate_limit_user_id to None for anonymous requests."""
    middleware = RateLimitAuthMiddleware(app=MagicMock())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [],
    }
    request = Request(scope)

    async def call_next(req: Request) -> Response:
        return Response("ok", status_code=200)

    await middleware.dispatch(request, call_next)
    assert request.state.rate_limit_user_id is None
