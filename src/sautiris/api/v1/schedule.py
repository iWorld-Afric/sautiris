"""Schedule management API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Self

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, get_event_bus, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.core.events import EventBus
from sautiris.models.schedule import SlotStatus
from sautiris.services.schedule_service import (
    ScheduleConflictError,
    ScheduleService,
    SlotNotDeletableError,
    SlotNotFoundError,
)

router = APIRouter(prefix="/schedule", tags=["schedule"])


# --- Schemas ---


class SlotCreate(BaseModel):
    order_id: uuid.UUID
    room_id: str
    modality: str
    scheduled_start: datetime
    scheduled_end: datetime
    duration_minutes: int = 30
    technologist_id: uuid.UUID | None = None
    technologist_name: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class SlotUpdate(BaseModel):
    room_id: str | None = None
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    duration_minutes: int | None = None
    technologist_id: uuid.UUID | None = None
    technologist_name: str | None = None
    status: SlotStatus | None = None
    notes: str | None = None


class SlotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    room_id: str
    modality: str
    scheduled_start: datetime
    scheduled_end: datetime
    duration_minutes: int
    technologist_id: uuid.UUID | None = None
    technologist_name: str | None = None
    status: SlotStatus
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedSlots(BaseModel):
    items: list[SlotResponse]
    total: int
    page: int
    page_size: int


# --- Endpoints ---


@router.post("/slots", status_code=status.HTTP_201_CREATED, response_model=SlotResponse)
async def create_slot(
    body: SlotCreate,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:manage")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    try:
        return await svc.create_slot(**body.model_dump(exclude_none=True))
    except ScheduleConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/slots", response_model=PaginatedSlots)
async def list_slots(
    room_id: str | None = None,
    modality: str | None = None,
    technologist_id: uuid.UUID | None = None,
    slot_status: SlotStatus | None = Query(None, alias="status"),
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:read")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    items, total = await svc.list_slots(
        room_id=room_id,
        modality=modality,
        technologist_id=technologist_id,
        status=slot_status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/slots/{slot_id}", response_model=SlotResponse)
async def get_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:read")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    try:
        return await svc.get_slot(slot_id)
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found") from None


@router.patch("/slots/{slot_id}", response_model=SlotResponse)
async def update_slot(
    slot_id: uuid.UUID,
    body: SlotUpdate,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:manage")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    try:
        return await svc.update_slot(slot_id, **body.model_dump(exclude_none=True))
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found") from None
    except ScheduleConflictError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.delete("/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_slot(
    slot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:manage")),
) -> None:
    svc = ScheduleService(db, event_bus=event_bus)
    try:
        await svc.delete_slot(slot_id)
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found") from None
    except SlotNotDeletableError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/availability", response_model=list[SlotResponse])
async def check_availability(
    modality: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:read")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    return await svc.check_availability(modality=modality, date_from=date_from, date_to=date_to)


@router.get("/rooms")
async def list_rooms(
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:read")),
) -> list[str]:
    svc = ScheduleService(db, event_bus=event_bus)
    return await svc.list_rooms()


@router.get("/conflicts", response_model=list[SlotResponse])
async def detect_conflicts(
    room_id: str | None = None,
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: AsyncSession = Depends(get_db),
    event_bus: EventBus = Depends(get_event_bus),
    user: AuthUser = Depends(require_permission("schedule:read")),
) -> object:
    svc = ScheduleService(db, event_bus=event_bus)
    return await svc.detect_conflicts(room_id=room_id, start=start, end=end)
