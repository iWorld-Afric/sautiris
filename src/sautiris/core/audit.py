"""HIPAA-grade PHI audit logger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import insert

from sautiris.core.tenancy import get_current_tenant_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sautiris.core.auth.base import AuthUser

logger = structlog.get_logger(__name__)


class AuditLogger:
    """Logs PHI access to the audit_logs table and structured logging."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        user: AuthUser,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        patient_id: uuid.UUID | None = None,
        ip_address: str = "",
        user_agent: str = "",
        correlation_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        """Write an audit log entry."""
        from sautiris.models.audit import AuditLog  # noqa: PLC0415

        now = datetime.now(UTC)
        stmt = insert(AuditLog).values(
            id=uuid.uuid4(),
            tenant_id=get_current_tenant_id(),
            user_id=user.user_id,
            user_name=user.username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            patient_id=patient_id,
            ip_address=ip_address or None,
            user_agent=user_agent or None,
            correlation_id=correlation_id,
            details=details or {},
            created_at=now,
        )
        await self._session.execute(stmt)
        await self._session.flush()

        logger.info(
            "audit",
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            user_id=str(user.user_id),
            correlation_id=correlation_id,
        )
