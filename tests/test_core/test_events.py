"""Tests for the domain event bus."""

from __future__ import annotations

import asyncio
from datetime import UTC
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


# ---------------------------------------------------------------------------
# Issue #16: New typed event dataclass tests
# ---------------------------------------------------------------------------


class TestNewTypedEvents:
    """Tests for typed events added in Issue #16."""

    def test_order_cancelled_defaults(self) -> None:
        from sautiris.core.events import OrderCancelled

        event = OrderCancelled()
        assert event.event_type == "order.cancelled"
        assert event.order_id == ""
        assert event.reason == ""
        assert event.from_status == ""
        assert event.event_id is not None

    def test_order_cancelled_with_data(self) -> None:
        from sautiris.core.events import OrderCancelled

        event = OrderCancelled(
            order_id="ORD-001", from_status="REQUESTED", reason="Patient no-show"
        )
        assert event.event_type == "order.cancelled"
        assert event.order_id == "ORD-001"
        assert event.reason == "Patient no-show"
        assert event.from_status == "REQUESTED"

    def test_order_reported(self) -> None:
        from sautiris.core.events import OrderReported

        event = OrderReported(order_id="ORD-001", from_status="COMPLETED")
        assert event.event_type == "order.reported"
        assert event.order_id == "ORD-001"
        assert event.from_status == "COMPLETED"

    def test_order_verified(self) -> None:
        from sautiris.core.events import OrderVerified

        event = OrderVerified(order_id="ORD-001", from_status="REPORTED")
        assert event.event_type == "order.verified"
        assert event.order_id == "ORD-001"

    def test_order_distributed(self) -> None:
        from sautiris.core.events import OrderDistributed

        event = OrderDistributed(order_id="ORD-001", from_status="VERIFIED")
        assert event.event_type == "order.distributed"
        assert event.order_id == "ORD-001"

    def test_report_created(self) -> None:
        from sautiris.core.events import ReportCreated

        event = ReportCreated(
            report_id="RPT-001",
            order_id="ORD-001",
            accession_number="ACC-001",
            reported_by="USR-001",
        )
        assert event.event_type == "report.created"
        assert event.report_id == "RPT-001"
        assert event.accession_number == "ACC-001"

    def test_report_amended(self) -> None:
        from sautiris.core.events import ReportAmended

        event = ReportAmended(
            report_id="RPT-001",
            order_id="ORD-001",
            accession_number="ACC-001",
            changed_by="USR-002",
        )
        assert event.event_type == "report.amended"
        assert event.changed_by == "USR-002"

    def test_worklist_status_changed(self) -> None:
        from sautiris.core.events import WorklistStatusChanged

        event = WorklistStatusChanged(
            item_id="WL-001",
            order_id="ORD-001",
            from_status="SCHEDULED",
            to_status="DISCONTINUED",
        )
        assert event.event_type == "worklist.status_changed"
        assert event.from_status == "SCHEDULED"
        assert event.to_status == "DISCONTINUED"

    def test_worklist_mpps_received(self) -> None:
        from sautiris.core.events import WorklistMPPSReceived

        event = WorklistMPPSReceived(
            item_id="WL-001",
            order_id="ORD-001",
            mpps_status="COMPLETED",
            mpps_uid="1.2.3.4",
        )
        assert event.event_type == "worklist.mpps_received"
        assert event.mpps_status == "COMPLETED"
        assert event.mpps_uid == "1.2.3.4"

    def test_schedule_slot_created(self) -> None:
        from sautiris.core.events import ScheduleSlotCreated

        event = ScheduleSlotCreated(
            slot_id="SLOT-001",
            order_id="ORD-001",
            room_id="CT-1",
            modality="CT",
            status="AVAILABLE",
        )
        assert event.event_type == "schedule.slot_created"
        assert event.room_id == "CT-1"
        assert event.modality == "CT"

    def test_schedule_slot_updated(self) -> None:
        from sautiris.core.events import ScheduleSlotUpdated

        event = ScheduleSlotUpdated(
            slot_id="SLOT-001",
            order_id="ORD-001",
            room_id="CT-2",
            modality="CT",
            status="BOOKED",
        )
        assert event.event_type == "schedule.slot_updated"
        assert event.room_id == "CT-2"

    def test_new_events_cannot_override_event_type(self) -> None:
        """All new typed events use field(init=False) so event_type is immutable."""
        from sautiris.core.events import (
            OrderCancelled,
            OrderDistributed,
            OrderReported,
            OrderVerified,
            ReportAmended,
            ReportCreated,
            ScheduleSlotCreated,
            ScheduleSlotUpdated,
            WorklistMPPSReceived,
            WorklistStatusChanged,
        )

        for cls, expected_type in [
            (OrderCancelled, "order.cancelled"),
            (OrderReported, "order.reported"),
            (OrderVerified, "order.verified"),
            (OrderDistributed, "order.distributed"),
            (ReportCreated, "report.created"),
            (ReportAmended, "report.amended"),
            (WorklistStatusChanged, "worklist.status_changed"),
            (WorklistMPPSReceived, "worklist.mpps_received"),
            (ScheduleSlotCreated, "schedule.slot_created"),
            (ScheduleSlotUpdated, "schedule.slot_updated"),
        ]:
            event = cls()
            assert event.event_type == expected_type, f"{cls.__name__} has wrong event_type"


# ---------------------------------------------------------------------------
# Issue #16: Service typed event emission tests
# ---------------------------------------------------------------------------


class TestServiceEmitsNewTypedEvents:
    """Verify services emit typed events instead of generic DomainEvent."""

    @pytest.mark.asyncio
    async def test_order_service_cancel_emits_order_cancelled(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import OrderCancelled
        from sautiris.services.order_service import OrderService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("order.cancelled", capture)

        mock_session = AsyncMock()
        svc = OrderService(mock_session, event_bus=bus)
        mock_order = MagicMock()
        mock_order.id = __import__("uuid").uuid4()
        mock_order.tenant_id = __import__("uuid").uuid4()
        mock_order.status = "REQUESTED"
        mock_order.special_instructions = None
        svc.repo = AsyncMock()
        svc.repo.get_by_id.return_value = mock_order
        svc.repo.update.return_value = mock_order

        await svc.cancel_order(mock_order.id, reason="Patient no-show")

        assert len(captured) == 1
        assert isinstance(captured[0], OrderCancelled)
        assert captured[0].order_id == str(mock_order.id)
        assert captured[0].reason == "Patient no-show"
        assert captured[0].from_status == "REQUESTED"

    @pytest.mark.asyncio
    async def test_report_service_create_emits_report_created(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import ReportCreated
        from sautiris.services.report_service import ReportService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("report.created", capture)

        mock_session = AsyncMock()
        svc = ReportService(mock_session, event_bus=bus)

        import uuid as _uuid

        mock_report = MagicMock()
        mock_report.id = _uuid.uuid4()
        mock_report.order_id = _uuid.uuid4()
        mock_report.tenant_id = _uuid.uuid4()
        mock_report.accession_number = "ACC-001"
        mock_report.report_status = "DRAFT"
        mock_report.reported_by = _uuid.uuid4()
        mock_report.is_critical = False
        mock_report.findings = "Normal"
        mock_report.impression = "Normal"
        mock_report.body = None

        svc.report_repo = AsyncMock()
        svc.report_repo.create.return_value = mock_report
        svc.report_repo.get_next_version_number.return_value = 1
        svc.report_repo.create_version.return_value = MagicMock()
        svc.template_repo = AsyncMock()
        svc.template_repo.find_default_template.return_value = None

        await svc.create_report(
            order_id=mock_report.order_id,
            accession_number="ACC-001",
            reported_by=mock_report.reported_by,
            reported_by_name="Dr. Test",
        )

        assert len(captured) == 1
        assert isinstance(captured[0], ReportCreated)
        assert captured[0].report_id == str(mock_report.id)

    @pytest.mark.asyncio
    async def test_report_service_amend_emits_report_amended(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import ReportAmended
        from sautiris.services.report_service import ReportService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("report.amended", capture)

        mock_session = AsyncMock()
        svc = ReportService(mock_session, event_bus=bus)

        import uuid as _uuid

        mock_report = MagicMock()
        mock_report.id = _uuid.uuid4()
        mock_report.order_id = _uuid.uuid4()
        mock_report.tenant_id = _uuid.uuid4()
        mock_report.accession_number = "ACC-001"
        mock_report.report_status = "FINAL"
        mock_report.reported_by = _uuid.uuid4()
        mock_report.is_critical = False
        mock_report.findings = "Updated findings"
        mock_report.impression = "Updated"
        mock_report.body = None

        svc.report_repo = AsyncMock()
        svc.report_repo.get_by_id.return_value = mock_report
        svc.report_repo.update.return_value = mock_report
        svc.report_repo.get_next_version_number.return_value = 2
        svc.report_repo.create_version.return_value = MagicMock()

        changed_by = _uuid.uuid4()
        await svc.amend_report(
            mock_report.id,
            changed_by=changed_by,
            findings="Amended findings",
        )

        assert len(captured) == 1
        assert isinstance(captured[0], ReportAmended)
        assert captured[0].changed_by == str(changed_by)

    # --- Order transition events (REPORTED, VERIFIED, DISTRIBUTED) ---

    @pytest.mark.asyncio
    async def test_order_transition_reported_emits_order_reported(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import OrderReported
        from sautiris.services.order_service import OrderService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("order.reported", capture)

        mock_session = AsyncMock()
        svc = OrderService(mock_session, event_bus=bus)
        mock_order = MagicMock()
        mock_order.id = __import__("uuid").uuid4()
        mock_order.tenant_id = __import__("uuid").uuid4()
        mock_order.status = "COMPLETED"
        svc.repo = AsyncMock()
        svc.repo.get_by_id.return_value = mock_order
        svc.repo.update.return_value = mock_order

        # _transition is private; we test via the public status change path
        # Use _transition directly since no public method triggers REPORTED
        await svc._transition(
            mock_order,
            __import__("sautiris.models.order", fromlist=["OrderStatus"]).OrderStatus.REPORTED,
        )

        assert len(captured) == 1
        assert isinstance(captured[0], OrderReported)
        assert captured[0].from_status == "COMPLETED"

    @pytest.mark.asyncio
    async def test_order_transition_verified_emits_order_verified(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import OrderVerified
        from sautiris.models.order import OrderStatus
        from sautiris.services.order_service import OrderService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("order.verified", capture)

        mock_session = AsyncMock()
        svc = OrderService(mock_session, event_bus=bus)
        mock_order = MagicMock()
        mock_order.id = __import__("uuid").uuid4()
        mock_order.tenant_id = __import__("uuid").uuid4()
        mock_order.status = "REPORTED"
        svc.repo = AsyncMock()
        svc.repo.update.return_value = mock_order

        await svc._transition(mock_order, OrderStatus.VERIFIED)

        assert len(captured) == 1
        assert isinstance(captured[0], OrderVerified)
        assert captured[0].from_status == "REPORTED"

    @pytest.mark.asyncio
    async def test_order_transition_distributed_emits_order_distributed(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import OrderDistributed
        from sautiris.models.order import OrderStatus
        from sautiris.services.order_service import OrderService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("order.distributed", capture)

        mock_session = AsyncMock()
        svc = OrderService(mock_session, event_bus=bus)
        mock_order = MagicMock()
        mock_order.id = __import__("uuid").uuid4()
        mock_order.tenant_id = __import__("uuid").uuid4()
        mock_order.status = "VERIFIED"
        svc.repo = AsyncMock()
        svc.repo.update.return_value = mock_order

        await svc._transition(mock_order, OrderStatus.DISTRIBUTED)

        assert len(captured) == 1
        assert isinstance(captured[0], OrderDistributed)
        assert captured[0].from_status == "VERIFIED"

    # --- Worklist events ---

    @pytest.mark.asyncio
    async def test_worklist_discontinued_emits_worklist_status_changed(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import WorklistStatusChanged
        from sautiris.models.worklist import WorklistStatus
        from sautiris.services.worklist_service import WorklistService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("worklist.status_changed", capture)

        mock_session = AsyncMock()
        svc = WorklistService(mock_session, event_bus=bus)
        mock_item = MagicMock()
        mock_item.id = __import__("uuid").uuid4()
        mock_item.order_id = __import__("uuid").uuid4()
        mock_item.tenant_id = __import__("uuid").uuid4()
        mock_item.status = WorklistStatus.SCHEDULED
        svc.repo = AsyncMock()
        svc.repo.get_by_id.return_value = mock_item
        svc.repo.update.return_value = mock_item

        await svc.update_procedure_step_status(mock_item.id, WorklistStatus.DISCONTINUED)

        assert len(captured) == 1
        assert isinstance(captured[0], WorklistStatusChanged)
        assert captured[0].to_status == str(WorklistStatus.DISCONTINUED)

    @pytest.mark.asyncio
    async def test_worklist_mpps_received_emits_typed_event(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import WorklistMPPSReceived
        from sautiris.models.worklist import MPPSStatus, WorklistStatus
        from sautiris.services.worklist_service import WorklistService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("worklist.mpps_received", capture)

        mock_session = AsyncMock()
        svc = WorklistService(mock_session, event_bus=bus)
        mock_item = MagicMock()
        mock_item.id = __import__("uuid").uuid4()
        mock_item.order_id = __import__("uuid").uuid4()
        mock_item.tenant_id = __import__("uuid").uuid4()
        mock_item.status = WorklistStatus.IN_PROGRESS
        mock_item.mpps_status = None
        mock_item.mpps_uid = None
        svc.repo = AsyncMock()
        svc.repo.get_by_id.return_value = mock_item
        svc.repo.update.return_value = mock_item

        await svc.receive_mpps(mock_item.id, mpps_status=MPPSStatus.COMPLETED, mpps_uid="1.2.3")

        assert len(captured) == 1
        assert isinstance(captured[0], WorklistMPPSReceived)
        assert captured[0].mpps_status == MPPSStatus.COMPLETED
        assert captured[0].mpps_uid == "1.2.3"

    # --- Schedule events ---

    @pytest.mark.asyncio
    async def test_schedule_create_slot_emits_slot_created(self) -> None:
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import ScheduleSlotCreated
        from sautiris.services.schedule_service import ScheduleService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("schedule.slot_created", capture)

        mock_session = AsyncMock()
        svc = ScheduleService(mock_session, event_bus=bus)
        import uuid as _uuid

        mock_slot = MagicMock()
        mock_slot.id = _uuid.uuid4()
        mock_slot.order_id = _uuid.uuid4()
        mock_slot.room_id = "CT-1"
        mock_slot.modality = "CT"
        mock_slot.status = "AVAILABLE"
        svc.repo = AsyncMock()
        svc.repo.find_conflicts.return_value = []
        svc.repo.create.return_value = mock_slot

        await svc.create_slot(
            order_id=mock_slot.order_id,
            room_id="CT-1",
            modality="CT",
            scheduled_start=datetime(2026, 3, 10, 9, 0, tzinfo=UTC),
            scheduled_end=datetime(2026, 3, 10, 9, 30, tzinfo=UTC),
        )

        assert len(captured) == 1
        assert isinstance(captured[0], ScheduleSlotCreated)
        assert captured[0].room_id == "CT-1"
        assert captured[0].modality == "CT"

    @pytest.mark.asyncio
    async def test_schedule_update_slot_emits_slot_updated(self) -> None:
        from datetime import datetime
        from unittest.mock import AsyncMock, MagicMock

        from sautiris.core.events import ScheduleSlotUpdated
        from sautiris.services.schedule_service import ScheduleService

        bus = EventBus()
        captured: list[DomainEvent] = []

        async def capture(event: DomainEvent) -> None:
            captured.append(event)

        bus.subscribe("schedule.slot_updated", capture)

        mock_session = AsyncMock()
        svc = ScheduleService(mock_session, event_bus=bus)
        import uuid as _uuid

        mock_slot = MagicMock()
        mock_slot.id = _uuid.uuid4()
        mock_slot.order_id = _uuid.uuid4()
        mock_slot.room_id = "CT-2"
        mock_slot.modality = "CT"
        mock_slot.status = "BOOKED"
        mock_slot.scheduled_start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        mock_slot.scheduled_end = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)
        mock_slot.technologist_id = None
        svc.repo = AsyncMock()
        svc.repo.get_by_id.return_value = mock_slot
        svc.repo.find_conflicts.return_value = []
        svc.repo.update.return_value = mock_slot

        await svc.update_slot(mock_slot.id, notes="Updated notes")

        assert len(captured) == 1
        assert isinstance(captured[0], ScheduleSlotUpdated)
        assert captured[0].room_id == "CT-2"
