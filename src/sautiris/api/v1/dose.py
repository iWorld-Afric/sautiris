"""Radiation dose tracking API endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.services.dose_service import DoseService

router = APIRouter(prefix="/dose", tags=["dose"])


# --- Pydantic schemas ---


class DoseRecordRequest(BaseModel):
    order_id: uuid.UUID
    modality: str
    source: str = "MANUAL"
    study_instance_uid: str | None = None
    ctdi_vol: float | None = None
    dlp: float | None = None
    dap: float | None = None
    effective_dose: float | None = None
    entrance_dose: float | None = None
    num_exposures: int | None = None
    kvp: float | None = None
    tube_current_ma: float | None = None
    exposure_time_ms: float | None = None
    protocol_name: str | None = None
    body_part: str | None = None


class DoseRecordResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    study_instance_uid: str | None
    modality: str
    ctdi_vol: float | None
    dlp: float | None
    dap: float | None
    effective_dose: float | None
    entrance_dose: float | None
    num_exposures: int | None
    kvp: float | None
    tube_current_ma: float | None
    exposure_time_ms: float | None
    protocol_name: str | None
    body_part: str | None
    exceeds_drl: bool | None
    source: str
    recorded_by: uuid.UUID | None
    recorded_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class DoseStatsResponse(BaseModel):
    modality: str
    count: int
    avg_ctdi_vol: float | None
    avg_dlp: float | None
    avg_dap: float | None
    avg_effective_dose: float | None


class DRLComplianceResponse(BaseModel):
    total_records: int
    exceeding_drl: int
    compliance_rate: float
    exceedances_by_modality: dict[str, int]


# --- Endpoints ---


@router.post("", response_model=DoseRecordResponse, status_code=status.HTTP_201_CREATED)
async def record_dose(
    body: DoseRecordRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("dose:record")),
) -> Any:
    """Record a radiation dose."""
    svc = DoseService(db)
    return await svc.record_dose(
        order_id=body.order_id,
        modality=body.modality,
        source=body.source,
        recorded_by=user.user_id,
        study_instance_uid=body.study_instance_uid,
        ctdi_vol=body.ctdi_vol,
        dlp=body.dlp,
        dap=body.dap,
        effective_dose=body.effective_dose,
        entrance_dose=body.entrance_dose,
        num_exposures=body.num_exposures,
        kvp=body.kvp,
        tube_current_ma=body.tube_current_ma,
        exposure_time_ms=body.exposure_time_ms,
        protocol_name=body.protocol_name,
        body_part=body.body_part,
    )


@router.get("/order/{order_id}", response_model=list[DoseRecordResponse])
async def get_order_dose(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("dose:read")),
) -> Any:
    """Get dose records for a specific order."""
    svc = DoseService(db)
    return await svc.get_order_dose(order_id)


@router.get("/patient/{patient_id}", response_model=list[DoseRecordResponse])
async def get_patient_dose(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("dose:read")),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """Get cumulative dose history for a patient."""
    svc = DoseService(db)
    return await svc.get_patient_dose_history(patient_id, offset=offset, limit=limit)


@router.get("/stats", response_model=list[DoseStatsResponse])
async def dose_stats(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("dose:read")),
) -> Any:
    """Get facility dose statistics by modality."""
    svc = DoseService(db)
    return await svc.get_stats()


@router.get("/drl-compliance", response_model=DRLComplianceResponse)
async def drl_compliance(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("dose:read")),
) -> Any:
    """Get DRL compliance report."""
    svc = DoseService(db)
    return await svc.get_drl_compliance()
