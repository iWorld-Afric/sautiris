"""Tests for tenant context and JWT-based tenant isolation (issue #1).

TenantMiddleware has been removed — tenant_id now comes exclusively from the
authenticated user's JWT claim, set by the get_current_user dependency.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

import sautiris.api.deps as deps
from sautiris.core.auth.base import AuthUser
from sautiris.core.tenancy import (
    DEFAULT_TENANT,
    get_current_tenant_id,
    set_current_tenant_id,
)


class TestTenantContext:
    """Tests for get/set tenant context functions."""

    def test_default_tenant(self) -> None:
        set_current_tenant_id(DEFAULT_TENANT)
        assert get_current_tenant_id() == DEFAULT_TENANT

    def test_set_custom_tenant(self) -> None:
        custom = uuid.uuid4()
        set_current_tenant_id(custom)
        assert get_current_tenant_id() == custom
        # Reset
        set_current_tenant_id(DEFAULT_TENANT)


class TestTenantJwtIsolation:
    """Issue #1: tenant_id must come from JWT only, never from X-Tenant-ID header."""

    @pytest.fixture
    def tenant_app(self) -> FastAPI:
        """App that returns the tenant_id from the get_tenant_id dependency."""
        from fastapi.responses import JSONResponse

        app = FastAPI()

        @app.get("/tenant")
        async def get_tenant(
            tenant_id: uuid.UUID = Depends(deps.get_tenant_id),
        ) -> JSONResponse:
            return JSONResponse({"tenant_id": str(tenant_id)})

        return app

    async def test_header_alone_does_not_set_tenant(
        self, tenant_app: FastAPI
    ) -> None:
        """Sending X-Tenant-ID header without a valid JWT must not grant access."""
        attacker_tenant = uuid.uuid4()

        async def _reject_auth() -> AuthUser:
            from fastapi import HTTPException  # noqa: PLC0415

            raise HTTPException(status_code=401, detail="Not authenticated")

        tenant_app.dependency_overrides[deps.get_current_user] = _reject_auth
        transport = ASGITransport(app=tenant_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/tenant",
                headers={"X-Tenant-ID": str(attacker_tenant)},
            )
        assert resp.status_code == 401

    async def test_jwt_tenant_id_is_used(self, tenant_app: FastAPI) -> None:
        """get_tenant_id returns the tenant from the JWT-derived AuthUser."""
        jwt_tenant = uuid.uuid4()
        jwt_user = AuthUser(
            user_id=uuid.uuid4(),
            username="test",
            tenant_id=jwt_tenant,
            roles=[],
            permissions=[],
        )

        async def _mock_user() -> AuthUser:
            return jwt_user

        tenant_app.dependency_overrides[deps.get_current_user] = _mock_user
        transport = ASGITransport(app=tenant_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/tenant",
                # Even if attacker sends a different X-Tenant-ID, it must be ignored
                headers={"X-Tenant-ID": str(uuid.uuid4())},
            )
        assert resp.status_code == 200
        assert uuid.UUID(resp.json()["tenant_id"]) == jwt_tenant
