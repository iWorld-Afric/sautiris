"""Tests for health check endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from sautiris.api.v1.health import router


@pytest.fixture
def health_app():  # type: ignore[no-untyped-def]
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.mark.asyncio
async def test_health_check(health_app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "sautiris"


@pytest.mark.asyncio
async def test_pacs_health(health_app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health/pacs")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_configured"


@pytest.mark.asyncio
async def test_dicom_health(health_app):  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=health_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health/dicom")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_configured"
