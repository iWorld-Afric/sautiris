"""ApiKey model — secure API key storage with SHA-256 hashing."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class ApiKey(TenantAwareBase):
    """A hashed API key scoped to a tenant and user.

    The raw key is **never** stored — only the SHA-256 hex digest.
    Lookup is performed by ``key_prefix`` (fast indexed scan) followed by
    a constant-time HMAC comparison of the stored hash.

    Key format: ``sautiris_<48 url-safe base64 chars>``
    Prefix: first 12 characters of the full key (``sautiris_XXX``).
    """

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(255))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String(12), index=True)
    # user_id references the external identity provider's user subject
    user_id: Mapped[uuid.UUID] = mapped_column()
    # MEDIUM-9: Permission validation (against Permission enum) is intentionally
    # delegated to the API/Pydantic layer (ApiKeyCreate schema) rather than the
    # model layer, as SQLAlchemy JSONB columns don't enforce element-level types.
    permissions: Mapped[list[str]] = mapped_column(JSONB, default=list)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
