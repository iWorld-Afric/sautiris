"""Order repository with tenant-scoped queries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select

from sautiris.models.order import OrderStatus, RadiologyOrder, Urgency
from sautiris.repositories.base import TenantAwareRepository


class OrderRepository(TenantAwareRepository[RadiologyOrder]):
    model = RadiologyOrder

    async def list_with_filters(
        self,
        *,
        modality: str | None = None,
        status: OrderStatus | None = None,
        urgency: Urgency | None = None,
        patient_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[RadiologyOrder], int]:
        """List orders with filters; returns (items, total_count)."""
        base = select(RadiologyOrder).where(RadiologyOrder.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(RadiologyOrder)
            .where(RadiologyOrder.tenant_id == self._tenant_id)
        )

        if modality:
            base = base.where(RadiologyOrder.modality == modality)
            count_base = count_base.where(RadiologyOrder.modality == modality)
        if status:
            base = base.where(RadiologyOrder.status == status)
            count_base = count_base.where(RadiologyOrder.status == status)
        if urgency:
            base = base.where(RadiologyOrder.urgency == urgency)
            count_base = count_base.where(RadiologyOrder.urgency == urgency)
        if patient_id:
            base = base.where(RadiologyOrder.patient_id == patient_id)
            count_base = count_base.where(RadiologyOrder.patient_id == patient_id)
        if date_from:
            base = base.where(RadiologyOrder.created_at >= date_from)
            count_base = count_base.where(RadiologyOrder.created_at >= date_from)
        if date_to:
            base = base.where(RadiologyOrder.created_at <= date_to)
            count_base = count_base.where(RadiologyOrder.created_at <= date_to)

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(RadiologyOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = result.scalars().all()

        return items, total

    async def get_order_stats(
        self,
    ) -> dict[str, int]:
        """Get order counts grouped by status."""
        stmt = (
            select(RadiologyOrder.status, func.count())
            .where(RadiologyOrder.tenant_id == self._tenant_id)
            .group_by(RadiologyOrder.status)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def get_by_accession(self, accession_number: str) -> RadiologyOrder | None:
        stmt = select(RadiologyOrder).where(
            RadiologyOrder.tenant_id == self._tenant_id,
            RadiologyOrder.accession_number == accession_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
