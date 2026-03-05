"""Shared test fixtures: async SQLite DB, test client, mock auth."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import JSON

from sautiris.core.auth.base import AuthProvider, AuthUser
from sautiris.core.tenancy import set_current_tenant_id
from sautiris.models.base import Base


# Register JSONB -> JSON type compilation for SQLite tests
@event.listens_for(Base.metadata, "before_create")
def _patch_jsonb_for_sqlite(target, connection, **kw):  # type: ignore[no-untyped-def]
    """Replace JSONB with JSON for SQLite compatibility."""
    if connection.dialect.name == "sqlite":
        for table in target.sorted_tables:
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()


TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TEST_USER = AuthUser(
    user_id=TEST_USER_ID,
    username="test_radiologist",
    email="test@sautiris.test",
    tenant_id=TEST_TENANT_ID,
    roles=["radiologist"],
    permissions=[
        "order:read",
        "report:read",
        "report:create",
        "report:finalize",
        "alert:create",
        "alert:read",
        "alert:acknowledge",
        "dose:read",
        "dose:record",
        "peer_review:create",
        "peer_review:read",
        "analytics:read",
    ],
    name="Test Radiologist",
)

engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class MockAuthProvider(AuthProvider):
    """Always returns TEST_USER."""

    async def authenticate(self, request: Any) -> AuthUser:
        return TEST_USER

    async def get_current_user(self, request: Any) -> AuthUser:
        return TEST_USER

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions


@pytest.fixture(autouse=True)
def _set_tenant() -> None:
    set_current_tenant_id(TEST_TENANT_ID)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI test app with all advanced feature routers mounted."""
    from sautiris.api.v1.alerts import router as alerts_router
    from sautiris.api.v1.dose import router as dose_router
    from sautiris.api.v1.peer_review import router as peer_review_router

    test_app = FastAPI()

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def get_user() -> AuthUser:
        return TEST_USER

    test_app.dependency_overrides[AsyncSession] = get_db  # type: ignore[index]
    test_app.include_router(alerts_router, prefix="/api/v1")
    test_app.include_router(peer_review_router, prefix="/api/v1")
    test_app.include_router(dose_router, prefix="/api/v1")

    # Store session getter for router deps
    test_app.state.db_session_factory = lambda: db_session
    test_app.state.auth_provider = MockAuthProvider()
    test_app.state.current_user = TEST_USER

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Factory helpers ---


def make_order(
    db_session: AsyncSession,
    *,
    patient_id: uuid.UUID | None = None,
    modality: str = "CT",
    status: str = "COMPLETED",
    accession_number: str | None = None,
) -> Any:
    """Create and flush a RadiologyOrder."""
    from sautiris.models.order import RadiologyOrder

    order = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=patient_id or uuid.uuid4(),
        accession_number=accession_number or f"ACC-{uuid.uuid4().hex[:8]}",
        modality=modality,
        status=status,
    )
    return order


def make_report(
    *,
    order_id: uuid.UUID,
    report_status: str = "FINAL",
    is_critical: bool = False,
    reported_by: uuid.UUID | None = None,
    accession_number: str = "ACC-TEST",
) -> Any:
    """Create a RadiologyReport."""
    from sautiris.models.report import RadiologyReport

    return RadiologyReport(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        order_id=order_id,
        accession_number=accession_number,
        report_status=report_status,
        is_critical=is_critical,
        reported_by=reported_by or TEST_USER_ID,
        reported_by_name="Test Radiologist",
        findings="Test findings",
        impression="Test impression",
        reported_at=datetime.now(UTC),
    )
