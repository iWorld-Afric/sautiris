"""Worklist API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.services.worklist_service import (
    InvalidWorklistTransitionError,
    WorklistItemNotFoundError,
    WorklistService,
)

router = APIRouter(prefix="/worklist", tags=["worklist"])


# --- Schemas ---


class WorklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    accession_number: str
    patient_id: str
    patient_name: str
    modality: str
    status: str
    mpps_status: str | None = None
    mpps_uid: str | None = None
    scheduled_start: datetime | None = None
    scheduled_station_ae_title: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedWorklist(BaseModel):
    items: list[WorklistItemResponse]
    total: int
    page: int
    page_size: int


class StatusUpdate(BaseModel):
    status: str


class MPPSUpdate(BaseModel):
    mpps_status: str
    mpps_uid: str | None = None


# --- Endpoints ---


@router.get("", response_model=PaginatedWorklist)
async def list_worklist(
    modality: str | None = None,
    wl_status: str | None = Query(None, alias="status"),
    scheduled_station_ae_title: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("worklist:read")),
) -> object:
    svc = WorklistService(db)
    items, total = await svc.list_items(
        modality=modality,
        status=wl_status,
        scheduled_station_ae_title=scheduled_station_ae_title,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def worklist_stats(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("worklist:read")),
) -> dict[str, int]:
    svc = WorklistService(db)
    return await svc.get_stats()


@router.get("/{item_id}", response_model=WorklistItemResponse)
async def get_worklist_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("worklist:read")),
) -> object:
    svc = WorklistService(db)
    try:
        return await svc.get_item(item_id)
    except WorklistItemNotFoundError:
        raise HTTPException(status_code=404, detail="Worklist item not found") from None


@router.post("/{item_id}/status", response_model=WorklistItemResponse)
async def update_step_status(
    item_id: uuid.UUID,
    body: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("worklist:update")),
) -> object:
    from sautiris.models.worklist import WorklistStatus

    svc = WorklistService(db)
    try:
        return await svc.update_procedure_step_status(item_id, WorklistStatus(body.status))
    except WorklistItemNotFoundError:
        raise HTTPException(status_code=404, detail="Worklist item not found") from None
    except InvalidWorklistTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}") from None


@router.post("/{item_id}/mpps", response_model=WorklistItemResponse)
async def receive_mpps(
    item_id: uuid.UUID,
    body: MPPSUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("worklist:update")),
) -> object:
    svc = WorklistService(db)
    try:
        return await svc.receive_mpps(
            item_id,
            mpps_status=body.mpps_status,
            mpps_uid=body.mpps_uid,
        )
    except WorklistItemNotFoundError:
        raise HTTPException(status_code=404, detail="Worklist item not found") from None
