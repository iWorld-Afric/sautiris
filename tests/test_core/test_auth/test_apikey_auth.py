"""Tests for APIKeyAuthProvider — missing header, session_factory=None,
valid key, expired key, and last_used_at update.

GAP-2: APIKeyAuthProvider.authenticate() was untested.
GAP-5: API key expiry enforcement had zero tests.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from sautiris.core.auth.apikey import APIKeyAuthProvider


def _make_request(api_key: str = "", header_name: str = "X-API-Key") -> Any:
    """Return a minimal mock Request with the given API key header."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [
            (header_name.lower().encode(), api_key.encode()),
        ],
    }
    return Request(scope)


def _make_apikey_model(
    *,
    raw_key: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    permissions: list[str] | None = None,
    expires_at: datetime | None = None,
) -> MagicMock:
    """Create a mock ApiKey model object."""
    from sautiris.repositories.apikey_repo import hash_key

    key_prefix = raw_key[:12]
    key_hash = hash_key(raw_key)

    mock_key = MagicMock()
    mock_key.key_prefix = key_prefix
    mock_key.key_hash = key_hash
    mock_key.is_active = True
    mock_key.user_id = user_id
    mock_key.tenant_id = tenant_id
    mock_key.permissions = permissions or ["order:read"]
    mock_key.expires_at = expires_at
    return mock_key


class TestAPIKeyAuthProviderMissingHeader:
    """Tests for missing or empty header."""

    async def test_missing_header_returns_401(self) -> None:
        """No X-API-Key header → 401 Unauthorized."""
        provider = APIKeyAuthProvider(session_factory=None)
        request = _make_request(api_key="")  # empty header

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401

    async def test_custom_header_name_missing_returns_401(self) -> None:
        """Custom header name missing → 401."""
        provider = APIKeyAuthProvider(header_name="X-Custom-Key", session_factory=None)
        # Request has X-API-Key but not X-Custom-Key
        request = _make_request(api_key="some-key", header_name="X-API-Key")

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401


class TestAPIKeyAuthProviderNoSessionFactory:
    """Tests for session_factory=None configuration."""

    async def test_session_factory_none_returns_500(self) -> None:
        """session_factory=None with a key present → 500 Internal Server Error."""
        provider = APIKeyAuthProvider(session_factory=None)
        request = _make_request(api_key="sautiris_testkey1234567890abcdef")

        with pytest.raises(HTTPException) as exc_info:
            await provider.authenticate(request)

        assert exc_info.value.status_code == 500


def _make_session_factory(api_key_model: MagicMock | None = None) -> Any:
    """Build an async context-manager factory that yields a mock AsyncSession.

    The session mock has __class__ set to AsyncSession so it passes
    the isinstance(session, AsyncSession) guard in APIKeyAuthProvider.
    The verify_any_tenant return value is set at the repository level.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock()
    # Make isinstance(mock_session, AsyncSession) return True
    mock_session.__class__ = AsyncSession

    # Pre-configure execute to return a result with the expected key candidates
    if api_key_model is not None:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [api_key_model]
        mock_session.execute.return_value = mock_result

    @asynccontextmanager  # type: ignore[arg-type]
    async def _factory() -> Any:
        yield mock_session

    return _factory


class TestAPIKeyAuthProviderValidKey:
    """Tests for valid key authentication flow (verified via mocked repository)."""

    async def test_valid_key_returns_auth_user(self) -> None:
        """A valid key produces an AuthUser with correct tenant/user."""
        raw_key = "sautiris_validkey123456789012345678901234"
        tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        user_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

        api_key_model = _make_apikey_model(
            raw_key=raw_key,
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=["order:read", "report:read"],
        )
        provider = APIKeyAuthProvider(session_factory=_make_session_factory(api_key_model))
        request = _make_request(api_key=raw_key)

        with patch(
            "sautiris.core.auth.apikey._CrossTenantApiKeyRepository.verify_any_tenant",
            new_callable=AsyncMock,
            return_value=api_key_model,
        ):
            user = await provider.authenticate(request)

        assert user.user_id == user_id
        assert user.tenant_id == tenant_id
        assert "order:read" in user.permissions

    async def test_invalid_key_returns_401(self) -> None:
        """A key that fails repository verification → 401."""
        raw_key = "sautiris_badkey1234567890123456789012345"
        provider = APIKeyAuthProvider(session_factory=_make_session_factory())
        request = _make_request(api_key=raw_key)

        with (
            patch(
                "sautiris.core.auth.apikey._CrossTenantApiKeyRepository.verify_any_tenant",
                new_callable=AsyncMock,
                return_value=None,  # key not found
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await provider.authenticate(request)

        assert exc_info.value.status_code == 401
        # GAP-4: verify detail does not leak key value or prefix
        detail = exc_info.value.detail
        assert detail == "Invalid or expired API key"
        assert raw_key not in detail
        assert raw_key[:12] not in detail


class TestAPIKeyExpiry:
    """Tests for key expiry enforcement (GAP-5)."""

    async def test_expired_key_returns_none_from_repo(self) -> None:
        """A key with expires_at in the past returns None from verify_any_tenant."""
        from sautiris.core.auth.apikey import _CrossTenantApiKeyRepository
        from sautiris.repositories.apikey_repo import hash_key

        raw_key = "sautiris_expiredkey12345678901234567890"
        prefix = raw_key[:12]
        key_hash = hash_key(raw_key)

        expired_dt = datetime.now(UTC) - timedelta(hours=1)

        expired_key = MagicMock()
        expired_key.key_prefix = prefix
        expired_key.key_hash = key_hash
        expired_key.is_active = True
        expired_key.expires_at = expired_dt

        # Mock the session's execute to return the expired key
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expired_key]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        repo = _CrossTenantApiKeyRepository(mock_session)
        result = await repo.verify_any_tenant(raw_key)

        assert result is None  # expired key → None

    async def test_future_expiry_key_returns_valid(self) -> None:
        """A key with expires_at in the future is considered valid."""
        from sautiris.core.auth.apikey import _CrossTenantApiKeyRepository
        from sautiris.repositories.apikey_repo import hash_key

        raw_key = "sautiris_futurekey12345678901234567890"
        prefix = raw_key[:12]
        key_hash = hash_key(raw_key)

        future_dt = datetime.now(UTC) + timedelta(days=30)

        valid_key = MagicMock()
        valid_key.key_prefix = prefix
        valid_key.key_hash = key_hash
        valid_key.is_active = True
        valid_key.expires_at = future_dt
        valid_key.id = uuid.uuid4()
        valid_key.user_id = uuid.uuid4()
        valid_key.tenant_id = uuid.uuid4()
        valid_key.permissions = ["order:read"]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [valid_key]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        repo = _CrossTenantApiKeyRepository(mock_session)
        result = await repo.verify_any_tenant(raw_key)

        assert result is valid_key  # future expiry → valid

    async def test_no_expiry_key_returns_valid(self) -> None:
        """A key with no expiry (expires_at=None) is always valid."""
        from sautiris.core.auth.apikey import _CrossTenantApiKeyRepository
        from sautiris.repositories.apikey_repo import hash_key

        raw_key = "sautiris_noexpiry12345678901234567890ab"
        prefix = raw_key[:12]
        key_hash = hash_key(raw_key)

        no_expiry_key = MagicMock()
        no_expiry_key.key_prefix = prefix
        no_expiry_key.key_hash = key_hash
        no_expiry_key.is_active = True
        no_expiry_key.expires_at = None  # never expires
        no_expiry_key.id = uuid.uuid4()
        no_expiry_key.user_id = uuid.uuid4()
        no_expiry_key.tenant_id = uuid.uuid4()
        no_expiry_key.permissions = ["order:read"]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [no_expiry_key]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        repo = _CrossTenantApiKeyRepository(mock_session)
        result = await repo.verify_any_tenant(raw_key)

        assert result is no_expiry_key


class TestAPIKeyAuthProviderInvalidSessionFactory:
    """Tests for the RuntimeError guard when session_factory yields a non-AsyncSession."""

    async def test_invalid_session_factory_raises_runtime_error(self) -> None:
        """If session_factory yields a non-AsyncSession, RuntimeError is raised."""
        from contextlib import asynccontextmanager

        class NotASession:
            pass

        @asynccontextmanager  # type: ignore[arg-type]
        async def _bad_factory() -> Any:
            yield NotASession()

        provider = APIKeyAuthProvider(session_factory=_bad_factory)  # type: ignore[arg-type]
        request = _make_request(api_key="sautiris_validkey123456789012345678901234")

        with pytest.raises(RuntimeError, match="expected AsyncSession"):
            await provider.authenticate(request)


class TestLastUsedAtFailureResilience:
    """GAP-7: last_used_at update failure must not block authentication."""

    async def test_last_used_at_failure_still_authenticates(self) -> None:
        """If last_used_at UPDATE raises, the key is still returned (auth succeeds)."""
        from sautiris.core.auth.apikey import _CrossTenantApiKeyRepository
        from sautiris.repositories.apikey_repo import hash_key

        raw_key = "sautiris_resilience1234567890123456789"
        prefix = raw_key[:12]
        key_hash = hash_key(raw_key)

        valid_key = MagicMock()
        valid_key.key_prefix = prefix
        valid_key.key_hash = key_hash
        valid_key.is_active = True
        valid_key.expires_at = None
        valid_key.id = uuid.uuid4()
        valid_key.user_id = uuid.uuid4()
        valid_key.tenant_id = uuid.uuid4()
        valid_key.permissions = ["order:read"]

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [valid_key]

        mock_session = AsyncMock()
        # First execute returns the key candidates (SELECT)
        # Second execute (UPDATE last_used_at) raises an exception
        mock_session.execute.side_effect = [mock_result, RuntimeError("DB write failed")]

        repo = _CrossTenantApiKeyRepository(mock_session)
        result = await repo.verify_any_tenant(raw_key)

        # Auth must succeed despite last_used_at failure
        assert result is valid_key
