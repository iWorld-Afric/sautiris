"""Billing API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.models.billing import CodeSystem
from sautiris.services.billing_service import (
    BillingAssignmentNotFoundError,
    BillingCodeInactiveError,
    BillingCodeNotFoundError,
    BillingService,
    DuplicateBillingAssignmentError,
)

router = APIRouter(prefix="/billing", tags=["billing"])


# --- Schemas ---


class BillingAssign(BaseModel):
    order_id: uuid.UUID
    billing_code_id: uuid.UUID
    quantity: int = Field(default=1, ge=1)


class BillingCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code_system: CodeSystem
    code: str
    display: str
    modality: str | None = None
    body_part: str | None = None
    is_active: bool


class OrderBillingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    billing_code_id: uuid.UUID
    quantity: int
    assigned_by: uuid.UUID | None = None
    assigned_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RevenueSummaryItem(BaseModel):
    code_system: CodeSystem
    assignment_count: int
    total_quantity: int


# --- Endpoints ---


@router.post("/assign", status_code=status.HTTP_201_CREATED, response_model=OrderBillingResponse)
async def assign_code(
    body: BillingAssign,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("billing:manage")),
) -> object:
    svc = BillingService(db)
    try:
        return await svc.assign_code(
            order_id=body.order_id,
            billing_code_id=body.billing_code_id,
            quantity=body.quantity,
            assigned_by=user.user_id,
        )
    except BillingCodeNotFoundError:
        raise HTTPException(status_code=404, detail="Billing code not found") from None
    except BillingCodeInactiveError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except DuplicateBillingAssignmentError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.get("/order/{order_id}", response_model=list[OrderBillingResponse])
async def get_order_billing(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("billing:read")),
) -> object:
    svc = BillingService(db)
    return await svc.get_order_billing(order_id)


@router.get("/codes", response_model=list[BillingCodeResponse])
async def search_billing_codes(
    q: str | None = None,
    code_system: CodeSystem | None = None,
    modality: str | None = None,
    body_part: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("billing:read")),
) -> object:
    svc = BillingService(db)
    return await svc.search_codes(
        q=q, code_system=code_system, modality=modality, body_part=body_part
    )


@router.get("/summary")
async def get_revenue_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: Literal["month", "modality", "code_system"] = "code_system",
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("billing:read")),
) -> list[dict[str, object]]:
    svc = BillingService(db)
    return await svc.get_revenue_summary(date_from=date_from, date_to=date_to, group_by=group_by)


@router.delete("/{billing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_billing(
    billing_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("billing:manage")),
) -> None:
    svc = BillingService(db)
    try:
        await svc.remove_assignment(billing_id)
    except BillingAssignmentNotFoundError:
        raise HTTPException(status_code=404, detail="Billing assignment not found") from None
