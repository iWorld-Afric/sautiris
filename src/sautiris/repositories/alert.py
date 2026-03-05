"""Repository for CriticalAlert entities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select

from sautiris.models.alert import CriticalAlert
from sautiris.repositories.base import TenantAwareRepository


class AlertRepository(TenantAwareRepository[CriticalAlert]):
    model = CriticalAlert

    async def list_filtered(
        self,
        *,
        status: str | None = None,
        urgency: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[CriticalAlert]:
        stmt = select(self.model).where(self.model.tenant_id == self._tenant_id)

        if status == "PENDING":
            stmt = stmt.where(
                self.model.acknowledged_at.is_(None),
                self.model.escalated.is_(False),
            )
        elif status == "ACKNOWLEDGED":
            stmt = stmt.where(self.model.acknowledged_at.isnot(None))
        elif status == "ESCALATED":
            stmt = stmt.where(self.model.escalated.is_(True))

        if urgency:
            stmt = stmt.where(self.model.urgency == urgency)

        stmt = stmt.order_by(self.model.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_unacknowledged_before(self, cutoff: datetime) -> Sequence[CriticalAlert]:
        """Get alerts not acknowledged and not yet escalated before cutoff time."""
        stmt = (
            select(self.model)
            .where(
                self.model.tenant_id == self._tenant_id,
                self.model.acknowledged_at.is_(None),
                self.model.escalated.is_(False),
                self.model.created_at <= cutoff,
            )
            .order_by(self.model.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_status(self) -> dict[str, int]:
        """Count alerts by status category."""
        total_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id
        )
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar() or 0

        ack_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.acknowledged_at.isnot(None),
        )
        ack_result = await self.session.execute(ack_stmt)
        acknowledged = ack_result.scalar() or 0

        esc_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.escalated.is_(True),
        )
        esc_result = await self.session.execute(esc_stmt)
        escalated = esc_result.scalar() or 0

        pending = total - acknowledged - escalated
        return {
            "total": total,
            "pending": max(0, pending),
            "acknowledged": acknowledged,
            "escalated": escalated,
        }

    async def avg_acknowledgment_time_minutes(self) -> float:
        """Average time from creation to acknowledgment in minutes."""
        stmt = select(
            func.avg(
                func.extract("epoch", self.model.acknowledged_at)
                - func.extract("epoch", self.model.created_at)
            )
        ).where(
            self.model.tenant_id == self._tenant_id,
            self.model.acknowledged_at.isnot(None),
        )
        result = await self.session.execute(stmt)
        avg_seconds = result.scalar()
        if avg_seconds is None:
            return 0.0
        return float(avg_seconds) / 60.0

    async def acknowledge(self, alert: CriticalAlert, *, user_id: uuid.UUID) -> CriticalAlert:
        now = datetime.now(UTC)
        alert.acknowledged_at = now
        alert.acknowledged_by = user_id
        await self.session.flush()
        await self.session.refresh(alert)
        return alert

    async def escalate(self, alert: CriticalAlert) -> CriticalAlert:
        alert.escalated = True
        alert.escalated_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(alert)
        return alert
