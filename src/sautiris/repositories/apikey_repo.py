"""Repository for ApiKey CRUD operations."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.apikey import ApiKey

_KEY_PREFIX = "sautiris_"
_KEY_PREFIX_LENGTH = 12  # chars stored for indexed lookup


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (raw_key, key_hash, key_prefix) where:
          - raw_key   is shown to the user exactly once
          - key_hash  is stored (SHA-256 hex)
          - key_prefix is used for indexed DB lookups
    """
    raw_key = _KEY_PREFIX + secrets.token_urlsafe(36)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:_KEY_PREFIX_LENGTH]
    return raw_key, key_hash, key_prefix


def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKeyRepository:
    """Tenant-aware repository for ApiKey records."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def create(
        self,
        *,
        name: str,
        user_id: uuid.UUID,
        permissions: list[str],
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> tuple[str, ApiKey]:
        """Create a new API key.  Returns ``(raw_key, ApiKey)`` — raw_key is shown once."""
        raw_key, key_hash, key_prefix = generate_api_key()
        api_key = ApiKey(
            id=uuid.uuid4(),
            tenant_id=self._tenant_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            user_id=user_id,
            permissions=permissions,
            scopes=scopes,
            is_active=True,
            expires_at=expires_at,
        )
        self._session.add(api_key)
        await self._session.flush()
        await self._session.refresh(api_key)
        return raw_key, api_key

    async def verify(self, raw_key: str) -> ApiKey | None:
        """Look up and verify a raw API key.  Returns ``ApiKey`` if valid, else ``None``."""
        prefix = raw_key[:_KEY_PREFIX_LENGTH]
        stmt = select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.tenant_id == self._tenant_id,
            ApiKey.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        candidates = result.scalars().all()
        provided_hash = hash_key(raw_key)  # Compute once before loop — O(1) vs O(n)
        for candidate in candidates:
            if hmac.compare_digest(candidate.key_hash, provided_hash):
                if candidate.expires_at and candidate.expires_at < datetime.now(UTC):
                    return None
                # Update last_used_at without loading the whole object
                try:
                    await self._session.execute(
                        update(ApiKey)
                        .where(ApiKey.id == candidate.id)
                        .values(last_used_at=datetime.now(UTC))
                    )
                except Exception:
                    import structlog as _structlog  # noqa: PLC0415
                    _structlog.get_logger(__name__).warning(
                        "auth.apikey_last_used_update_failed",
                        key_prefix=candidate.key_prefix,
                        exc_info=True,
                    )
                return candidate
        return None

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        stmt = select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, *, offset: int = 0, limit: int = 100) -> list[ApiKey]:
        stmt = (
            select(ApiKey)
            .where(ApiKey.tenant_id == self._tenant_id)
            .order_by(ApiKey.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke(self, key_id: uuid.UUID) -> bool:
        """Deactivate a key.  Returns True if found, False if not found."""
        stmt = (
            update(ApiKey)
            .where(ApiKey.id == key_id, ApiKey.tenant_id == self._tenant_id)
            .values(is_active=False)
            .returning(ApiKey.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None
