"""Order management API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, get_event_bus, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.core.events import EventBus
from sautiris.models.order import OrderStatus, Urgency
from sautiris.services.order_service import (
    InvalidTransitionError,
    OrderNotFoundError,
    OrderService,
)

router = APIRouter(prefix="/orders", tags=["orders"])


# --- Schemas ---


class OrderCreate(BaseModel):
    patient_id: uuid.UUID
    modality: str
    urgency: Urgency = Urgency.ROUTINE
    body_part: str | None = None
    laterality: str | None = None
    procedure_code: str | None = None
    procedure_description: str | None = None
    clinical_indication: str | None = None
    patient_history: str | None = None
    requesting_physician_id: uuid.UUID | None = None
    requesting_physician_name: str | None = None
    encounter_id: uuid.UUID | None = None
    special_instructions: str | None = None
    transport_mode: str | None = None
    isolation_precautions: str | None = None
    pregnant: bool | None = None


class OrderUpdate(BaseModel):
    body_part: str | None = None
    laterality: str | None = None
    procedure_code: str | None = None
    procedure_description: str | None = None
    clinical_indication: str | None = None
    patient_history: str | None = None
    special_instructions: str | None = None
    urgency: Urgency | None = None


class OrderSchedule(BaseModel):
    scheduled_at: datetime


class OrderCancel(BaseModel):
    reason: str


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    accession_number: str
    modality: str
    urgency: Urgency
    status: OrderStatus
    body_part: str | None = None
    laterality: str | None = None
    procedure_code: str | None = None
    procedure_description: str | None = None
    clinical_indication: str | None = None
    requesting_physician_name: str | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedOrders(BaseModel):
    items: list[OrderResponse]
    total: int
    page: int
    page_size: int


# --- Endpoints ---


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrderResponse)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:create")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    return await svc.create_order(**body.model_dump(exclude_none=True))


@router.get("", response_model=PaginatedOrders)
async def list_orders(
    modality: str | None = None,
    order_status: OrderStatus | None = Query(None, alias="status"),
    urgency: Urgency | None = None,
    patient_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:read")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    items, total = await svc.list_orders(
        modality=modality,
        status=order_status,
        urgency=urgency,
        patient_id=patient_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_order_stats(
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:read")),
) -> dict[str, int]:
    svc = OrderService(db, event_bus=event_bus)
    return await svc.get_order_stats()


@router.get("/accession/next")
async def get_next_accession(
    modality: str = Query(...),
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:read")),
) -> dict[str, str]:
    """Preview the next accession number without reserving it.

    This is a read-only peek — the counter is NOT incremented.  The returned
    number is an estimate; a concurrent order creation may claim it first.
    Use ``POST /orders`` to actually generate and consume a number.
    """
    svc = OrderService(db, event_bus=event_bus)
    accession = await svc.peek_next_accession(modality)
    return {"accession_number": accession}


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:read")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.get_order(order_id)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: uuid.UUID,
    body: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:update")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.update_order(order_id, **body.model_dump(exclude_none=True))
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: uuid.UUID,
    body: OrderCancel,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:cancel")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.cancel_order(order_id, reason=body.reason)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{order_id}/schedule", response_model=OrderResponse)
async def schedule_order(
    order_id: uuid.UUID,
    body: OrderSchedule,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:update")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.schedule_order(order_id, body.scheduled_at)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{order_id}/start", response_model=OrderResponse)
async def start_exam(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:update")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.start_exam(order_id)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{order_id}/complete", response_model=OrderResponse)
async def complete_exam(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:update")),
) -> object:
    svc = OrderService(db, event_bus=event_bus)
    try:
        return await svc.complete_exam(order_id)
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/{order_id}/history")
async def get_order_history(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("order:read")),
) -> dict[str, object]:
    svc = OrderService(db, event_bus=event_bus)
    try:
        order = await svc.get_order(order_id)
        return {
            "order_id": str(order.id),
            "current_status": order.status,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "scheduled_at": order.scheduled_at.isoformat() if order.scheduled_at else None,
            "started_at": order.started_at.isoformat() if order.started_at else None,
            "completed_at": order.completed_at.isoformat() if order.completed_at else None,
        }
    except OrderNotFoundError:
        raise HTTPException(status_code=404, detail="Order not found") from None
