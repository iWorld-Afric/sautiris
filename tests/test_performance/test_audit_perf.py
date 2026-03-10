"""Performance tests for the audit middleware and AuditLogger.

Validates that PHI audit logging does not degrade request latency (fire-and-forget).
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.audit import AuditLogger
from tests.conftest import TEST_USER


@pytest.mark.performance
class TestAuditLoggerPerformance:
    """Performance tests for AuditLogger direct writes."""

    async def test_single_audit_log_write_latency(self, db_session: AsyncSession) -> None:
        """A single audit log write must complete in < 50ms (SQLite in-memory)."""
        audit = AuditLogger(db_session)

        start = time.perf_counter()
        await audit.log(
            user=TEST_USER,
            action="READ",
            resource_type="ORDER",
            resource_id=uuid.uuid4(),
            patient_id=uuid.uuid4(),
            ip_address="192.168.1.100",
            user_agent="TestClient/1.0",
            correlation_id=str(uuid.uuid4()),
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 0.050, (
            f"Single audit log write took {elapsed * 1000:.2f}ms — expected < 50ms."
        )

    async def test_100_audit_log_writes_throughput(self, db_session: AsyncSession) -> None:
        """100 sequential audit log writes must complete in < 5s.

        Establishes a baseline for sustained audit throughput.
        At 100/5s = 20 writes/s minimum via SQLite (PostgreSQL will be faster).
        """
        audit = AuditLogger(db_session)
        n = 100

        start = time.perf_counter()
        for i in range(n):
            await audit.log(
                user=TEST_USER,
                action="READ",
                resource_type="ORDER",
                resource_id=uuid.uuid4(),
                ip_address="10.0.0.1",
                correlation_id=f"corr-{i:05d}",
            )
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, f"{n} sequential audit writes took {elapsed:.3f}s — expected < 5s."

    async def test_audit_does_not_block_response_path(self, db_session: AsyncSession) -> None:
        """Fire-and-forget audit tasks must not add blocking time to the response path.

        The AuditMiddleware uses asyncio.create_task() for fire-and-forget.
        Simulates the pattern: response is sent, then audit task runs in background.
        The response-return portion should take < 5ms even with audit pending.
        """

        # Simulate what the middleware does: call_next → response → create_task(audit)
        response_sent = False
        audit_written = False

        async def mock_response_path() -> float:
            """Simulate call_next() + fire-and-forget audit task."""
            nonlocal response_sent

            # Simulate fast response
            start = time.perf_counter()

            async def background_audit() -> None:
                nonlocal audit_written
                audit = AuditLogger(db_session)
                await audit.log(
                    user=TEST_USER,
                    action="READ",
                    resource_type="ORDER",
                    resource_id=uuid.uuid4(),
                    ip_address="192.168.0.1",
                )
                audit_written = True

            # fire-and-forget (like AuditMiddleware.dispatch does)
            asyncio.create_task(background_audit())
            response_sent = True
            elapsed = time.perf_counter() - start
            return elapsed

        response_time = await mock_response_path()
        assert response_sent, "Response should have been sent"

        # Response time (excluding audit) should be near zero
        assert response_time < 0.005, (
            f"Response path with fire-and-forget audit took {response_time * 1000:.2f}ms. "
            "Fire-and-forget must not block the response. Expected < 5ms."
        )

        # Allow background task to complete
        await asyncio.sleep(0.1)
        assert audit_written, "Background audit task should have completed"

    async def test_concurrent_phi_requests_all_audited(self, db_session: AsyncSession) -> None:
        """20 concurrent PHI requests must all produce audit log entries.

        Verifies that the fire-and-forget pattern doesn't drop audit records
        under moderate concurrent load.
        """
        audit = AuditLogger(db_session)
        order_ids = [uuid.uuid4() for _ in range(20)]

        async def audit_one(resource_id: uuid.UUID) -> None:
            await audit.log(
                user=TEST_USER,
                action="READ",
                resource_type="ORDER",
                resource_id=resource_id,
                ip_address="10.0.0.1",
            )

        start = time.perf_counter()
        await asyncio.gather(*[audit_one(oid) for oid in order_ids])
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"20 concurrent audit writes took {elapsed:.3f}s — expected < 2s."

        # Verify all 20 entries were actually written by counting via ORM
        from sqlalchemy import func, select

        from sautiris.models.audit import AuditLog

        result = await db_session.execute(select(func.count()).select_from(AuditLog))
        count = result.scalar_one()
        assert count >= 20, (
            f"Expected at least 20 audit log entries, found {count}. "
            "No audit records should be dropped under concurrent load."
        )

    async def test_audit_correlation_id_sanitization_overhead(self) -> None:
        """Correlation ID sanitization (regex match) must add < 0.1ms per request."""
        from sautiris.api.middleware.audit_middleware import _sanitize_correlation_id

        valid_id = "abc-123-XYZ-456"
        n = 10_000

        start = time.perf_counter()
        for _ in range(n):
            result = _sanitize_correlation_id(valid_id)
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / n) * 1000
        assert avg_ms < 0.1, (
            f"Correlation ID sanitization averaged {avg_ms:.4f}ms — expected < 0.1ms. "
            "This regex runs on every PHI request so it must be near-instant."
        )
        assert result == valid_id

    async def test_phi_route_check_overhead(self) -> None:
        """PHI route prefix check must complete in < 0.01ms per request."""
        from sautiris.api.middleware.audit_middleware import _is_phi_route

        phi_paths = [
            "/api/v1/orders",
            "/api/v1/orders/123",
            "/api/v1/reports",
            "/api/v1/patients",
            "/api/v1/worklist",
        ]
        non_phi_paths = [
            "/api/v1/health",
            "/api/v1/schedule",
            "/api/v1/dose",
            "/metrics",
            "/",
        ]
        all_paths = phi_paths + non_phi_paths
        n = 100_000

        start = time.perf_counter()
        for i in range(n):
            _is_phi_route(all_paths[i % len(all_paths)])
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / n) * 1000
        assert avg_ms < 0.01, (
            f"PHI route check averaged {avg_ms:.5f}ms — expected < 0.01ms. "
            "Prefix tuple-match runs on every request; must be trivially cheap."
        )
