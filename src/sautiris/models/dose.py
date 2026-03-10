"""DoseRecord model for radiation dose tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class DoseSource(StrEnum):
    MANUAL = "MANUAL"
    DICOM_SR = "DICOM_SR"
    MPPS = "MPPS"
    RDSR = "RDSR"


class DoseRecord(TenantAwareBase):
    __tablename__ = "dose_records"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    study_instance_uid: Mapped[str | None] = mapped_column(String(128), default=None)
    modality: Mapped[str] = mapped_column(String(16))
    ctdi_vol: Mapped[float | None] = mapped_column(Numeric(10, 4), default=None)
    dlp: Mapped[float | None] = mapped_column(Numeric(10, 4), default=None)
    dap: Mapped[float | None] = mapped_column(Numeric(10, 4), default=None)
    effective_dose: Mapped[float | None] = mapped_column(Numeric(10, 4), default=None)
    entrance_dose: Mapped[float | None] = mapped_column(Numeric(10, 4), default=None)
    num_exposures: Mapped[int | None] = mapped_column(Integer, default=None)
    kvp: Mapped[float | None] = mapped_column(Numeric(7, 2), default=None)
    tube_current_ma: Mapped[float | None] = mapped_column(Numeric(7, 2), default=None)
    exposure_time_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    protocol_name: Mapped[str | None] = mapped_column(String(255), default=None)
    body_part: Mapped[str | None] = mapped_column(String(128), default=None)
    exceeds_drl: Mapped[bool | None] = mapped_column(Boolean, default=None)
    source: Mapped[DoseSource] = mapped_column(String(16), default=DoseSource.MANUAL)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
