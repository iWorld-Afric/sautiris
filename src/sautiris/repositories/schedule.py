"""Schedule repository with conflict detection."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import and_, func, or_, select

from sautiris.models.schedule import ScheduleSlot, SlotStatus
from sautiris.repositories.base import TenantAwareRepository


class ScheduleRepository(TenantAwareRepository[ScheduleSlot]):
    model = ScheduleSlot

    async def find_conflicts(
        self,
        *,
        room_id: str | None = None,
        technologist_id: uuid.UUID | None = None,
        start: datetime,
        end: datetime,
        exclude_id: uuid.UUID | None = None,
    ) -> Sequence[ScheduleSlot]:
        """Find overlapping slots for the given room or technologist."""
        conditions = [
            ScheduleSlot.tenant_id == self._tenant_id,
            ScheduleSlot.scheduled_start < end,
            ScheduleSlot.scheduled_end > start,
            ScheduleSlot.status.notin_([SlotStatus.CANCELLED, SlotStatus.NO_SHOW]),
        ]

        resource_conditions = []
        if room_id:
            resource_conditions.append(ScheduleSlot.room_id == room_id)
        if technologist_id:
            resource_conditions.append(ScheduleSlot.technologist_id == technologist_id)

        if not resource_conditions:
            return []

        conditions.append(or_(*resource_conditions))

        if exclude_id:
            conditions.append(ScheduleSlot.id != exclude_id)

        stmt = select(ScheduleSlot).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_with_filters(
        self,
        *,
        room_id: str | None = None,
        modality: str | None = None,
        technologist_id: uuid.UUID | None = None,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[ScheduleSlot], int]:
        base = select(ScheduleSlot).where(ScheduleSlot.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(ScheduleSlot)
            .where(ScheduleSlot.tenant_id == self._tenant_id)
        )

        if room_id:
            base = base.where(ScheduleSlot.room_id == room_id)
            count_base = count_base.where(ScheduleSlot.room_id == room_id)
        if modality:
            base = base.where(ScheduleSlot.modality == modality)
            count_base = count_base.where(ScheduleSlot.modality == modality)
        if technologist_id:
            base = base.where(ScheduleSlot.technologist_id == technologist_id)
            count_base = count_base.where(ScheduleSlot.technologist_id == technologist_id)
        if status:
            base = base.where(ScheduleSlot.status == status)
            count_base = count_base.where(ScheduleSlot.status == status)
        if date_from:
            base = base.where(ScheduleSlot.scheduled_start >= date_from)
            count_base = count_base.where(ScheduleSlot.scheduled_start >= date_from)
        if date_to:
            base = base.where(ScheduleSlot.scheduled_end <= date_to)
            count_base = count_base.where(ScheduleSlot.scheduled_end <= date_to)

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(ScheduleSlot.scheduled_start).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_availability(
        self,
        *,
        modality: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Sequence[ScheduleSlot]:
        """Return only AVAILABLE slots."""
        stmt = select(ScheduleSlot).where(
            ScheduleSlot.tenant_id == self._tenant_id,
            ScheduleSlot.status == SlotStatus.AVAILABLE,
        )
        if modality:
            stmt = stmt.where(ScheduleSlot.modality == modality)
        if date_from:
            stmt = stmt.where(ScheduleSlot.scheduled_start >= date_from)
        if date_to:
            stmt = stmt.where(ScheduleSlot.scheduled_end <= date_to)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_rooms(self) -> Sequence[str]:
        """Return distinct room_ids."""
        stmt = (
            select(ScheduleSlot.room_id).where(ScheduleSlot.tenant_id == self._tenant_id).distinct()
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
