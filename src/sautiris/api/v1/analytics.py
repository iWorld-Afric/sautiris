"""Analytics API endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.models.order import Urgency
from sautiris.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/tat")
async def get_tat_metrics(
    modality: str | None = None,
    urgency: Urgency | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics:read")),
) -> dict[str, object]:
    svc = AnalyticsService(db)
    return await svc.get_tat_metrics(
        modality=modality, urgency=urgency, date_from=date_from, date_to=date_to
    )


@router.get("/workload")
async def get_workload(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics:read")),
) -> list[dict[str, object]]:
    svc = AnalyticsService(db)
    return await svc.get_workload(date_from=date_from, date_to=date_to)


@router.get("/quality")
async def get_quality_metrics(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics:read")),
) -> dict[str, object]:
    """Quality metrics placeholder — depends on peer review data."""
    return {
        "discrepancy_rate": 0.0,
        "critical_finding_rate": 0.0,
        "sample_count": 0,
    }


@router.get("/volume")
async def get_volume_stats(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics:read")),
) -> list[dict[str, object]]:
    svc = AnalyticsService(db)
    return await svc.get_volume_stats(date_from=date_from, date_to=date_to)


@router.get("/dashboard")
async def get_dashboard(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("analytics:read")),
) -> dict[str, object]:
    svc = AnalyticsService(db)
    return await svc.get_dashboard(date_from=date_from, date_to=date_to)
