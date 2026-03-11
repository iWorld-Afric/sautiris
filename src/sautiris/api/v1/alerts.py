"""Critical alert API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, get_event_bus, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.core.events import EventBus
from sautiris.models.alert import AlertType, AlertUrgency, NotificationMethod
from sautiris.services.alert_service import AlertService

router = APIRouter(prefix="/alerts", tags=["alerts"])


# --- Pydantic schemas ---


class AlertCreateRequest(BaseModel):
    order_id: uuid.UUID
    report_id: uuid.UUID | None = None
    alert_type: AlertType = AlertType.CRITICAL_FINDING
    finding_description: str | None = None
    urgency: AlertUrgency = AlertUrgency.URGENT
    notified_physician_id: uuid.UUID | None = None
    notified_physician_name: str | None = None
    notification_method: NotificationMethod = NotificationMethod.IN_APP


class AlertResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    report_id: uuid.UUID | None
    alert_type: AlertType
    finding_description: str | None
    urgency: AlertUrgency
    notified_physician_id: uuid.UUID | None
    notified_physician_name: str | None
    notification_method: NotificationMethod | None
    notified_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: uuid.UUID | None
    escalated: bool
    escalated_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertStatsResponse(BaseModel):
    total: int
    pending: int
    acknowledged: int
    escalated: int
    avg_acknowledgment_time_minutes: float
    escalation_rate: float


# --- Endpoints ---


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
async def create_alert(
    body: AlertCreateRequest,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("alert:create")),
) -> object:
    """Create a critical alert and dispatch notification."""
    svc = AlertService(db, event_bus=event_bus)
    alert = await svc.create_alert(
        order_id=body.order_id,
        report_id=body.report_id,
        alert_type=body.alert_type,
        finding_description=body.finding_description,
        urgency=body.urgency,
        notified_physician_id=body.notified_physician_id,
        notified_physician_name=body.notified_physician_name,
        notification_method=body.notification_method,
    )
    return alert


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("alert:read")),
    alert_status: Literal["PENDING", "ACKNOWLEDGED", "ESCALATED"] | None = Query(
        default=None, alias="status"
    ),
    urgency: AlertUrgency | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> object:
    """List alerts with optional filtering."""
    svc = AlertService(db)
    return await svc.list_alerts(status=alert_status, urgency=urgency, offset=offset, limit=limit)


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("alert:acknowledge")),
) -> object:
    """Acknowledge a critical alert."""
    svc = AlertService(db)
    try:
        return await svc.acknowledge_alert(alert_id, user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{alert_id}/escalate", response_model=AlertResponse)
async def escalate_alert(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("alert:acknowledge")),
) -> object:
    """Escalate an unacknowledged alert."""
    svc = AlertService(db)
    try:
        return await svc.escalate_alert(alert_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/stats", response_model=AlertStatsResponse)
async def alert_stats(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("alert:read")),
) -> object:
    """Get alert statistics."""
    svc = AlertService(db)
    return await svc.get_stats()
