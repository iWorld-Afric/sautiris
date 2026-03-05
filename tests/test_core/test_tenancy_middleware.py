"""Tests for TenantMiddleware and tenant context management."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from sautiris.core.tenancy import (
    DEFAULT_TENANT,
    TenantMiddleware,
    get_current_tenant_id,
    set_current_tenant_id,
)


class TestTenantContext:
    """Tests for get/set tenant context."""

    def test_default_tenant(self) -> None:
        set_current_tenant_id(DEFAULT_TENANT)
        assert get_current_tenant_id() == DEFAULT_TENANT

    def test_set_custom_tenant(self) -> None:
        custom = uuid.uuid4()
        set_current_tenant_id(custom)
        assert get_current_tenant_id() == custom
        # Reset
        set_current_tenant_id(DEFAULT_TENANT)


class TestTenantMiddleware:
    """Tests for TenantMiddleware."""

    @pytest.fixture
    def tenant_app(self) -> Starlette:
        async def tenant_endpoint(request: Request) -> JSONResponse:
            return JSONResponse({"tenant_id": str(get_current_tenant_id())})

        app = Starlette(routes=[Route("/tenant", tenant_endpoint)])
        app.add_middleware(TenantMiddleware, header_name="X-Tenant-ID")
        return app

    async def test_no_header_uses_default(self, tenant_app: Starlette) -> None:
        transport = ASGITransport(app=tenant_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/tenant")
            assert resp.status_code == 200
            assert resp.json()["tenant_id"] == str(DEFAULT_TENANT)

    async def test_valid_header_sets_tenant(self, tenant_app: Starlette) -> None:
        custom_id = uuid.uuid4()
        transport = ASGITransport(app=tenant_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/tenant",
                headers={"X-Tenant-ID": str(custom_id)},
            )
            assert resp.status_code == 200
            assert resp.json()["tenant_id"] == str(custom_id)

    async def test_invalid_header_uses_default(self, tenant_app: Starlette) -> None:
        transport = ASGITransport(app=tenant_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/tenant",
                headers={"X-Tenant-ID": "not-a-uuid"},
            )
            assert resp.status_code == 200
            assert resp.json()["tenant_id"] == str(DEFAULT_TENANT)
