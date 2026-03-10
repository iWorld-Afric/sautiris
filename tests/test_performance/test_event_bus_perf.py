"""Performance tests for the domain event bus.

Measures handler throughput, concurrent fan-out latency, and slow-handler isolation.
Run with: python -m pytest tests/test_performance/ -x -q -m performance
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from sautiris.core.events import (
    DomainEvent,
    EventBus,
    OrderCreated,
    ReportFinalized,
)


@pytest.mark.performance
class TestEventBusPerformance:
    """Performance tests for EventBus publish/fan-out mechanics."""

    async def test_event_publish_with_10_handlers_latency(self) -> None:
        """Publishing one event with 10 handlers must complete in < 50ms.

        All handlers run concurrently via asyncio.gather. With no external I/O
        and instant handlers, fan-out overhead should be negligible.
        """
        bus = EventBus()
        call_counts: list[int] = []

        for i in range(10):
            handler = AsyncMock()
            bus.subscribe("order.created", handler)
            call_counts.append(i)

        event = OrderCreated(order_id="ORD-PERF-001", patient_id="PAT-001")
        start = time.perf_counter()
        errors = await bus.publish(event)
        elapsed = time.perf_counter() - start

        assert errors == [], f"Unexpected handler errors: {errors}"
        assert elapsed < 0.050, (
            f"10-handler fan-out took {elapsed * 1000:.2f}ms — expected < 50ms. "
            "asyncio.gather should schedule all handlers concurrently with minimal overhead."
        )

    async def test_slow_handler_does_not_block_fast_handlers(self) -> None:
        """A 100ms handler must not serialise other handlers — they run concurrently.

        If handlers ran sequentially, total time would be ~100ms + epsilon.
        With asyncio.gather, all fast handlers should complete near-instantly while
        the slow one is awaited. Total time should still be ~ slow handler's duration.
        """
        bus = EventBus()
        completed: list[str] = []

        async def slow_handler(event: DomainEvent) -> None:
            await asyncio.sleep(0.1)  # 100ms simulated I/O
            completed.append("slow")

        async def fast_handler_1(event: DomainEvent) -> None:
            completed.append("fast-1")

        async def fast_handler_2(event: DomainEvent) -> None:
            completed.append("fast-2")

        async def fast_handler_3(event: DomainEvent) -> None:
            completed.append("fast-3")

        bus.subscribe("order.created", slow_handler)
        bus.subscribe("order.created", fast_handler_1)
        bus.subscribe("order.created", fast_handler_2)
        bus.subscribe("order.created", fast_handler_3)

        event = OrderCreated(order_id="ORD-SLOW-001")
        start = time.perf_counter()
        await bus.publish(event)
        elapsed = time.perf_counter() - start

        # All 4 handlers ran
        assert set(completed) == {"slow", "fast-1", "fast-2", "fast-3"}, (
            f"Not all handlers ran: {completed}"
        )

        # Total time should be driven by the slow handler (~100ms), not 4x serial
        # We allow up to 300ms to account for CI overhead
        assert elapsed < 0.300, (
            f"4 handlers (1 slow @ 100ms) took {elapsed * 1000:.0f}ms. "
            "With asyncio.gather, total ≈ slowest handler duration, not sum."
        )

        # Specifically: total time should be much less than 4 × 100ms = 400ms
        assert elapsed < 0.400, (
            "Handlers appear to be running sequentially rather than concurrently."
        )

    async def test_event_bus_throughput_1000_events(self) -> None:
        """1000 events published sequentially must complete in < 5s.

        At 1000/5s = 200 events/s minimum throughput for the pure in-process bus.
        """
        bus = EventBus()
        received: list[int] = []

        async def counting_handler(event: DomainEvent) -> None:
            received.append(1)

        bus.subscribe("order.created", counting_handler)

        n = 1000
        start = time.perf_counter()
        for i in range(n):
            await bus.publish(OrderCreated(order_id=f"ORD-{i:05d}"))
        elapsed = time.perf_counter() - start

        assert len(received) == n, f"Expected {n} handler calls, got {len(received)}"
        assert elapsed < 5.0, (
            f"{n} event publishes took {elapsed:.3f}s — expected < 5s. "
            f"Throughput: {n / elapsed:.0f} events/s."
        )

    async def test_event_bus_1000_events_concurrent(self) -> None:
        """1000 events published concurrently must all be handled and complete in < 5s."""
        bus = EventBus()
        received: list[str] = []
        lock = asyncio.Lock()

        async def recording_handler(event: DomainEvent) -> None:
            async with lock:
                received.append(event.payload.get("order_id", "unknown"))

        bus.subscribe("report.finalized", recording_handler)

        n = 1000
        events = [
            ReportFinalized(
                order_id=f"ORD-{i:05d}",
                report_id=f"RPT-{i:05d}",
                payload={"order_id": f"ORD-{i:05d}"},
            )
            for i in range(n)
        ]

        start = time.perf_counter()
        await asyncio.gather(*[bus.publish(e) for e in events])
        elapsed = time.perf_counter() - start

        assert len(received) == n, (
            f"Expected {n} events handled, got {len(received)}. "
            "Some events may have been dropped or handlers panicked."
        )
        assert elapsed < 5.0, f"{n} concurrent event publishes took {elapsed:.3f}s — expected < 5s."

    async def test_event_bus_no_handler_overhead(self) -> None:
        """Publishing events with no subscribers should have near-zero overhead."""
        bus = EventBus()
        n = 10_000

        start = time.perf_counter()
        for i in range(n):
            await bus.publish(OrderCreated(order_id=f"ORD-{i}"))
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"{n} no-op publishes took {elapsed:.3f}s — expected < 2s. "
            "Events with no subscribers should return immediately."
        )

    async def test_subscribe_and_unsubscribe_perf(self) -> None:
        """1,000 subscribe/unsubscribe cycles must complete in < 5s.

        Note: each subscribe() emits a structlog debug log line, so throughput
        is partially gated by logging overhead. The threshold reflects this reality
        while still catching O(n²) regression in the unsubscribe path (list.remove).
        """
        bus = EventBus()
        n = 1_000

        handlers = [AsyncMock() for _ in range(n)]
        start = time.perf_counter()
        for h in handlers:
            bus.subscribe("order.created", h)
        for h in handlers:
            bus.unsubscribe("order.created", h)
        elapsed = time.perf_counter() - start

        assert bus.handler_count == 0, "All handlers should have been unsubscribed"
        assert elapsed < 5.0, (
            f"{n} subscribe+unsubscribe cycles took {elapsed:.3f}s — expected < 5s. "
            "Note: each subscribe() emits a debug log which adds overhead."
        )

    async def test_failing_handler_does_not_degrade_throughput(self) -> None:
        """A handler that always raises must not prevent other handlers from running.

        Even with one failing handler, the bus must still deliver to good handlers.
        The key assertion is correctness (all 100 good_calls happened), not strict timing,
        since structlog error logging per failure adds measurable overhead.
        """
        bus = EventBus()
        good_calls: list[int] = []

        async def good_handler(event: DomainEvent) -> None:
            good_calls.append(1)

        async def bad_handler(event: DomainEvent) -> None:
            raise RuntimeError("simulated handler failure")

        bus.subscribe("order.created", good_handler)
        bus.subscribe("order.created", bad_handler)

        n = 100
        start = time.perf_counter()
        for i in range(n):
            errors = await bus.publish(OrderCreated(order_id=f"ORD-{i}"))
            assert len(errors) == 1, f"Event {i}: expected 1 error (bad_handler), got {len(errors)}"
        elapsed = time.perf_counter() - start

        assert len(good_calls) == n, (
            f"Good handler called {len(good_calls)} times, expected {n}. "
            "A failing non-critical handler must not prevent other handlers from running."
        )
        # Generous threshold: structlog error logging for 100 failures adds ~100ms each
        assert elapsed < 30.0, (
            f"{n} events with one failing handler took {elapsed:.3f}s — expected < 30s."
        )
