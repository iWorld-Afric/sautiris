"""Tests for the domain event bus."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from sautiris.core.events import (
    CriticalFinding,
    DomainEvent,
    EventBus,
    ExamCompleted,
    ExamStarted,
    OrderCreated,
    OrderScheduled,
    ReportFinalized,
)

# ---------------------------------------------------------------------------
# EventBus core tests
# ---------------------------------------------------------------------------


class TestEventBus:
    """Tests for EventBus subscribe/publish/unsubscribe."""

    def test_initial_state(self) -> None:
        bus = EventBus()
        assert bus.handler_count == 0

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self) -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("order.created", handler)

        event = OrderCreated(order_id="ORD-001", patient_id="PAT-001")
        errors = await bus.publish(event)

        assert errors == []
        handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_multiple_handlers(self) -> None:
        bus = EventBus()
        handler1 = AsyncMock()
        handler2 = AsyncMock()
        bus.subscribe("order.created", handler1)
        bus.subscribe("order.created", handler2)

        event = OrderCreated(order_id="ORD-001")
        errors = await bus.publish(event)

        assert errors == []
        handler1.assert_called_once_with(event)
        handler2.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_no_handlers_returns_empty(self) -> None:
        bus = EventBus()
        event = OrderCreated(order_id="ORD-001")
        errors = await bus.publish(event)
        assert errors == []

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("order.created", handler)
        bus.unsubscribe("order.created", handler)

        event = OrderCreated(order_id="ORD-001")
        await bus.publish(event)

        handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_handler(self) -> None:
        bus = EventBus()
        handler = AsyncMock()
        # Should not raise
        bus.unsubscribe("order.created", handler)

    @pytest.mark.asyncio
    async def test_handler_error_returns_exceptions(self) -> None:
        bus = EventBus()
        good_handler = AsyncMock()
        bad_handler = AsyncMock(side_effect=RuntimeError("boom"))

        bus.subscribe("order.created", good_handler)
        bus.subscribe("order.created", bad_handler)

        event = OrderCreated(order_id="ORD-001")
        errors = await bus.publish(event)

        assert len(errors) == 1
        assert isinstance(errors[0], RuntimeError)
        # Good handler still executed
        good_handler.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_handlers_run_concurrently(self) -> None:
        bus = EventBus()
        call_order: list[int] = []

        async def slow_handler(event: DomainEvent) -> None:
            await asyncio.sleep(0.05)
            call_order.append(1)

        async def fast_handler(event: DomainEvent) -> None:
            call_order.append(2)

        bus.subscribe("order.created", slow_handler)
        bus.subscribe("order.created", fast_handler)

        event = OrderCreated(order_id="ORD-001")
        await bus.publish(event)

        # Both handlers ran
        assert set(call_order) == {1, 2}

    def test_clear(self) -> None:
        bus = EventBus()
        bus.subscribe("order.created", AsyncMock())
        bus.subscribe("report.finalized", AsyncMock())
        assert bus.handler_count == 2
        bus.clear()
        assert bus.handler_count == 0

    def test_handler_count(self) -> None:
        bus = EventBus()
        bus.subscribe("order.created", AsyncMock())
        bus.subscribe("order.created", AsyncMock())
        bus.subscribe("report.finalized", AsyncMock())
        assert bus.handler_count == 3

    @pytest.mark.asyncio
    async def test_different_event_types_isolated(self) -> None:
        bus = EventBus()
        order_handler = AsyncMock()
        report_handler = AsyncMock()
        bus.subscribe("order.created", order_handler)
        bus.subscribe("report.finalized", report_handler)

        event = OrderCreated(order_id="ORD-001")
        await bus.publish(event)

        order_handler.assert_called_once()
        report_handler.assert_not_called()


# ---------------------------------------------------------------------------
# Concrete event tests
# ---------------------------------------------------------------------------


class TestConcreteEvents:
    """Tests for concrete event dataclass fields and defaults."""

    def test_order_created_defaults(self) -> None:
        event = OrderCreated()
        assert event.event_type == "order.created"
        assert event.order_id == ""
        assert event.patient_id == ""
        assert event.modality == ""
        assert event.event_id is not None

    def test_order_created_with_data(self) -> None:
        event = OrderCreated(
            order_id="ORD-001",
            patient_id="PAT-001",
            modality="CT",
            urgency="STAT",
        )
        assert event.order_id == "ORD-001"
        assert event.modality == "CT"

    def test_order_scheduled(self) -> None:
        event = OrderScheduled(
            order_id="ORD-001",
            schedule_slot_id="SLOT-001",
            room_id="CT-1",
        )
        assert event.event_type == "order.scheduled"
        assert event.room_id == "CT-1"

    def test_exam_started(self) -> None:
        event = ExamStarted(
            order_id="ORD-001",
            mpps_uid="1.2.3.4",
            station_ae_title="CT_SCANNER_1",
        )
        assert event.event_type == "exam.started"
        assert event.mpps_uid == "1.2.3.4"

    def test_exam_completed(self) -> None:
        event = ExamCompleted(
            order_id="ORD-001",
            study_instance_uid="1.2.3.4.5",
        )
        assert event.event_type == "exam.completed"
        assert event.study_instance_uid == "1.2.3.4.5"

    def test_report_finalized(self) -> None:
        event = ReportFinalized(
            order_id="ORD-001",
            report_id="RPT-001",
            is_critical=True,
        )
        assert event.event_type == "report.finalized"
        assert event.is_critical is True

    def test_critical_finding(self) -> None:
        event = CriticalFinding(
            order_id="ORD-001",
            finding_description="Pneumothorax",
            urgency="IMMEDIATE",
        )
        assert event.event_type == "finding.critical"
        assert event.urgency == "IMMEDIATE"

    def test_event_has_uuid_and_timestamp(self) -> None:
        event = OrderCreated()
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_drl_exceeded_event(self) -> None:
        from sautiris.core.events import DRLExceeded

        event = DRLExceeded(
            order_id="ORD-001",
            dose_record_id="DOSE-001",
            modality="CT",
            body_part="HEAD",
            ctdi_vol=90.0,
            dlp=1500.0,
        )
        assert event.event_type == "dose.drl_exceeded"
        assert event.modality == "CT"
        assert event.ctdi_vol == 90.0

    def test_ai_finding_created_event(self) -> None:
        from sautiris.core.events import AIFindingCreated

        event = AIFindingCreated(
            order_id="ORD-001",
            study_instance_uid="1.2.3",
            finding_type="nodule",
            confidence=0.93,
        )
        assert event.event_type == "ai.finding_created"
        assert event.finding_type == "nodule"
        assert event.confidence == 0.93


class TestCriticalHandlers:
    """Tests for critical handler behaviour (is_critical=True bubbles exceptions)."""

    @pytest.mark.asyncio
    async def test_critical_handler_bubbles_exception(self) -> None:
        bus = EventBus()

        async def bad_handler(event: DomainEvent) -> None:
            raise RuntimeError("critical failure")

        bus.subscribe("order.created", bad_handler, is_critical=True)
        event = OrderCreated(order_id="ORD-001")
        with pytest.raises(RuntimeError, match="critical failure"):
            await bus.publish(event)

    @pytest.mark.asyncio
    async def test_multiple_critical_handlers_first_error_propagates(self) -> None:
        """GAP-11: When multiple critical handlers fail, the FIRST error propagates.

        Fan-out continues through all handlers (even if earlier ones fail), but
        only the first critical exception is raised after fan-out completes.
        """
        bus = EventBus()

        # Track which handlers were actually called
        called: list[str] = []

        async def critical_a(event: DomainEvent) -> None:
            called.append("a")
            raise ValueError("error from A")

        async def critical_b(event: DomainEvent) -> None:
            called.append("b")
            raise RuntimeError("error from B")

        async def non_critical(event: DomainEvent) -> None:
            called.append("nc")

        # Register: critical A first, then critical B, then non-critical
        bus.subscribe("order.created", critical_a, is_critical=True)
        bus.subscribe("order.created", critical_b, is_critical=True)
        bus.subscribe("order.created", non_critical)

        event = OrderCreated(order_id="ORD-001")
        # The first critical handler's exception (ValueError from A) is raised
        with pytest.raises(ValueError, match="error from A"):
            await bus.publish(event)

        # All three handlers ran (fan-out completes before exception is raised)
        assert "a" in called, "critical_a handler must have been called"
        assert "b" in called, "critical_b handler must have been called"
        assert "nc" in called, "non_critical handler must have been called"

    @pytest.mark.asyncio
    async def test_non_critical_handler_fanout_continues(self) -> None:
        """Non-critical handler failure must not stop other handlers."""
        from unittest.mock import AsyncMock

        bus = EventBus()
        good = AsyncMock()
        bad = AsyncMock(side_effect=RuntimeError("non-critical failure"))

        bus.subscribe("order.created", bad, is_critical=False)
        bus.subscribe("order.created", good)

        event = OrderCreated(order_id="ORD-001")
        errors = await bus.publish(event)

        assert len(errors) == 1
        good.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_and_non_critical_mixed(self) -> None:
        """If critical handler fails, exception propagates; non-critical handlers still run."""
        from unittest.mock import AsyncMock

        bus = EventBus()
        non_critical = AsyncMock()

        async def crit_handler(event: DomainEvent) -> None:
            raise ValueError("critical boom")

        bus.subscribe("order.created", crit_handler, is_critical=True)
        bus.subscribe("order.created", non_critical)

        event = OrderCreated(order_id="ORD-001")
        with pytest.raises(ValueError, match="critical boom"):
            await bus.publish(event)

        # Non-critical handler still ran
        non_critical.assert_called_once()


class TestServiceEmitsTypedEvents:
    """Verify services emit typed events (not generic DomainEvent)."""

    @pytest.mark.asyncio
    async def test_dose_service_emits_drl_exceeded_typed_event(self) -> None:
        from unittest.mock import AsyncMock

        from sqlalchemy.ext.asyncio import AsyncSession

        from sautiris.core.events import DRLExceeded
        from sautiris.services.dose_service import DoseService

        mock_session = AsyncMock(spec=AsyncSession)
        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("dose.drl_exceeded", capture)

        svc = DoseService(mock_session, event_bus=bus)
        # _check_drl is synchronous and returns True for CT HEAD with ctdi_vol=9999
        svc.drl = {"CT": {"HEAD": {"ctdi_vol": 60.0}}}

        mock_session.execute.return_value.scalar_one.return_value = None
        from unittest.mock import MagicMock

        mock_dose = MagicMock()
        mock_dose.id = __import__("uuid").uuid4()
        svc.repo = AsyncMock()
        svc.repo.create.return_value = mock_dose

        import uuid as _uuid

        await svc.record_dose(
            order_id=_uuid.uuid4(),
            modality="CT",
            body_part="HEAD",
            ctdi_vol=9999.0,
        )

        assert len(captured) == 1
        assert isinstance(captured[0], DRLExceeded)
