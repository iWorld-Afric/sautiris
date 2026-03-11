"""Tests for security fixes in api/deps.py — tenant mismatch (SEC-1) and API key scope (SEC-3)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from sautiris.core.auth.base import AuthUser

# ---------------------------------------------------------------------------
# SEC-1: X-Tenant-ID header mismatch → 403
# ---------------------------------------------------------------------------


def _make_deps_app(user: AuthUser) -> FastAPI:
    """Minimal FastAPI app wired with get_current_user and require_permission."""
    from sautiris.api.deps import get_current_user, require_permission

    app = FastAPI()

    # Mock auth provider that always returns the given user
    mock_provider = AsyncMock()
    mock_provider.get_current_user = AsyncMock(return_value=user)
    app.state.auth_provider = mock_provider

    from fastapi import Depends

    @app.get("/test")
    async def test_endpoint(u: AuthUser = Depends(get_current_user)) -> dict[str, str]:
        return {"tenant": str(u.tenant_id)}

    @app.get("/protected")
    async def protected_endpoint(
        u: AuthUser = Depends(require_permission("order:read")),
    ) -> dict[str, str]:
        return {"user": u.username}

    return app


class TestTenantIdMismatch:
    """SEC-1: X-Tenant-ID header that doesn't match JWT tenant → 403."""

    @pytest.fixture
    def user(self) -> AuthUser:
        return AuthUser(
            user_id=uuid.uuid4(),
            username="testuser",
            email="test@example.com",
            tenant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            roles=("radiologist",),
            permissions=("order:read",),
        )

    async def test_matching_header_allowed(self, user: AuthUser) -> None:
        """X-Tenant-ID matches JWT tenant → request proceeds normally."""
        app = _make_deps_app(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/test",
                headers={"X-Tenant-ID": str(user.tenant_id)},
            )
        assert resp.status_code == 200
        assert resp.json()["tenant"] == str(user.tenant_id)

    async def test_no_header_allowed(self, user: AuthUser) -> None:
        """No X-Tenant-ID header → request proceeds (header is optional)."""
        app = _make_deps_app(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/test")
        assert resp.status_code == 200

    async def test_mismatched_header_returns_403(self, user: AuthUser) -> None:
        """X-Tenant-ID differs from JWT tenant → 403."""
        app = _make_deps_app(user)
        wrong_tenant = str(uuid.uuid4())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/test",
                headers={"X-Tenant-ID": wrong_tenant},
            )
        assert resp.status_code == 403
        assert "does not match" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# SEC-3: API key scope enforcement in require_permission
# ---------------------------------------------------------------------------


class TestApiKeyScopeEnforcement:
    """SEC-3: require_permission checks user.permissions (not just roles)."""

    async def test_api_key_user_with_permission_passes(self) -> None:
        """API key user with 'service' role + explicit permission → 200."""
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="api-key-service",
            tenant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            roles=("service",),  # not in ROLE_PERMISSIONS
            permissions=("order:read",),  # explicit permission
        )
        app = _make_deps_app(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/protected")
        assert resp.status_code == 200

    async def test_api_key_user_without_permission_rejected(self) -> None:
        """API key user with 'service' role but missing permission → 403."""
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="api-key-no-perm",
            tenant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            roles=("service",),
            permissions=("report:read",),  # doesn't have order:read
        )
        app = _make_deps_app(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/protected")
        assert resp.status_code == 403

    async def test_role_based_user_still_works(self) -> None:
        """Standard role-based user passes via ROLE_PERMISSIONS as before."""
        user = AuthUser(
            user_id=uuid.uuid4(),
            username="radiologist",
            tenant_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            roles=("radiologist",),  # radiologist has order:read in ROLE_PERMISSIONS
            permissions=(),
        )
        app = _make_deps_app(user)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/protected")
        assert resp.status_code == 200
