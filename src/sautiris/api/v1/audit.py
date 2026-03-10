"""Audit log query API — admin-only endpoint.

Issue #22: Provides read-only access to the audit_logs table for compliance
and security review.  Only accessible to users with the ``admin:*`` permission.
Records are append-only; no modification endpoints are provided.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_current_user, get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.models.audit import AuditLog

router = APIRouter(prefix="/audit-logs", tags=["audit"])


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    patient_id: uuid.UUID | None
    ip_address: str | None
    user_agent: str | None
    correlation_id: str | None
    details: dict[str, object] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[AuditLogResponse],
    summary="List audit log entries (admin only)",
)
async def list_audit_logs(
    user_id: uuid.UUID | None = Query(default=None, description="Filter by user UUID"),
    resource_type: str | None = Query(
        default=None, max_length=64, description="Filter by resource type"
    ),
    action: str | None = Query(
        default=None, max_length=64, description="Filter by action (READ, WRITE, etc.)"
    ),
    correlation_id: str | None = Query(
        default=None, max_length=128, description="Filter by correlation ID"
    ),
    from_dt: datetime | None = Query(default=None, description="Start of date range (UTC)"),
    to_dt: datetime | None = Query(default=None, description="End of date range (UTC)"),
    limit: int = Query(default=100, le=1000, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    _admin: object = Depends(require_permission("admin:*")),
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    # #6: Enforce tenant isolation — admins can only query their own tenant's logs
    stmt = select(AuditLog).where(AuditLog.tenant_id == current_user.tenant_id)
    stmt = stmt.order_by(AuditLog.created_at.desc())

    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type.upper())
    if action is not None:
        stmt = stmt.where(AuditLog.action == action.upper())
    if correlation_id is not None:
        stmt = stmt.where(AuditLog.correlation_id == correlation_id)
    if from_dt is not None:
        stmt = stmt.where(AuditLog.created_at >= from_dt)
    if to_dt is not None:
        stmt = stmt.where(AuditLog.created_at <= to_dt)

    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())
