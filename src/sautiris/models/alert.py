"""CriticalAlert model."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class AlertType(StrEnum):
    CRITICAL_FINDING = "CRITICAL_FINDING"
    UNEXPECTED_FINDING = "UNEXPECTED_FINDING"
    INCIDENTAL = "INCIDENTAL"


class AlertUrgency(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    URGENT = "URGENT"
    NON_URGENT = "NON_URGENT"


class NotificationMethod(StrEnum):
    IN_APP = "IN_APP"
    SMS = "SMS"
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class CriticalAlert(TenantAwareBase):
    __tablename__ = "critical_alerts"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("radiology_reports.id"), default=None
    )
    alert_type: Mapped[AlertType] = mapped_column(String(32))
    finding_description: Mapped[str | None] = mapped_column(Text, default=None)
    urgency: Mapped[AlertUrgency] = mapped_column(String(16), default=AlertUrgency.URGENT)
    notified_physician_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    notified_physician_name: Mapped[str | None] = mapped_column(String(255), default=None)
    notification_method: Mapped[NotificationMethod | None] = mapped_column(String(16), default=None)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
