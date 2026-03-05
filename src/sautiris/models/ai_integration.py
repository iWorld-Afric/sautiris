"""AIProviderConfig and AIFinding models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class AIProviderConfig(TenantAwareBase):
    __tablename__ = "ai_provider_configs"

    provider_name: Mapped[str] = mapped_column(String(64))
    api_url: Mapped[str] = mapped_column(String(512))
    api_key: Mapped[str | None] = mapped_column(String(512), default=None)
    is_certified: Mapped[bool] = mapped_column(Boolean, default=False)
    supported_modalities: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    webhook_secret: Mapped[str | None] = mapped_column(String(512), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )


class AIFinding(TenantAwareBase):
    __tablename__ = "ai_findings"

    order_id: Mapped[uuid.UUID] = mapped_column(index=True)
    provider_config_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    finding_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float | None] = mapped_column(default=None)
    coordinates: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    raw_response: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
