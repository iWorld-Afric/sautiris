"""Tests for error message sanitization — no internal details leak via API responses.

Covers:
- Fix 1: require_permission 403 does not expose permission name
- Fix 2: APIKeyAuthProvider 401 does not expose header name
- Fix 3: Rate limiter returns 400 when request.client is None
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from sautiris.api.middleware.rate_limit import RateLimitMiddleware
from sautiris.config import SautiRISSettings
from sautiris.core.auth.apikey import APIKeyAuthProvider

# ---------------------------------------------------------------------------
# Fix 1: require_permission must NOT leak the permission name
# ---------------------------------------------------------------------------


class TestRequirePermissionSanitization:
    """403 responses from require_permission must not contain the permission name."""

    async def test_403_does_not_contain_permission_name(self) -> None:
        """When a user lacks a permission, the 403 detail is generic."""
        from collections.abc import AsyncGenerator

        from sqlalchemy.ext.asyncio import AsyncSession

        import sautiris.api.deps as deps
        from sautiris.api.v1.alerts import router as alerts_router
        from sautiris.core.auth.base import AuthUser

        app = FastAPI()
        app.include_router(alerts_router, prefix="/api/v1")

        # User with NO permissions at all
        import uuid

        no_perms_user = AuthUser(
            user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            username="no_perms",
            email="no@perms.test",
            tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            roles=("viewer",),
            permissions=(),  # no permissions
        )

        async def override_get_current_user() -> AuthUser:
            return no_perms_user

        mock_session = AsyncMock(spec=AsyncSession)

        async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
            yield mock_session

        app.dependency_overrides[deps.get_current_user] = override_get_current_user
        app.dependency_overrides[deps.get_db] = override_get_db

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/alerts")
            assert resp.status_code == 403
            detail = resp.json()["detail"]
            assert detail == "Insufficient permissions"
            # Must NOT contain the actual permission name
            assert "alert:read" not in detail


# ---------------------------------------------------------------------------
# Fix 2: API key auth must NOT leak the header name
# ---------------------------------------------------------------------------


class TestAPIKeyAuthSanitization:
    """401 responses from API key auth must not expose the header name."""

    async def test_missing_header_does_not_expose_header_name(self) -> None:
        """When API key header is missing, the 401 detail is generic."""
        provider = APIKeyAuthProvider(header_name="X-Custom-Secret-Key", session_factory=None)
        scope: dict[str, Any] = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)

        with pytest.raises(Exception) as exc_info:
            await provider.authenticate(request)

        exc = exc_info.value
        assert exc.status_code == 401  # type: ignore[attr-defined]
        detail = exc.detail  # type: ignore[attr-defined]
        assert detail == "Missing or invalid API key"
        # Must NOT contain the custom header name
        assert "X-Custom-Secret-Key" not in detail
        assert "header" not in detail.lower()

    async def test_default_header_not_exposed_either(self) -> None:
        """Default X-API-Key header name is also not leaked."""
        provider = APIKeyAuthProvider(session_factory=None)
        scope: dict[str, Any] = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
        request = Request(scope)

        with pytest.raises(Exception) as exc_info:
            await provider.authenticate(request)

        detail = exc_info.value.detail  # type: ignore[attr-defined]
        assert "X-API-Key" not in detail


# ---------------------------------------------------------------------------
# Fix 3: Rate limiter returns 400 when request.client is None
# ---------------------------------------------------------------------------


def _make_limited_app(general_rate: str = "10/minute") -> FastAPI:
    """Create a minimal app with rate limiting enabled."""
    app = FastAPI()
    settings = SautiRISSettings(
        rate_limit_enabled=True,
        rate_limit_general=general_rate,
        rate_limit_auth_endpoints="2/minute",
        rate_limit_apikey_create="1/minute",
        rate_limit_trusted_ips=[],
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app.add_middleware(RateLimitMiddleware, settings=settings)

    @app.get("/data")
    async def data() -> JSONResponse:
        return JSONResponse({"ok": True})

    return app


class TestRateLimiterNullClient:
    """Rate limiter must return 400 when request.client is None."""

    async def test_null_client_returns_400(self) -> None:
        """When request.client is None, the rate limiter returns 400."""
        app = _make_limited_app()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="10/minute",
            rate_limit_auth_endpoints="2/minute",
            rate_limit_apikey_create="1/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        mw = RateLimitMiddleware(app, settings=settings)

        # Build a mock request with client=None
        mock_request = MagicMock(spec=Request)
        mock_request.client = None
        mock_request.url = MagicMock()
        mock_request.url.path = "/data"

        call_next = AsyncMock(return_value=JSONResponse({"ok": True}))
        response = await mw.dispatch(mock_request, call_next)

        assert response.status_code == 400
        # Verify the body content
        import json

        data = json.loads(response.body.decode())
        assert data["detail"] == "Unable to determine client address"

        # call_next must NOT have been called — request was rejected early
        call_next.assert_not_called()

    async def test_null_client_does_not_use_unknown_key(self) -> None:
        """Regression: 'unknown' must never be used as a rate limit key."""
        app = _make_limited_app()
        settings = SautiRISSettings(
            rate_limit_enabled=True,
            rate_limit_general="10/minute",
            rate_limit_auth_endpoints="2/minute",
            rate_limit_apikey_create="1/minute",
            rate_limit_trusted_ips=[],
            database_url="sqlite+aiosqlite:///:memory:",
        )
        mw = RateLimitMiddleware(app, settings=settings)

        mock_request = MagicMock(spec=Request)
        mock_request.client = None
        mock_request.url = MagicMock()
        mock_request.url.path = "/data"

        call_next = AsyncMock()
        await mw.dispatch(mock_request, call_next)

        # No "unknown" key should appear in the windows dict
        assert not any("unknown" in k for k in mw._windows)
