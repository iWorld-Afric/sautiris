"""WorklistItem model for DICOM Modality Worklist."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class WorklistStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class MPPSStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


class WorklistItem(TenantAwareBase):
    __tablename__ = "worklist_items"
    __table_args__ = (
        Index("ix_worklist_items_accession", "accession_number"),
        Index("ix_worklist_items_order", "order_id"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    schedule_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_slots.id"), default=None
    )
    accession_number: Mapped[str] = mapped_column(String(64))
    patient_id: Mapped[str] = mapped_column(String(64))
    patient_name: Mapped[str] = mapped_column(String(255))
    patient_dob: Mapped[date | None] = mapped_column(Date, default=None)
    patient_sex: Mapped[str | None] = mapped_column(String(1), default=None)
    modality: Mapped[str] = mapped_column(String(16))
    scheduled_station_ae_title: Mapped[str | None] = mapped_column(String(64), default=None)
    scheduled_procedure_step_id: Mapped[str | None] = mapped_column(String(64), default=None)
    scheduled_procedure_step_description: Mapped[str | None] = mapped_column(Text, default=None)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    requested_procedure_id: Mapped[str | None] = mapped_column(String(64), default=None)
    requested_procedure_description: Mapped[str | None] = mapped_column(Text, default=None)
    referring_physician_name: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[WorklistStatus] = mapped_column(String(32), default=WorklistStatus.SCHEDULED)
    mpps_status: Mapped[MPPSStatus | None] = mapped_column(String(32), default=None)
    mpps_uid: Mapped[str | None] = mapped_column(String(128), default=None)
    scheduled_performing_physician_name: Mapped[str | None] = mapped_column(
        String(255), default=None
    )
