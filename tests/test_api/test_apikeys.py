"""Tests for API key management endpoints (issue #10)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import _ADMIN_PERMS, TEST_TENANT_ID, TEST_USER_ID


@pytest.fixture
async def admin_http_client(db_session: AsyncSession) -> AsyncClient:
    from fastapi import FastAPI
    from httpx import ASGITransport

    import sautiris.api.deps as deps
    from sautiris.api.router import api_router
    from sautiris.core.auth.base import AuthUser
    from sautiris.core.events import EventBus

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.state.event_bus = EventBus()

    admin_user = AuthUser(
        user_id=TEST_USER_ID,
        username="admin",
        email="admin@test.com",
        tenant_id=TEST_TENANT_ID,
        roles=["admin"],
        permissions=_ADMIN_PERMS + ["admin:full"],
        name="Admin",
    )

    async def _db():
        yield db_session

    async def _user():
        return admin_user

    app.dependency_overrides[deps.get_db] = _db
    app.dependency_overrides[deps.get_current_user] = _user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestApiKeyLifecycle:
    """Full lifecycle: create, list, get, revoke."""

    async def test_create_returns_raw_key_once(
        self, admin_http_client: AsyncClient
    ) -> None:
        resp = await admin_http_client.post(
            "/api/v1/apikeys",
            json={"name": "ci-key", "permissions": ["order:read"]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "raw_key" in data
        assert data["raw_key"].startswith("sautiris_")
        assert "key_hash" not in data  # hash must NOT be exposed
        assert data["name"] == "ci-key"
        assert data["permissions"] == ["order:read"]
        assert data["is_active"] is True

    async def test_list_keys(self, admin_http_client: AsyncClient) -> None:
        await admin_http_client.post(
            "/api/v1/apikeys",
            json={"name": "key-a"},
        )
        resp = await admin_http_client.get("/api/v1/apikeys")
        assert resp.status_code == 200
        keys = resp.json()
        assert isinstance(keys, list)
        assert any(k["name"] == "key-a" for k in keys)

    async def test_get_key_by_id(self, admin_http_client: AsyncClient) -> None:
        create_resp = await admin_http_client.post(
            "/api/v1/apikeys",
            json={"name": "get-test"},
        )
        key_id = create_resp.json()["id"]
        resp = await admin_http_client.get(f"/api/v1/apikeys/{key_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == key_id

    async def test_revoke_key(self, admin_http_client: AsyncClient) -> None:
        create_resp = await admin_http_client.post(
            "/api/v1/apikeys",
            json={"name": "revoke-test"},
        )
        key_id = create_resp.json()["id"]
        resp = await admin_http_client.delete(f"/api/v1/apikeys/{key_id}")
        assert resp.status_code == 204

        # Revoked key is still visible (for audit) but marked inactive
        get_resp = await admin_http_client.get(f"/api/v1/apikeys/{key_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["is_active"] is False

    async def test_get_nonexistent_returns_404(
        self, admin_http_client: AsyncClient
    ) -> None:
        resp = await admin_http_client.get(f"/api/v1/apikeys/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestApiKeyRepository:
    """Unit tests for ApiKeyRepository hash/verify logic."""

    async def test_generate_key_format(self) -> None:
        from sautiris.repositories.apikey_repo import generate_api_key

        raw, key_hash, prefix = generate_api_key()
        assert raw.startswith("sautiris_")
        assert len(key_hash) == 64  # SHA-256 hex
        assert raw.startswith(prefix)
        assert len(prefix) == 12

    async def test_hash_is_deterministic(self) -> None:
        from sautiris.repositories.apikey_repo import hash_key

        assert hash_key("sautiris_abc") == hash_key("sautiris_abc")

    async def test_create_and_verify(self, db_session: AsyncSession) -> None:
        from sautiris.repositories.apikey_repo import ApiKeyRepository

        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        raw_key, api_key = await repo.create(
            name="test",
            user_id=TEST_USER_ID,
            permissions=["read"],
            scopes=[],
        )
        assert api_key.key_hash  # stored
        # raw key is never the hash
        assert api_key.key_hash != raw_key

        verified = await repo.verify(raw_key)
        assert verified is not None
        assert verified.id == api_key.id

    async def test_wrong_key_returns_none(self, db_session: AsyncSession) -> None:
        from sautiris.repositories.apikey_repo import ApiKeyRepository

        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        await repo.create(
            name="test",
            user_id=TEST_USER_ID,
            permissions=[],
            scopes=[],
        )
        result = await repo.verify("sautiris_wrongkey12345678901234567890")
        assert result is None

    async def test_cross_tenant_isolation(self, db_session: AsyncSession) -> None:
        """A key from tenant A must not be found via tenant B repository."""
        from sautiris.repositories.apikey_repo import ApiKeyRepository

        tenant_a = TEST_TENANT_ID
        tenant_b = uuid.UUID("00000000-0000-0000-0000-000000000002")

        repo_a = ApiKeyRepository(db_session, tenant_a)
        raw_key, _ = await repo_a.create(
            name="a-key",
            user_id=TEST_USER_ID,
            permissions=[],
            scopes=[],
        )

        repo_b = ApiKeyRepository(db_session, tenant_b)
        result = await repo_b.verify(raw_key)
        assert result is None  # cross-tenant lookup must fail


# ---------------------------------------------------------------------------
# GAP-C1, GAP-C2, GAP-C3: ApiKeyRepository verify/revoke edge cases
# ---------------------------------------------------------------------------


class TestApiKeyRepositoryGaps:
    """Gap coverage for ApiKeyRepository.verify() and revoke()."""

    async def test_verify_expired_key_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """GAP-C1: verify() returns None for a key whose expires_at is in the past.

        Note: SQLite returns naive datetimes, but the source compares with
        datetime.now(UTC) (aware). We patch the module-level datetime to
        return a naive "now" matching SQLite's output so the comparison works.
        """
        from datetime import datetime
        from unittest.mock import patch

        from sautiris.repositories.apikey_repo import ApiKeyRepository

        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        # Store a naive past datetime — SQLite stores/returns datetimes as naive
        past_dt = datetime(2020, 1, 1, 0, 0, 0)
        raw_key, _ = await repo.create(
            name="expired-key",
            user_id=TEST_USER_ID,
            permissions=[],
            scopes=[],
            expires_at=past_dt,
        )
        # Patch datetime.now in the repo module to return a naive "now" so that
        # the comparison (naive < naive) succeeds without TypeError
        with patch("sautiris.repositories.apikey_repo.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 9, 12, 0, 0)
            result = await repo.verify(raw_key)
        assert result is None

    async def test_verify_last_used_update_failure_returns_key(
        self, db_session: AsyncSession
    ) -> None:
        """GAP-C2: When last_used_at UPDATE fails, key is still returned (graceful degradation)
        and a warning is logged."""
        from unittest.mock import AsyncMock, MagicMock

        from structlog.testing import capture_logs

        from sautiris.repositories.apikey_repo import ApiKeyRepository

        # Create a real key so we have a valid api_key object with correct key_hash
        real_repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        raw_key, api_key = await real_repo.create(
            name="update-fail-key",
            user_id=TEST_USER_ID,
            permissions=[],
            scopes=[],
        )

        # Build a mock session: SELECT returns the real candidate, UPDATE raises
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [api_key]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[mock_result, RuntimeError("DB connection lost")]
        )

        verify_repo = ApiKeyRepository(mock_session, TEST_TENANT_ID)
        with capture_logs() as cap_logs:
            result = await verify_repo.verify(raw_key)

        # Key is still returned despite the UPDATE failure
        assert result is not None
        assert result.id == api_key.id
        # Warning is logged for the failure
        warning_events = [
            log for log in cap_logs if log.get("log_level") == "warning"
        ]
        assert any(
            "apikey_last_used_update_failed" in log.get("event", "")
            for log in warning_events
        ), f"Expected warning 'apikey_last_used_update_failed', got: {cap_logs}"

    async def test_revoke_then_verify_returns_none(
        self, db_session: AsyncSession
    ) -> None:
        """GAP-C3: verify() returns None after a key has been revoked."""
        from sautiris.repositories.apikey_repo import ApiKeyRepository

        repo = ApiKeyRepository(db_session, TEST_TENANT_ID)
        raw_key, api_key = await repo.create(
            name="revoke-verify-key",
            user_id=TEST_USER_ID,
            permissions=[],
            scopes=[],
        )

        revoked = await repo.revoke(api_key.id)
        assert revoked is True

        result = await repo.verify(raw_key)
        assert result is None
