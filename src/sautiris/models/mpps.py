"""MPPSInstance model for DICOM MPPS state tracking (Issue #14)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class MPPSStatusEnum(StrEnum):
    IN_PROGRESS = "IN PROGRESS"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"


# Valid MPPS state transitions (HIGH-3: typed with enum keys/values)
VALID_MPPS_TRANSITIONS: dict[MPPSStatusEnum, set[MPPSStatusEnum]] = {
    MPPSStatusEnum.IN_PROGRESS: {MPPSStatusEnum.COMPLETED, MPPSStatusEnum.DISCONTINUED},
    MPPSStatusEnum.COMPLETED: set(),
    MPPSStatusEnum.DISCONTINUED: set(),
}


class MPPSInstance(TenantAwareBase):
    """Persisted DICOM Modality Performed Procedure Step instance."""

    __tablename__ = "mpps_instances"
    __table_args__ = (
        Index("ix_mpps_instances_sop_uid", "sop_instance_uid"),
        Index("ix_mpps_instances_worklist", "worklist_item_id"),
    )

    sop_instance_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # HIGH-2: typed with MPPSStatusEnum instead of str
    status: Mapped[MPPSStatusEnum] = mapped_column(String(32), default=MPPSStatusEnum.IN_PROGRESS)
    performed_station_ae: Mapped[str | None] = mapped_column(String(64), default=None)
    modality: Mapped[str | None] = mapped_column(String(16), default=None)
    performed_procedure_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    performed_procedure_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    worklist_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("worklist_items.id"), default=None
    )
    attributes: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
