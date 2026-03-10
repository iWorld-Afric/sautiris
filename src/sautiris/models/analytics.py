"""TATMetric model for turnaround time analytics."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase
from sautiris.models.order import Urgency


class TATMetric(TenantAwareBase):
    __tablename__ = "tat_metrics"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    order_to_schedule_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    schedule_to_exam_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    exam_to_preliminary_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    exam_to_final_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    final_to_distributed_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    total_tat_mins: Mapped[int | None] = mapped_column(Integer, default=None)
    modality: Mapped[str | None] = mapped_column(String(16), default=None)
    urgency: Mapped[Urgency | None] = mapped_column(String(16), default=None)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
