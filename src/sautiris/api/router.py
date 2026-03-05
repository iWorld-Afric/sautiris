"""Master router that mounts all v1 sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from sautiris.api.v1 import (
    alerts,
    analytics,
    billing,
    dose,
    health,
    orders,
    peer_review,
    reports,
    schedule,
    worklist,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(orders.router)
api_router.include_router(schedule.router)
api_router.include_router(reports.router)
api_router.include_router(worklist.router)
api_router.include_router(billing.router)
api_router.include_router(analytics.router)
api_router.include_router(alerts.router)
api_router.include_router(peer_review.router)
api_router.include_router(dose.router)
