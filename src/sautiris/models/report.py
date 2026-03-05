"""RadiologyReport, ReportTemplate, and ReportVersion models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sautiris.models.base import Base, TenantAwareBase


class ReportStatus(StrEnum):
    DRAFT = "DRAFT"
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    AMENDED = "AMENDED"
    CANCELLED = "CANCELLED"


class RadiologyReport(TenantAwareBase):
    __tablename__ = "radiology_reports"
    __table_args__ = (
        Index("ix_radiology_reports_order", "order_id"),
        Index("ix_radiology_reports_accession", "accession_number"),
        Index("ix_radiology_reports_status", "report_status"),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("report_templates.id"), default=None
    )
    accession_number: Mapped[str] = mapped_column(String(64))
    report_status: Mapped[str] = mapped_column(String(32), default=ReportStatus.DRAFT)
    findings: Mapped[str | None] = mapped_column(Text, default=None)
    impression: Mapped[str | None] = mapped_column(Text, default=None)
    recommendation: Mapped[str | None] = mapped_column(Text, default=None)
    technique: Mapped[str | None] = mapped_column(Text, default=None)
    comparison: Mapped[str | None] = mapped_column(Text, default=None)
    clinical_information: Mapped[str | None] = mapped_column(Text, default=None)
    body: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    is_addendum: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("radiology_reports.id"), default=None
    )
    reported_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    reported_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    approved_by_name: Mapped[str | None] = mapped_column(String(255), default=None)
    transcribed_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    distributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    order: Mapped[RadiologyOrder] = relationship(  # type: ignore[name-defined]  # noqa: F821
        back_populates="reports"
    )
    versions: Mapped[list[ReportVersion]] = relationship(back_populates="report", lazy="selectin")


class ReportTemplate(TenantAwareBase):
    __tablename__ = "report_templates"

    name: Mapped[str] = mapped_column(String(255))
    modality: Mapped[str | None] = mapped_column(String(16), default=None)
    body_part: Mapped[str | None] = mapped_column(String(128), default=None)
    sections: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(default=None)


class ReportVersion(Base):
    __tablename__ = "report_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_reports.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status_at_version: Mapped[str] = mapped_column(String(32))
    findings: Mapped[str | None] = mapped_column(Text, default=None)
    impression: Mapped[str | None] = mapped_column(Text, default=None)
    body: Mapped[dict[str, object] | None] = mapped_column(JSONB, default=None)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(default=None)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    report: Mapped[RadiologyReport] = relationship(back_populates="versions")
