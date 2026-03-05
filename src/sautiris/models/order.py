"""RadiologyOrder model."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sautiris.models.base import TenantAwareBase


class OrderStatus(StrEnum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


class Urgency(StrEnum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    STAT = "STAT"
    ASAP = "ASAP"


class RadiologyOrder(TenantAwareBase):
    __tablename__ = "radiology_orders"
    __table_args__ = (
        Index("ix_radiology_orders_accession", "accession_number"),
        Index("ix_radiology_orders_patient", "patient_id"),
        Index("ix_radiology_orders_status", "status"),
        Index("ix_radiology_orders_scheduled", "scheduled_at"),
        Index("ix_radiology_orders_modality", "modality"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column()
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    accession_number: Mapped[str] = mapped_column(String(64), unique=True)
    order_number: Mapped[str | None] = mapped_column(String(64), default=None)
    requesting_physician_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    requesting_physician_name: Mapped[str | None] = mapped_column(String(255), default=None)
    modality: Mapped[str] = mapped_column(String(16))
    body_part: Mapped[str | None] = mapped_column(String(128), default=None)
    laterality: Mapped[str | None] = mapped_column(String(16), default=None)
    procedure_code: Mapped[str | None] = mapped_column(String(32), default=None)
    procedure_description: Mapped[str | None] = mapped_column(Text, default=None)
    clinical_indication: Mapped[str | None] = mapped_column(Text, default=None)
    patient_history: Mapped[str | None] = mapped_column(Text, default=None)
    urgency: Mapped[str] = mapped_column(String(16), default=Urgency.ROUTINE)
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.REQUESTED)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    study_instance_uid: Mapped[str | None] = mapped_column(String(128), default=None)
    special_instructions: Mapped[str | None] = mapped_column(Text, default=None)
    transport_mode: Mapped[str | None] = mapped_column(String(32), default=None)
    isolation_precautions: Mapped[str | None] = mapped_column(String(64), default=None)
    pregnant: Mapped[bool | None] = mapped_column(default=None)

    # Relationships
    schedule_slots: Mapped[list[ScheduleSlot]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="order", lazy="selectin"
    )
    reports: Mapped[list[RadiologyReport]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="order", lazy="selectin"
    )
