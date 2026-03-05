"""Structured reporting API endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.services.report_service import (
    InvalidReportTransitionError,
    ReportNotFoundError,
    ReportService,
)

router = APIRouter(prefix="/reports", tags=["reports"])


# --- Schemas ---


class ReportCreate(BaseModel):
    order_id: uuid.UUID
    accession_number: str
    modality: str | None = None
    body_part: str | None = None
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None
    technique: str | None = None
    comparison: str | None = None
    clinical_information: str | None = None
    body: dict[str, object] | None = None
    is_critical: bool = False


class ReportUpdate(BaseModel):
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None
    technique: str | None = None
    comparison: str | None = None
    clinical_information: str | None = None
    body: dict[str, object] | None = None
    is_critical: bool | None = None


class ReportFinalize(BaseModel):
    pass


class ReportAmend(BaseModel):
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None


class AddendumCreate(BaseModel):
    order_id: uuid.UUID
    accession_number: str
    findings: str | None = None
    impression: str | None = None


class TemplateCreate(BaseModel):
    name: str
    modality: str | None = None
    body_part: str | None = None
    sections: dict[str, object] | None = None
    is_default: bool = False


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    accession_number: str
    report_status: str
    findings: str | None = None
    impression: str | None = None
    recommendation: str | None = None
    technique: str | None = None
    is_critical: bool
    is_addendum: bool
    parent_report_id: uuid.UUID | None = None
    reported_by: uuid.UUID | None = None
    reported_by_name: str | None = None
    approved_by: uuid.UUID | None = None
    approved_by_name: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    report_id: uuid.UUID
    version_number: int
    status_at_version: str
    findings: str | None = None
    impression: str | None = None
    changed_by: uuid.UUID | None = None
    changed_at: datetime


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    modality: str | None = None
    body_part: str | None = None
    sections: dict[str, object] | None = None
    is_default: bool
    is_active: bool


class PaginatedReports(BaseModel):
    items: list[ReportResponse]
    total: int
    page: int
    page_size: int


# --- Endpoints ---


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ReportResponse)
async def create_report(
    body: ReportCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:create")),
) -> object:
    svc = ReportService(db)
    return await svc.create_report(
        **body.model_dump(exclude_none=True),
        reported_by=user.user_id,
        reported_by_name=user.name or user.username,
    )


@router.get("", response_model=PaginatedReports)
async def list_reports(
    order_id: uuid.UUID | None = None,
    report_status: str | None = Query(None, alias="status"),
    reported_by: uuid.UUID | None = None,
    is_critical: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:read")),
) -> object:
    svc = ReportService(db)
    items, total = await svc.list_reports(
        order_id=order_id,
        status=report_status,
        reported_by=reported_by,
        is_critical=is_critical,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    modality: str | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:read")),
) -> object:
    svc = ReportService(db)
    return await svc.list_templates(modality=modality, is_active=is_active)


@router.post(
    "/templates",
    status_code=status.HTTP_201_CREATED,
    response_model=TemplateResponse,
)
async def create_template(
    body: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:create")),
) -> object:
    svc = ReportService(db)
    return await svc.create_template(
        **body.model_dump(exclude_none=True),
        created_by=user.user_id,
    )


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:read")),
) -> object:
    svc = ReportService(db)
    try:
        return await svc.get_report(report_id)
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found") from None


@router.patch("/{report_id}", response_model=ReportResponse)
async def update_report(
    report_id: uuid.UUID,
    body: ReportUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:update")),
) -> object:
    svc = ReportService(db)
    try:
        return await svc.update_report(
            report_id,
            changed_by=user.user_id,
            **body.model_dump(exclude_none=True),
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found") from None
    except InvalidReportTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{report_id}/finalize", response_model=ReportResponse)
async def finalize_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:finalize")),
) -> object:
    svc = ReportService(db)
    try:
        return await svc.finalize_report(
            report_id,
            approved_by=user.user_id,
            approved_by_name=user.name or user.username,
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found") from None
    except InvalidReportTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{report_id}/amend", response_model=ReportResponse)
async def amend_report(
    report_id: uuid.UUID,
    body: ReportAmend,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:amend")),
) -> object:
    svc = ReportService(db)
    try:
        return await svc.amend_report(
            report_id,
            changed_by=user.user_id,
            **body.model_dump(exclude_none=True),
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Report not found") from None
    except InvalidReportTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/{report_id}/addendum", response_model=ReportResponse)
async def create_addendum(
    report_id: uuid.UUID,
    body: AddendumCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:create")),
) -> object:
    svc = ReportService(db)
    try:
        return await svc.create_addendum(
            report_id,
            order_id=body.order_id,
            accession_number=body.accession_number,
            reported_by=user.user_id,
            reported_by_name=user.name or user.username,
            findings=body.findings,
            impression=body.impression,
        )
    except ReportNotFoundError:
        raise HTTPException(status_code=404, detail="Parent report not found") from None


@router.get("/{report_id}/versions", response_model=list[VersionResponse])
async def get_report_versions(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("report:read")),
) -> object:
    svc = ReportService(db)
    return await svc.get_versions(report_id)
