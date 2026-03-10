"""AuditLog model for PHI access tracking."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID] = mapped_column()
    user_name: Mapped[str | None] = mapped_column(String(255), default=None)
    # Note: action and resource_type are free-form strings validated at the API
    # layer (audit_middleware.py).  No Python-level StrEnum currently exists for
    # these fields; a future migration can add one and type the columns with it.
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(128), default=None, index=True)
    details: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
