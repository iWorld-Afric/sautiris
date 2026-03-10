"""Performance tests for accession number generation.

Validates that the counter-table approach is fast and produces zero duplicates
under concurrent load.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.accession import generate_accession_number, peek_next_accession_number
from tests.conftest import TEST_TENANT_ID


@pytest.mark.performance
class TestAccessionGenerationPerformance:
    """Performance tests for the accession number generation subsystem."""

    async def test_accession_generation_throughput(self, db_session: AsyncSession) -> None:
        """100 sequential accession numbers must be generated in < 5s.

        At 100 in < 5s = 20/s minimum throughput for SQLite (production PostgreSQL
        will be significantly faster via atomic RETURNING).
        """
        n = 100
        start = time.perf_counter()
        results = []
        for _ in range(n):
            acc = await generate_accession_number(db_session, TEST_TENANT_ID, "PERF")
            results.append(acc)
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0, (
            f"{n} sequential accession generations took {elapsed:.3f}s — expected < 5s."
        )
        # Verify all are unique (sanity check)
        assert len(set(results)) == n, f"Duplicate accession numbers found in {n} sequential calls"

    async def test_accession_concurrent_uniqueness(self, db_session: AsyncSession) -> None:
        """50 concurrent accession-number requests must produce zero duplicates.

        This is the core correctness guarantee for concurrent order registration.
        The per-key asyncio.Lock in SQLite mode serializes the read-modify-write.
        Target: completes in < 10s.
        """
        n = 50
        start = time.perf_counter()
        results = await asyncio.gather(
            *[
                generate_accession_number(db_session, TEST_TENANT_ID, "CONCURRENT")
                for _ in range(n)
            ]
        )
        elapsed = time.perf_counter() - start

        assert len(set(results)) == n, (
            f"CRITICAL: {n - len(set(results))} duplicate accession numbers found! "
            f"Results: {sorted(results)}"
        )
        assert elapsed < 10.0, (
            f"{n} concurrent accession generations took {elapsed:.3f}s — expected < 10s."
        )

    async def test_accession_sequential_numbers_are_monotonically_increasing(
        self, db_session: AsyncSession
    ) -> None:
        """Sequence numbers must be strictly monotonically increasing.

        Each call increments the counter by exactly 1; no gaps except on date rollover.
        """
        prefix = "MONOTONE"
        n = 20
        results = []
        for _ in range(n):
            acc = await generate_accession_number(db_session, TEST_TENANT_ID, prefix)
            results.append(acc)

        seq_numbers = [int(acc.rsplit("-", 1)[-1]) for acc in results]
        for i in range(1, n):
            assert seq_numbers[i] == seq_numbers[i - 1] + 1, (
                f"Sequence gap at position {i}: {seq_numbers[i - 1]} → {seq_numbers[i]}. "
                "Sequence numbers must be strictly monotonic with no gaps."
            )

    async def test_peek_does_not_increment_counter(self, db_session: AsyncSession) -> None:
        """peek_next_accession_number must be read-only: it must NOT increment the sequence.

        After N peeks, generate_accession_number must still return seq=1 (first generation).
        """
        prefix = "PEEK"
        tenant = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")

        # Peek multiple times — should always see the same "next" value
        for _ in range(5):
            peeked = await peek_next_accession_number(db_session, tenant, prefix)
            assert peeked.endswith("-00001"), (
                f"Peek returned {peeked!r} — should always show seq=00001 before any generation."
            )

        # First real generation should be seq=1 (peek didn't increment)
        actual = await generate_accession_number(db_session, tenant, prefix)
        assert actual.endswith("-00001"), (
            f"First generate after peeks returned {actual!r} — expected seq=00001. "
            "peek_next must not increment the counter."
        )

    async def test_different_tenant_prefixes_do_not_interfere(
        self, db_session: AsyncSession
    ) -> None:
        """Two tenants generating accessions concurrently must not share sequence state."""
        tenant_a = TEST_TENANT_ID
        tenant_b = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

        # 20 concurrent generations split between two tenants
        tasks_a = [
            generate_accession_number(db_session, tenant_a, "TA") for _ in range(10)
        ]
        tasks_b = [
            generate_accession_number(db_session, tenant_b, "TB") for _ in range(10)
        ]

        all_results = await asyncio.gather(*tasks_a, *tasks_b)
        results_a = [r for r in all_results if r.startswith("TA-")]
        results_b = [r for r in all_results if r.startswith("TB-")]

        assert len(set(results_a)) == 10, f"Duplicates in tenant A: {sorted(results_a)}"
        assert len(set(results_b)) == 10, f"Duplicates in tenant B: {sorted(results_b)}"

        # Sequences for each tenant start at 1
        seqs_a = sorted(int(r.rsplit("-", 1)[-1]) for r in results_a)
        seqs_b = sorted(int(r.rsplit("-", 1)[-1]) for r in results_b)
        assert seqs_a == list(range(1, 11)), f"Tenant A seqs not 1-10: {seqs_a}"
        assert seqs_b == list(range(1, 11)), f"Tenant B seqs not 1-10: {seqs_b}"

    async def test_accession_generation_average_latency(self, db_session: AsyncSession) -> None:
        """Single-call average latency must be < 100ms for SQLite in tests.

        Establish a baseline to detect regressions in query complexity.
        """
        n = 20
        # Warm up
        for _ in range(3):
            await generate_accession_number(db_session, TEST_TENANT_ID, "WARMUP")

        start = time.perf_counter()
        for _ in range(n):
            await generate_accession_number(db_session, TEST_TENANT_ID, "LATENCY")
        elapsed = time.perf_counter() - start

        avg_ms = (elapsed / n) * 1000
        assert avg_ms < 100.0, (
            f"Average accession generation latency: {avg_ms:.2f}ms — expected < 100ms. "
            "Each generation is 2-3 SQL statements on an in-memory SQLite DB."
        )
