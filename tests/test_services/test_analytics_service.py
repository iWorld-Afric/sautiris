"""Tests for AnalyticsService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.order import RadiologyOrder
from sautiris.services.analytics_service import AnalyticsService
from tests.conftest import TEST_TENANT_ID


@pytest.fixture
def analytics_service(db_session: AsyncSession) -> AnalyticsService:
    return AnalyticsService(db_session)


async def _make_order_with_times(
    session: AsyncSession,
    *,
    modality: str = "CT",
) -> RadiologyOrder:
    now = datetime.now(UTC)
    order = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality=modality,
        status="COMPLETED",
        scheduled_at=now - timedelta(hours=2),
        started_at=now - timedelta(hours=1),
        completed_at=now,
    )
    session.add(order)
    await session.flush()
    return order


async def test_capture_tat(analytics_service: AnalyticsService, db_session: AsyncSession) -> None:
    order = await _make_order_with_times(db_session)
    metric = await analytics_service.capture_tat(order=order)
    assert metric.id is not None
    assert metric.modality == "CT"
    assert metric.order_id == order.id


async def test_get_tat_metrics_empty(analytics_service: AnalyticsService) -> None:
    result = await analytics_service.get_tat_metrics()
    assert result["sample_count"] == 0
    assert result["avg_total_tat_mins"] == 0.0


async def test_get_tat_metrics_with_data(
    analytics_service: AnalyticsService, db_session: AsyncSession
) -> None:
    order = await _make_order_with_times(db_session)
    await analytics_service.capture_tat(order=order)
    result = await analytics_service.get_tat_metrics()
    assert result["sample_count"] == 1


async def test_get_workload(analytics_service: AnalyticsService, db_session: AsyncSession) -> None:
    for _ in range(3):
        order = await _make_order_with_times(db_session)
        await analytics_service.capture_tat(order=order)
    workload = await analytics_service.get_workload()
    assert len(workload) >= 1
    ct_entry = [w for w in workload if w["modality"] == "CT"]
    assert ct_entry[0]["order_count"] == 3


async def test_get_volume_stats(
    analytics_service: AnalyticsService, db_session: AsyncSession
) -> None:
    await _make_order_with_times(db_session, modality="CT")
    await _make_order_with_times(db_session, modality="MR")
    volume = await analytics_service.get_volume_stats()
    assert len(volume) >= 1


async def test_get_dashboard(analytics_service: AnalyticsService, db_session: AsyncSession) -> None:
    order = await _make_order_with_times(db_session)
    await analytics_service.capture_tat(order=order)
    dashboard = await analytics_service.get_dashboard()
    assert "tat_metrics" in dashboard
    assert "workload" in dashboard
    assert "volume_stats" in dashboard


# ---------------------------------------------------------------------------
# GAP-H2: AnalyticsService._ensure_aware() — naive datetime conversion
# ---------------------------------------------------------------------------


class TestEnsureAware:
    def test_naive_datetime_gets_utc_tzinfo(self) -> None:
        """GAP-H2a: naive datetime is given UTC tzinfo."""
        naive = datetime(2024, 1, 15, 10, 30, 0)  # no tzinfo
        result = AnalyticsService._ensure_aware(naive)
        assert result is not None
        assert result.tzinfo is UTC
        assert result.year == 2024
        assert result.hour == 10

    def test_aware_datetime_returned_unchanged(self) -> None:
        """GAP-H2b: already-aware datetime is returned as-is (same object)."""
        aware = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = AnalyticsService._ensure_aware(aware)
        assert result is aware

    def test_none_returns_none(self) -> None:
        """GAP-H2c: None input returns None."""
        result = AnalyticsService._ensure_aware(None)
        assert result is None


# ---------------------------------------------------------------------------
# GAP-H3: capture_tat() — partial/missing timestamps
# ---------------------------------------------------------------------------


async def test_capture_tat_missing_scheduled_at_returns_none_segments(
    analytics_service: AnalyticsService, db_session: AsyncSession
) -> None:
    """GAP-H3: order with scheduled_at=None → order_to_schedule_mins and
    schedule_to_exam_mins are both None."""
    from datetime import UTC, datetime

    order = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="CT",
        status="COMPLETED",
        scheduled_at=None,
        started_at=None,
        completed_at=datetime.now(UTC),
    )
    db_session.add(order)
    await db_session.flush()

    metric = await analytics_service.capture_tat(order=order)

    assert metric.order_to_schedule_mins is None
    assert metric.schedule_to_exam_mins is None


# ---------------------------------------------------------------------------
# GAP-M6: get_tat_metrics() — filter by modality / urgency
# ---------------------------------------------------------------------------


async def test_get_tat_metrics_filter_by_modality(
    analytics_service: AnalyticsService, db_session: AsyncSession
) -> None:
    """GAP-M6a: modality filter returns only metrics for that modality."""
    ct_order = await _make_order_with_times(db_session, modality="CT")
    mr_order = await _make_order_with_times(db_session, modality="MR")
    await analytics_service.capture_tat(order=ct_order)
    await analytics_service.capture_tat(order=mr_order)

    ct_result = await analytics_service.get_tat_metrics(modality="CT")
    assert ct_result["sample_count"] == 1

    mr_result = await analytics_service.get_tat_metrics(modality="MR")
    assert mr_result["sample_count"] == 1


async def test_get_tat_metrics_filter_by_urgency(
    analytics_service: AnalyticsService, db_session: AsyncSession
) -> None:
    """GAP-M6b: urgency filter returns only metrics for that urgency."""
    from datetime import UTC, datetime, timedelta

    from sautiris.models.order import Urgency

    now = datetime.now(UTC)
    order_stat = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="CT",
        status="COMPLETED",
        urgency=Urgency.STAT,
        scheduled_at=now - timedelta(hours=2),
        completed_at=now,
    )
    order_routine = RadiologyOrder(
        id=uuid.uuid4(),
        tenant_id=TEST_TENANT_ID,
        patient_id=uuid.uuid4(),
        accession_number=f"ACC-{uuid.uuid4().hex[:8]}",
        modality="CT",
        status="COMPLETED",
        urgency=Urgency.ROUTINE,
        scheduled_at=now - timedelta(hours=2),
        completed_at=now,
    )
    db_session.add_all([order_stat, order_routine])
    await db_session.flush()

    await analytics_service.capture_tat(order=order_stat)
    await analytics_service.capture_tat(order=order_routine)

    stat_result = await analytics_service.get_tat_metrics(urgency="STAT")
    assert stat_result["sample_count"] == 1

    routine_result = await analytics_service.get_tat_metrics(urgency="ROUTINE")
    assert routine_result["sample_count"] == 1
