"""BillingCode and OrderBilling models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import Base, TenantAwareBase


class BillingCode(Base):
    """Reference table of CPT/ICD/SNOMED codes."""

    __tablename__ = "billing_codes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code_system: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(32))
    display: Mapped[str] = mapped_column(String(512))
    modality: Mapped[str | None] = mapped_column(String(16), default=None)
    body_part: Mapped[str | None] = mapped_column(String(128), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrderBilling(TenantAwareBase):
    __tablename__ = "order_billing"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    billing_code_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("billing_codes.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
