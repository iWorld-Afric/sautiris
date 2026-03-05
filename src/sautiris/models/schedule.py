"""ScheduleSlot model."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sautiris.models.base import TenantAwareBase


class SlotStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    ARRIVED = "ARRIVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScheduleSlot(TenantAwareBase):
    __tablename__ = "schedule_slots"
    __table_args__ = (
        Index("ix_schedule_slots_order", "order_id"),
        Index("ix_schedule_slots_room", "room_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    room_id: Mapped[str] = mapped_column(String(64))
    modality: Mapped[str] = mapped_column(String(16))
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    technologist_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    technologist_name: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(32), default=SlotStatus.AVAILABLE)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    order: Mapped[RadiologyOrder] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="schedule_slots"
    )
