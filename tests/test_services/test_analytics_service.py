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
