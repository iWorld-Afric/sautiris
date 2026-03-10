"""API key authentication provider — validates keys via the ApiKey repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sautiris.core.auth.base import AuthProvider, AuthUser

if TYPE_CHECKING:
    from sautiris.models.apikey import ApiKey

logger = structlog.get_logger(__name__)


class APIKeyAuthProvider(AuthProvider):
    """Validates ``X-API-Key`` (or configured header) against the ``api_keys`` table.

    Keys are stored as SHA-256 hashes. Lookup is performed by prefix (fast indexed
    scan) followed by a constant-time ``hmac.compare_digest`` comparison.
    """

    def __init__(
        self,
        header_name: str = "X-API-Key",
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ):
        self.header_name = header_name
        self._session_factory = session_factory

    async def authenticate(self, request: Request) -> AuthUser:
        raw_key = request.headers.get(self.header_name, "")
        if not raw_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid API key",
            )

        if self._session_factory is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication service unavailable",
            )

        async with self._session_factory() as session:
            # FIX-7: Replace assert (stripped by -O) with explicit type guard
            if not isinstance(session, AsyncSession):
                logger.error("auth.invalid_session_factory", type=type(session).__name__)
                raise RuntimeError(
                    f"session_factory returned {type(session)!r}, expected AsyncSession"
                )
            # We need a tenant_id to scope the lookup.  For the API key provider,
            # we look across a prefix match and then verify tenant from the stored key.
            # Use a cross-tenant repository (no tenant filter on prefix lookup).
            repo = _CrossTenantApiKeyRepository(session)
            api_key = await repo.verify_any_tenant(raw_key)

        if api_key is None:
            logger.warning("auth.apikey_invalid")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
            )

        return AuthUser(
            user_id=api_key.user_id,
            username=f"apikey:{api_key.key_prefix}",
            email="",
            tenant_id=api_key.tenant_id,
            roles=("service",),
            permissions=tuple(api_key.permissions),
        )

    async def get_current_user(self, request: Request) -> AuthUser:
        return await self.authenticate(request)

    async def check_permission(self, user: AuthUser, permission: str) -> bool:
        return permission in user.permissions


class _CrossTenantApiKeyRepository:
    """Internal helper: prefix lookup without tenant filter (for auth provider use only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def verify_any_tenant(self, raw_key: str) -> ApiKey | None:
        import hmac  # noqa: PLC0415
        from datetime import UTC, datetime  # noqa: PLC0415

        from sqlalchemy import select, update  # noqa: PLC0415

        from sautiris.models.apikey import ApiKey  # noqa: PLC0415
        from sautiris.repositories.apikey_repo import hash_key  # noqa: PLC0415

        prefix = raw_key[:12]
        stmt = select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        candidates = result.scalars().all()

        provided_hash = hash_key(raw_key)
        for candidate in candidates:
            if hmac.compare_digest(candidate.key_hash, provided_hash):
                if candidate.expires_at and candidate.expires_at < datetime.now(UTC):
                    return None
                # FIX-9: Update last_used_at so operators can see key activity
                try:
                    await self._session.execute(
                        update(ApiKey)
                        .where(ApiKey.id == candidate.id)
                        .values(last_used_at=datetime.now(UTC))
                    )
                    # Explicit commit ensures last_used_at persists regardless of
                    # the caller's transaction boundary.
                    await self._session.commit()
                except Exception:
                    logger.warning(
                        "auth.apikey_last_used_update_failed",
                        key_prefix=candidate.key_prefix,
                        exc_info=True,
                    )
                return candidate
        return None
