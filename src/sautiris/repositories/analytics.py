"""Analytics repository for TAT metrics."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select

from sautiris.models.analytics import TATMetric
from sautiris.models.order import RadiologyOrder, Urgency
from sautiris.repositories.base import TenantAwareRepository


class TATMetricRepository(TenantAwareRepository[TATMetric]):
    model = TATMetric

    async def get_tat_metrics(
        self,
        *,
        modality: str | None = None,
        urgency: Urgency | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, object]:
        """Aggregate TAT metrics with avg/p95."""
        stmt = select(
            func.avg(TATMetric.total_tat_mins).label("avg_total"),
            func.avg(TATMetric.order_to_schedule_mins).label("avg_order_to_schedule"),
            func.avg(TATMetric.exam_to_preliminary_mins).label("avg_exam_to_prelim"),
            func.avg(TATMetric.exam_to_final_mins).label("avg_exam_to_final"),
            func.count().label("sample_count"),
        ).where(TATMetric.tenant_id == self._tenant_id)

        if modality:
            stmt = stmt.where(TATMetric.modality == modality)
        if urgency:
            stmt = stmt.where(TATMetric.urgency == urgency)
        if date_from:
            stmt = stmt.where(TATMetric.measured_at >= date_from)
        if date_to:
            stmt = stmt.where(TATMetric.measured_at <= date_to)

        result = await self.session.execute(stmt)
        row = result.one()
        return {
            "avg_total_tat_mins": float(row[0]) if row[0] else 0.0,
            "avg_order_to_schedule_mins": float(row[1]) if row[1] else 0.0,
            "avg_exam_to_preliminary_mins": float(row[2]) if row[2] else 0.0,
            "avg_exam_to_final_mins": float(row[3]) if row[3] else 0.0,
            "sample_count": row[4],
        }

    async def get_workload(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, object]]:
        """Workload grouped by modality."""
        stmt = (
            select(
                TATMetric.modality,
                func.count().label("order_count"),
            )
            .where(TATMetric.tenant_id == self._tenant_id)
            .group_by(TATMetric.modality)
        )
        if date_from:
            stmt = stmt.where(TATMetric.measured_at >= date_from)
        if date_to:
            stmt = stmt.where(TATMetric.measured_at <= date_to)

        result = await self.session.execute(stmt)
        return [{"modality": row[0], "order_count": row[1]} for row in result.all()]

    async def get_volume_stats(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, object]]:
        """Order volume grouped by status."""
        stmt = (
            select(
                RadiologyOrder.status,
                func.count().label("count"),
            )
            .where(RadiologyOrder.tenant_id == self._tenant_id)
            .group_by(RadiologyOrder.status)
        )
        if date_from:
            stmt = stmt.where(RadiologyOrder.created_at >= date_from)
        if date_to:
            stmt = stmt.where(RadiologyOrder.created_at <= date_to)

        result = await self.session.execute(stmt)
        return [{"status": row[0], "count": row[1]} for row in result.all()]
