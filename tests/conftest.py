"""Shared test fixtures: async SQLite DB, test client, mock auth."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import JSON

import sautiris.api.deps as deps
from sautiris.core.auth.base import AuthProvider, AuthUser
from sautiris.core.events import EventBus
from sautiris.core.tenancy import set_current_tenant_id
from sautiris.models.base import Base

# ---------------------------------------------------------------------------
# JSONB → JSON compatibility patch for SQLite
# ---------------------------------------------------------------------------


@event.listens_for(Base.metadata, "before_create")
def _patch_jsonb_for_sqlite(target, connection, **kw):  # type: ignore[no-untyped-def]
    """Replace JSONB with JSON for SQLite compatibility."""
    if connection.dialect.name == "sqlite":
        for table in target.sorted_tables:
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()


# ---------------------------------------------------------------------------
# Test constants
# ---------------------------------------------------------------------------

TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_TENANT_B_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

_RADIOLOGIST_PERMS = [
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
]

_ADMIN_PERMS = _RADIOLOGIST_PERMS + [
    "order:create",
    "order:update",
    "order:cancel",
    "order:delete",
    "schedule:manage",
    "schedule:read",
    "billing:read",
    "billing:manage",
    "worklist:read",
    "worklist:manage",
    "admin:*",
]

_TECHNOLOGIST_PERMS = [
    "order:read",
    "order:update",
    "schedule:read",
    "schedule:manage",
    "dose:record",
    "dose:read",
    "worklist:read",
]

_CLERK_PERMS = [
    "order:create",
    "order:read",
    "order:update",
    "schedule:read",
    "schedule:manage",
    "worklist:read",
]

TEST_USER = AuthUser(
    user_id=TEST_USER_ID,
    username="test_radiologist",
    email="test@sautiris.test",
    tenant_id=TEST_TENANT_ID,
    roles=("radiologist",),
    permissions=tuple(_RADIOLOGIST_PERMS),
    name="Test Radiologist",
)

_USERS_BY_ROLE: dict[str, AuthUser] = {
    "admin": AuthUser(
        user_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        username="test_admin",
        email="admin@sautiris.test",
        tenant_id=TEST_TENANT_ID,
        roles=("admin",),
        permissions=tuple(_ADMIN_PERMS),
        name="Test Admin",
    ),
    "radiologist": TEST_USER,
    "technologist": AuthUser(
        user_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        username="test_tech",
        email="tech@sautiris.test",
        tenant_id=TEST_TENANT_ID,
        roles=("technologist",),
        permissions=tuple(_TECHNOLOGIST_PERMS),
        name="Test Technologist",
    ),
    "clerk": AuthUser(
        user_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        username="test_clerk",
        email="clerk@sautiris.test",
        tenant_id=TEST_TENANT_ID,
        roles=("registration_clerk",),
        permissions=tuple(_CLERK_PERMS),
        name="Test Clerk",
    ),
}

# ---------------------------------------------------------------------------
# DB engine (shared across session for speed)
# ---------------------------------------------------------------------------

engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class MockAuthProvider(AuthProvider):
    """Returns a configurable test user."""

    def __init__(self, user: AuthUser = TEST_USER) -> None:
        self._user = user

    async def authenticate(self, request: Any) -> AuthUser:
        return self._user

    async def get_current_user(self, request: Any) -> AuthUser:
        return self._user

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions


# ---------------------------------------------------------------------------
# Schema setup — once per session, using transaction rollback per test
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncGenerator[None, None]:
    """Create DB schema once for the whole test session."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _set_tenant() -> None:
    """Set the current tenant context for every test."""
    set_current_tenant_id(TEST_TENANT_ID)


@pytest.fixture(autouse=True)
def _reset_accession_locks() -> None:
    """Reset module-level asyncio.Lock objects to avoid cross-loop binding errors."""
    from sautiris.core.accession import reset_sqlite_locks

    reset_sqlite_locks()


@pytest.fixture
async def db_session(_create_schema: None) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean AsyncSession per test using transaction rollback."""
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()


# ---------------------------------------------------------------------------
# Application fixture for integration tests
# ---------------------------------------------------------------------------


def _make_ris_app(user: AuthUser | None = None) -> FastAPI:
    """Build a minimal test FastAPI app with all routers mounted."""
    from sautiris.api.router import api_router

    test_app = FastAPI()
    test_app.include_router(api_router, prefix="/api/v1")
    test_app.state.event_bus = EventBus()

    return test_app


def _apply_db_override(app: FastAPI, session: AsyncSession) -> FastAPI:
    """Override get_db to yield the provided test session."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[deps.get_db] = override_get_db
    return app


def _apply_auth_override(app: FastAPI, user: AuthUser) -> FastAPI:
    """Override get_current_user to return the provided test user."""

    async def override_get_current_user() -> AuthUser:
        return user

    app.dependency_overrides[deps.get_current_user] = override_get_current_user
    return app


@pytest.fixture
async def ris_app(db_session: AsyncSession) -> FastAPI:
    """Full API app for integration tests — radiologist user (default)."""
    app = _make_ris_app()
    _apply_db_override(app, db_session)
    _apply_auth_override(app, TEST_USER)
    return app


@pytest.fixture
async def client(ris_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client for the default (radiologist) app."""
    transport = ASGITransport(app=ris_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Role-based client fixtures
# ---------------------------------------------------------------------------


def _make_client_for_role(role: str) -> Any:
    @pytest.fixture
    async def _fixture(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
        app = _make_ris_app()
        _apply_db_override(app, db_session)
        _apply_auth_override(app, _USERS_BY_ROLE[role])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    return _fixture


admin_client = _make_client_for_role("admin")
radiologist_client = _make_client_for_role("radiologist")
technologist_client = _make_client_for_role("technologist")
clerk_client = _make_client_for_role("clerk")


@pytest.fixture
async def unauth_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client with no authentication override (will get 403 for protected routes)."""
    from fastapi import HTTPException

    app = _make_ris_app()
    _apply_db_override(app, db_session)

    async def _reject() -> AuthUser:
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[deps.get_current_user] = _reject
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Tenant-scoped test data helpers
# ---------------------------------------------------------------------------


@dataclass
class TenantTestData:
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    order: Any


async def create_test_order(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TEST_TENANT_ID,
    patient_id: uuid.UUID | None = None,
    modality: str = "CT",
    status: str = "COMPLETED",
    accession_number: str | None = None,
) -> Any:
    """Create and persist a test RadiologyOrder."""
    from sautiris.models.order import RadiologyOrder

    order = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        patient_id=patient_id or uuid.uuid4(),
        accession_number=accession_number or f"ACC-{uuid.uuid4().hex[:8]}",
        modality=modality,
        status=status,
    )
    session.add(order)
    await session.flush()
    await session.refresh(order)
    return order


@pytest.fixture
async def tenant_a_data(db_session: AsyncSession) -> TenantTestData:
    """Create a complete set of test data for tenant A."""
    patient_id = uuid.uuid4()
    order = await create_test_order(db_session, tenant_id=TEST_TENANT_ID, patient_id=patient_id)
    return TenantTestData(tenant_id=TEST_TENANT_ID, patient_id=patient_id, order=order)


@pytest.fixture
async def tenant_b_data(db_session: AsyncSession) -> TenantTestData:
    """Create a complete set of test data for tenant B (for isolation tests)."""
    patient_id = uuid.uuid4()
    order = await create_test_order(db_session, tenant_id=TEST_TENANT_B_ID, patient_id=patient_id)
    return TenantTestData(tenant_id=TEST_TENANT_B_ID, patient_id=patient_id, order=order)


# ---------------------------------------------------------------------------
# Legacy factory helpers (kept for existing service tests)
# ---------------------------------------------------------------------------


def make_order(
    db_session: AsyncSession,
    *,
    patient_id: uuid.UUID | None = None,
    modality: str = "CT",
    status: str = "COMPLETED",
    accession_number: str | None = None,
) -> Any:
    """Create (but do not persist) a RadiologyOrder."""
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
    """Create a RadiologyReport (not persisted)."""
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
