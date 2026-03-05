"""Worklist repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select

from sautiris.models.worklist import WorklistItem
from sautiris.repositories.base import TenantAwareRepository


class WorklistRepository(TenantAwareRepository[WorklistItem]):
    model = WorklistItem

    async def get_by_accession(self, accession_number: str) -> WorklistItem | None:
        stmt = select(WorklistItem).where(
            WorklistItem.tenant_id == self._tenant_id,
            WorklistItem.accession_number == accession_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_filters(
        self,
        *,
        modality: str | None = None,
        status: str | None = None,
        scheduled_station_ae_title: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[WorklistItem], int]:
        base = select(WorklistItem).where(WorklistItem.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(WorklistItem)
            .where(WorklistItem.tenant_id == self._tenant_id)
        )

        if modality:
            base = base.where(WorklistItem.modality == modality)
            count_base = count_base.where(WorklistItem.modality == modality)
        if status:
            base = base.where(WorklistItem.status == status)
            count_base = count_base.where(WorklistItem.status == status)
        if scheduled_station_ae_title:
            base = base.where(WorklistItem.scheduled_station_ae_title == scheduled_station_ae_title)
            count_base = count_base.where(
                WorklistItem.scheduled_station_ae_title == scheduled_station_ae_title
            )
        if date_from:
            base = base.where(WorklistItem.scheduled_start >= date_from)
            count_base = count_base.where(WorklistItem.scheduled_start >= date_from)
        if date_to:
            base = base.where(WorklistItem.scheduled_start <= date_to)
            count_base = count_base.where(WorklistItem.scheduled_start <= date_to)

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(WorklistItem.scheduled_start).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self) -> dict[str, int]:
        stmt = (
            select(WorklistItem.status, func.count())
            .where(WorklistItem.tenant_id == self._tenant_id)
            .group_by(WorklistItem.status)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
