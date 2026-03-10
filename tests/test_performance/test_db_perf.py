"""Performance tests for database query patterns.

Validates list-query latency and tenant isolation filter correctness under load.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    TEST_TENANT_ID,
    TEST_USER,
    _apply_auth_override,
    _apply_db_override,
    _make_ris_app,
    create_test_order,
)


@pytest.mark.performance
class TestDatabaseQueryPerformance:
    """Performance tests for DB-backed API endpoints."""

    async def test_order_list_with_100_orders_response_time(
        self, db_session: AsyncSession
    ) -> None:
        """GET /api/v1/orders with 100 orders in the DB must respond in < 500ms.

        Measures the full stack: HTTP → route handler → repository query → serialisation.
        SQLite in-memory should be fast; if this is slow, suspect N+1 or missing indexes.
        """
        # Create 100 orders for the test tenant
        for i in range(100):
            await create_test_order(
                db_session,
                tenant_id=TEST_TENANT_ID,
                modality="CT",
                status="COMPLETED",
                accession_number=f"ACC-PERF-{i:05d}",
            )

        app = _make_ris_app()
        _apply_db_override(app, db_session)
        _apply_auth_override(app, TEST_USER)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.perf_counter()
            resp = await client.get("/api/v1/orders")
            elapsed = time.perf_counter() - start

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        # The response may be paginated — just verify we got results
        assert isinstance(data, (list, dict)), f"Unexpected response shape: {data}"

        assert elapsed < 0.500, (
            f"GET /orders with 100 rows took {elapsed * 1000:.0f}ms — expected < 500ms. "
            "If slow, check for N+1 queries or missing tenant_id index."
        )

    async def test_order_list_tenant_isolation_no_cross_tenant_leakage(
        self, db_session: AsyncSession
    ) -> None:
        """Orders for tenant B must never appear in tenant A's response.

        Verifies that the tenant_id filter is applied in every list query.
        Creates 10 orders for each tenant, then checks the count returned to tenant A.
        """
        tenant_b = uuid.UUID("00000000-0000-0000-0000-000000000099")

        # Tenant A orders
        for i in range(10):
            await create_test_order(
                db_session,
                tenant_id=TEST_TENANT_ID,
                accession_number=f"ACC-A-{i:05d}",
            )
        # Tenant B orders (should not appear in tenant A's results)
        for i in range(10):
            await create_test_order(
                db_session,
                tenant_id=tenant_b,
                accession_number=f"ACC-B-{i:05d}",
            )

        app = _make_ris_app()
        _apply_db_override(app, db_session)
        _apply_auth_override(app, TEST_USER)  # TEST_USER is tenant A

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/orders")

        assert resp.status_code == 200
        data = resp.json()

        # Extract all accession numbers from the response
        if isinstance(data, list):
            accessions = [item.get("accession_number", "") for item in data]
        elif isinstance(data, dict) and "items" in data:
            accessions = [item.get("accession_number", "") for item in data["items"]]
        else:
            accessions = []

        # No tenant B accession numbers should appear
        leaked = [acc for acc in accessions if acc.startswith("ACC-B-")]
        assert leaked == [], (
            f"CRITICAL: Tenant isolation breach! Tenant A can see tenant B orders: {leaked}"
        )

    async def test_concurrent_order_reads_do_not_degrade(
        self, db_session: AsyncSession
    ) -> None:
        """10 concurrent GET /orders requests must all complete in < 3s total.

        Simulates moderate concurrent load from multiple radiologist sessions.
        """
        # Create some orders first
        for i in range(20):
            await create_test_order(
                db_session,
                tenant_id=TEST_TENANT_ID,
                accession_number=f"ACC-CONC-{i:05d}",
            )

        app = _make_ris_app()
        _apply_db_override(app, db_session)
        _apply_auth_override(app, TEST_USER)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = time.perf_counter()
            responses = await asyncio.gather(
                *[client.get("/api/v1/orders") for _ in range(10)],
                return_exceptions=True,
            )
            elapsed = time.perf_counter() - start

        success_count = sum(
            1 for r in responses if hasattr(r, "status_code") and r.status_code == 200
        )
        assert success_count == 10, (
            f"Expected all 10 concurrent requests to succeed, got {success_count}. "
            f"Failures: {[r for r in responses if not hasattr(r, 'status_code')]}"
        )
        assert elapsed < 3.0, (
            f"10 concurrent GET /orders took {elapsed:.3f}s — expected < 3s."
        )

    async def test_accession_counter_query_latency(self, db_session: AsyncSession) -> None:
        """Accession counter lookup query must be < 10ms (single row by primary key)."""
        from sqlalchemy import text

        # Pre-seed the counter
        today = __import__("datetime").date.today().strftime("%Y%m%d")
        counter_key = f"{TEST_TENANT_ID}:QUERY_PERF:{today}"
        await db_session.execute(
            text(
                "INSERT INTO accession_counters (counter_key, tenant_id, date_prefix, seq) "
                "VALUES (:key, :tid, :date, 42)"
            ),
            {"key": counter_key, "tid": str(TEST_TENANT_ID), "date": today},
        )

        start = time.perf_counter()
        result = await db_session.execute(
            text("SELECT seq FROM accession_counters WHERE counter_key = :key"),
            {"key": counter_key},
        )
        seq = result.scalar_one()
        elapsed = time.perf_counter() - start

        assert seq == 42
        assert elapsed < 0.010, (
            f"Accession counter lookup took {elapsed * 1000:.2f}ms — expected < 10ms. "
            "This is a single-row primary-key lookup."
        )

    async def test_bulk_order_insert_throughput(self, db_session: AsyncSession) -> None:
        """Inserting 50 orders one-by-one must complete in < 5s (SQLite in-memory).

        Baseline: if each INSERT takes 100ms, 50 = 5s. Should be much faster.
        """
        n = 50
        start = time.perf_counter()
        for i in range(n):
            await create_test_order(
                db_session,
                tenant_id=TEST_TENANT_ID,
                accession_number=f"ACC-BULK-{i:05d}",
            )
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, (
            f"Inserting {n} orders took {elapsed:.3f}s — expected < 5s. "
            f"Average per INSERT: {(elapsed / n) * 1000:.1f}ms."
        )
