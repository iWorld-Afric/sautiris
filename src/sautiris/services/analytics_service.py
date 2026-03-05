"""Analytics service for TAT metrics, workload, and dashboard."""

from __future__ import annotations

from datetime import UTC, date, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.analytics import TATMetric
from sautiris.models.order import RadiologyOrder
from sautiris.repositories.analytics import TATMetricRepository

logger = structlog.get_logger(__name__)


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TATMetricRepository(session)

    @staticmethod
    def _ensure_aware(dt: datetime | None) -> datetime | None:
        """Ensure datetime is timezone-aware (assume UTC if naive)."""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt

    async def capture_tat(
        self,
        *,
        order: RadiologyOrder,
    ) -> TATMetric:
        """Calculate and record TAT segments for a completed/reported order."""
        created = self._ensure_aware(order.created_at)
        scheduled = self._ensure_aware(order.scheduled_at)
        started = self._ensure_aware(order.started_at)
        completed = self._ensure_aware(order.completed_at)

        order_to_schedule = None
        if scheduled and created:
            order_to_schedule = int((scheduled - created).total_seconds() / 60)

        schedule_to_exam = None
        if started and scheduled:
            schedule_to_exam = int((started - scheduled).total_seconds() / 60)

        total = None
        if completed and created:
            total = int((completed - created).total_seconds() / 60)

        metric = TATMetric(
            order_id=order.id,
            order_to_schedule_mins=order_to_schedule,
            schedule_to_exam_mins=schedule_to_exam,
            total_tat_mins=total,
            modality=order.modality,
            urgency=order.urgency,
            is_critical=False,
            measured_at=datetime.now(UTC),
        )
        created_metric = await self.repo.create(metric)
        logger.info("tat_captured", order_id=str(order.id))
        return created_metric

    async def get_tat_metrics(
        self,
        *,
        modality: str | None = None,
        urgency: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, object]:
        return await self.repo.get_tat_metrics(
            modality=modality,
            urgency=urgency,
            date_from=date_from,
            date_to=date_to,
        )

    async def get_workload(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, object]]:
        return await self.repo.get_workload(date_from=date_from, date_to=date_to)

    async def get_volume_stats(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, object]]:
        return await self.repo.get_volume_stats(date_from=date_from, date_to=date_to)

    async def get_dashboard(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, object]:
        tat = await self.get_tat_metrics(date_from=date_from, date_to=date_to)
        workload = await self.get_workload(date_from=date_from, date_to=date_to)
        volume = await self.get_volume_stats(date_from=date_from, date_to=date_to)
        return {
            "tat_metrics": tat,
            "workload": workload,
            "volume_stats": volume,
        }
