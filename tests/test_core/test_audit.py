"""Tests for audit logging."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.audit import AuditLogger
from sautiris.core.auth.base import AuthUser
from sautiris.models.audit import AuditLog

TEST_TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER = AuthUser(
    user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    username="auditor",
    tenant_id=TEST_TENANT,
)


@pytest.mark.asyncio
async def test_audit_log_creates_entry(db_session: AsyncSession) -> None:
    logger = AuditLogger(db_session)
    await logger.log(
        user=TEST_USER,
        action="READ",
        resource_type="ORDER",
        resource_id=uuid.uuid4(),
        patient_id=uuid.uuid4(),
        ip_address="127.0.0.1",
    )
    await db_session.commit()

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert len(logs) == 1
    assert logs[0].action == "READ"
    assert logs[0].resource_type == "ORDER"
    assert logs[0].user_id == TEST_USER.user_id


@pytest.mark.asyncio
async def test_audit_log_stores_correlation_id(db_session: AsyncSession) -> None:
    """AuditLogger.log() must store correlation_id in the audit_logs table."""
    logger = AuditLogger(db_session)
    corr_id = "req-abc-123"
    await logger.log(
        user=TEST_USER,
        action="READ",
        resource_type="ORDER",
        resource_id=uuid.uuid4(),
        ip_address="10.0.0.1",
        correlation_id=corr_id,
    )
    await db_session.commit()

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert len(logs) >= 1
    last = logs[-1]
    assert last.correlation_id == corr_id


@pytest.mark.asyncio
async def test_audit_log_correlation_id_optional(db_session: AsyncSession) -> None:
    """correlation_id defaults to None when not provided."""
    logger = AuditLogger(db_session)
    await logger.log(
        user=TEST_USER,
        action="WRITE",
        resource_type="REPORT",
    )
    await db_session.commit()

    result = await db_session.execute(select(AuditLog))
    logs = result.scalars().all()
    assert any(lg.correlation_id is None for lg in logs)
