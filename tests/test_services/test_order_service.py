"""Tests for OrderService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.order import OrderStatus
from sautiris.services.order_service import (
    InvalidTransitionError,
    OrderNotFoundError,
    OrderService,
)
from tests.conftest import TEST_TENANT_ID


@pytest.fixture
def order_service(db_session: AsyncSession) -> OrderService:
    return OrderService(db_session)


async def test_create_order(order_service: OrderService) -> None:
    order = await order_service.create_order(
        patient_id=uuid.uuid4(),
        modality="CT",
        urgency="ROUTINE",
        clinical_indication="Chest pain",
    )
    assert order.id is not None
    assert order.status == OrderStatus.REQUESTED
    assert order.modality == "CT"
    assert "CT" in order.accession_number
    assert order.accession_number.endswith("00001")
    assert order.tenant_id == TEST_TENANT_ID


async def test_create_order_accession_sequential(
    order_service: OrderService,
) -> None:
    o1 = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    o2 = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    assert o1.accession_number != o2.accession_number
    assert o1.accession_number.endswith("00001")
    assert o2.accession_number.endswith("00002")


async def test_get_order(order_service: OrderService) -> None:
    created = await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")
    fetched = await order_service.get_order(created.id)
    assert fetched.id == created.id
    assert fetched.modality == "MR"


async def test_get_order_not_found(order_service: OrderService) -> None:
    with pytest.raises(OrderNotFoundError):
        await order_service.get_order(uuid.uuid4())


async def test_list_orders(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")

    items, total = await order_service.list_orders()
    assert total == 2
    assert len(items) == 2


async def test_list_orders_filter_modality(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")

    items, total = await order_service.list_orders(modality="CT")
    assert total == 1
    assert items[0].modality == "CT"


async def test_update_order_requested(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    updated = await order_service.update_order(order.id, clinical_indication="Updated")
    assert updated.clinical_indication == "Updated"


async def test_update_order_completed_fails(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    await order_service.complete_exam(order.id)

    with pytest.raises(InvalidTransitionError):
        await order_service.update_order(order.id, clinical_indication="Nope")


async def test_schedule_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    scheduled = await order_service.schedule_order(order.id, datetime.now(UTC))
    assert scheduled.status == OrderStatus.SCHEDULED
    assert scheduled.scheduled_at is not None


async def test_start_exam(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    started = await order_service.start_exam(order.id)
    assert started.status == OrderStatus.IN_PROGRESS
    assert started.started_at is not None


async def test_complete_exam(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    completed = await order_service.complete_exam(order.id)
    assert completed.status == OrderStatus.COMPLETED
    assert completed.completed_at is not None


async def test_cancel_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    cancelled = await order_service.cancel_order(order.id, reason="Patient refused")
    assert cancelled.status == OrderStatus.CANCELLED
    assert "Patient refused" in (cancelled.special_instructions or "")


async def test_cancel_completed_order(order_service: OrderService) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.schedule_order(order.id, datetime.now(UTC))
    await order_service.start_exam(order.id)
    await order_service.complete_exam(order.id)
    cancelled = await order_service.cancel_order(order.id, reason="Clinically inappropriate")
    assert cancelled.status == OrderStatus.CANCELLED
    assert "Clinically inappropriate" in (cancelled.special_instructions or "")


async def test_invalid_transition_requested_to_completed(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    with pytest.raises(InvalidTransitionError):
        await order_service.complete_exam(order.id)


async def test_invalid_transition_cancelled_to_scheduled(
    order_service: OrderService,
) -> None:
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.cancel_order(order.id, reason="Test cancellation")
    with pytest.raises(InvalidTransitionError):
        await order_service.schedule_order(order.id, datetime.now(UTC))


async def test_get_order_stats(order_service: OrderService) -> None:
    await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")
    await order_service.create_order(patient_id=uuid.uuid4(), modality="MR")
    stats = await order_service.get_order_stats()
    assert stats.get("REQUESTED", 0) == 2


async def test_get_next_accession(order_service: OrderService) -> None:
    accession = await order_service.get_next_accession("CT")
    assert "CT" in accession
    assert accession.endswith("00001")


# ---------------------------------------------------------------------------
# GAP-C2: OrderService._publish error logging
# ---------------------------------------------------------------------------


async def test_event_publish_errors_are_logged(db_session: AsyncSession) -> None:
    """GAP-C2: _publish logs an ERROR for each error returned by event_bus.publish.

    When an event handler raises, EventBus.publish collects the exceptions and
    returns them.  OrderService._publish must iterate those errors and emit a
    logger.error for each one rather than silently dropping or re-raising.
    """
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _failing_handler(event: object) -> None:
        raise ValueError("downstream handler boom")

    bus.subscribe("order.created", _failing_handler)
    service = OrderService(db_session, event_bus=bus)

    # _publish is in the mixin; patch mixins.logger for handler-error logging
    with patch("sautiris.services.mixins.logger") as mock_logger:
        await service.create_order(
            patient_id=uuid.uuid4(),
            modality="CT",
            urgency="ROUTINE",
            clinical_indication="Test error logging",
        )
        mock_logger.error.assert_called()
        error_calls = mock_logger.error.call_args_list
        assert any("event_bus.handler_error" in str(call.args) for call in error_calls), (
            f"Expected 'event_bus.handler_error' in error calls. Got: {error_calls}"
        )


async def test_event_publish_no_errors_does_not_log_error(db_session: AsyncSession) -> None:
    """_publish does NOT emit handler_error errors when all handlers succeed."""
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _ok_handler(event: object) -> None:
        pass  # success

    bus.subscribe("order.created", _ok_handler)
    service = OrderService(db_session, event_bus=bus)

    # _publish is in the mixin; patch mixins.logger for handler-error logging
    with patch("sautiris.services.mixins.logger") as mock_logger:
        await service.create_order(
            patient_id=uuid.uuid4(),
            modality="MR",
        )
        handler_error_calls = [
            call
            for call in mock_logger.error.call_args_list
            if "event_bus.handler_error" in str(call.args)
        ]
        assert len(handler_error_calls) == 0


# ---------------------------------------------------------------------------
# GAP-R4-5: OrderService.peek_next_accession
# ---------------------------------------------------------------------------


async def test_peek_next_accession_returns_valid_format(
    order_service: OrderService,
) -> None:
    """peek_next_accession returns a string with the modality prefix in the expected format."""
    accession = await order_service.peek_next_accession("CT")
    assert "CT" in accession
    # Format: {prefix}-{YYYYMMDD}-{seq:05d}
    parts = accession.split("-")
    assert len(parts) == 3, f"Expected 3 parts in '{accession}', got {len(parts)}"
    assert parts[0] == "CT"
    assert len(parts[1]) == 8  # YYYYMMDD
    assert parts[2].isdigit()


async def test_peek_next_accession_is_read_only(
    order_service: OrderService,
) -> None:
    """Two consecutive peek calls return the same value — counter is not incremented."""
    peek1 = await order_service.peek_next_accession("MR")
    peek2 = await order_service.peek_next_accession("MR")
    assert peek1 == peek2, (
        f"peek_next_accession should be read-only but returned different values: "
        f"{peek1!r} vs {peek2!r}"
    )


async def test_peek_next_accession_does_not_consume_sequence(
    order_service: OrderService,
) -> None:
    """peek does not advance the counter; a subsequent create_order gets the peeked number."""
    peeked = await order_service.peek_next_accession("CR")
    # Now actually create an order — it should receive the same sequence number that was peeked
    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CR")
    assert order.accession_number == peeked, (
        f"Expected create_order to produce {peeked!r} (the peeked value), "
        f"got {order.accession_number!r}"
    )


async def test_peek_next_accession_after_order_creation(
    order_service: OrderService,
) -> None:
    """peek after an order is created reflects the incremented counter."""
    await order_service.create_order(patient_id=uuid.uuid4(), modality="XA")
    peeked = await order_service.peek_next_accession("XA")
    # After 1 creation, next peek should show seq=2
    assert peeked.endswith("00002"), f"Expected sequence 00002, got {peeked!r}"


# ---------------------------------------------------------------------------
# GAP-H4: OrderService.update_order() — unknown field warning
# ---------------------------------------------------------------------------


async def test_update_order_unknown_field_logs_warning(
    order_service: OrderService,
) -> None:
    """GAP-H4: Passing an unknown field to update_order() logs a warning and does not crash."""
    from unittest.mock import patch

    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")

    with patch("sautiris.services.order_service.logger") as mock_logger:
        updated = await order_service.update_order(order.id, nonexistent_field="bogus_value")

    assert updated is not None  # no crash
    mock_logger.warning.assert_called()
    warning_key = mock_logger.warning.call_args[0][0]
    assert "unknown_fields" in warning_key


async def test_update_order_non_updatable_field_logs_warning(
    order_service: OrderService,
) -> None:
    """Passing a valid but non-updatable model field (status) logs a non_updatable_field warning."""
    from unittest.mock import patch

    order = await order_service.create_order(patient_id=uuid.uuid4(), modality="CT")

    with patch("sautiris.services.order_service.logger") as mock_logger:
        updated = await order_service.update_order(order.id, status="REQUESTED")

    assert updated is not None  # no crash
    mock_logger.warning.assert_called()
    warning_keys = [call.args[0] for call in mock_logger.warning.call_args_list]
    assert any("non_updatable_field" in key for key in warning_keys)
