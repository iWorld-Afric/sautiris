"""Report and report template repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select

from sautiris.models.report import RadiologyReport, ReportTemplate, ReportVersion
from sautiris.repositories.base import TenantAwareRepository


class ReportRepository(TenantAwareRepository[RadiologyReport]):
    model = RadiologyReport

    async def list_with_filters(
        self,
        *,
        order_id: uuid.UUID | None = None,
        status: str | None = None,
        reported_by: uuid.UUID | None = None,
        is_critical: bool | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[RadiologyReport], int]:
        base = select(RadiologyReport).where(RadiologyReport.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(RadiologyReport)
            .where(RadiologyReport.tenant_id == self._tenant_id)
        )

        if order_id:
            base = base.where(RadiologyReport.order_id == order_id)
            count_base = count_base.where(RadiologyReport.order_id == order_id)
        if status:
            base = base.where(RadiologyReport.report_status == status)
            count_base = count_base.where(RadiologyReport.report_status == status)
        if reported_by:
            base = base.where(RadiologyReport.reported_by == reported_by)
            count_base = count_base.where(RadiologyReport.reported_by == reported_by)
        if is_critical is not None:
            base = base.where(RadiologyReport.is_critical == is_critical)
            count_base = count_base.where(RadiologyReport.is_critical == is_critical)
        if date_from:
            base = base.where(RadiologyReport.created_at >= date_from)
            count_base = count_base.where(RadiologyReport.created_at >= date_from)
        if date_to:
            base = base.where(RadiologyReport.created_at <= date_to)
            count_base = count_base.where(RadiologyReport.created_at <= date_to)

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(RadiologyReport.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_versions(self, report_id: uuid.UUID) -> Sequence[ReportVersion]:
        stmt = (
            select(ReportVersion)
            .where(ReportVersion.report_id == report_id)
            .order_by(ReportVersion.version_number)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_next_version_number(self, report_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(ReportVersion.version_number), 0)).where(
            ReportVersion.report_id == report_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() + 1

    async def create_version(self, version: ReportVersion) -> ReportVersion:
        self.session.add(version)
        await self.session.flush()
        await self.session.refresh(version)
        return version


class ReportTemplateRepository(TenantAwareRepository[ReportTemplate]):
    model = ReportTemplate

    async def find_default_template(
        self, modality: str | None = None, body_part: str | None = None
    ) -> ReportTemplate | None:
        stmt = select(ReportTemplate).where(
            ReportTemplate.tenant_id == self._tenant_id,
            ReportTemplate.is_default.is_(True),
            ReportTemplate.is_active.is_(True),
        )
        if modality:
            stmt = stmt.where(ReportTemplate.modality == modality)
        if body_part:
            stmt = stmt.where(ReportTemplate.body_part == body_part)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_templates(
        self,
        *,
        modality: str | None = None,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[ReportTemplate]:
        stmt = select(ReportTemplate).where(
            ReportTemplate.tenant_id == self._tenant_id,
        )
        if modality:
            stmt = stmt.where(ReportTemplate.modality == modality)
        if is_active is not None:
            stmt = stmt.where(ReportTemplate.is_active == is_active)
        stmt = stmt.order_by(ReportTemplate.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()
