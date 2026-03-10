"""Tests for ScheduleService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.services.schedule_service import (
    ScheduleConflictError,
    ScheduleService,
    SlotNotDeletableError,
    SlotNotFoundError,
)


@pytest.fixture
def schedule_service(db_session: AsyncSession) -> ScheduleService:
    return ScheduleService(db_session)


def _make_times(offset_hours: int = 0) -> tuple[datetime, datetime]:
    start = datetime.now(UTC) + timedelta(hours=offset_hours)
    end = start + timedelta(minutes=30)
    return start, end


async def test_create_slot(schedule_service: ScheduleService) -> None:
    start, end = _make_times()
    slot = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    assert slot.id is not None
    assert slot.room_id == "ROOM-CT-1"
    assert slot.status == "AVAILABLE"


async def test_create_overlapping_slot_conflict(
    schedule_service: ScheduleService,
) -> None:
    start, end = _make_times()
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    with pytest.raises(ScheduleConflictError):
        await schedule_service.create_slot(
            order_id=uuid.uuid4(),
            room_id="ROOM-CT-1",
            modality="CT",
            scheduled_start=start + timedelta(minutes=10),
            scheduled_end=end + timedelta(minutes=10),
        )


async def test_create_slot_different_room_no_conflict(
    schedule_service: ScheduleService,
) -> None:
    start, end = _make_times()
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    slot2 = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-MR-1",
        modality="MR",
        scheduled_start=start,
        scheduled_end=end,
    )
    assert slot2.room_id == "ROOM-MR-1"


async def test_technologist_double_booking_conflict(
    schedule_service: ScheduleService,
) -> None:
    start, end = _make_times()
    tech_id = uuid.uuid4()
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
        technologist_id=tech_id,
    )
    with pytest.raises(ScheduleConflictError):
        await schedule_service.create_slot(
            order_id=uuid.uuid4(),
            room_id="ROOM-CT-2",
            modality="CT",
            scheduled_start=start,
            scheduled_end=end,
            technologist_id=tech_id,
        )


async def test_get_slot(schedule_service: ScheduleService) -> None:
    start, end = _make_times()
    created = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    fetched = await schedule_service.get_slot(created.id)
    assert fetched.id == created.id


async def test_get_slot_not_found(schedule_service: ScheduleService) -> None:
    with pytest.raises(SlotNotFoundError):
        await schedule_service.get_slot(uuid.uuid4())


async def test_delete_available_slot(schedule_service: ScheduleService) -> None:
    start, end = _make_times()
    slot = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    await schedule_service.delete_slot(slot.id)
    with pytest.raises(SlotNotFoundError):
        await schedule_service.get_slot(slot.id)


async def test_delete_booked_slot_fails(
    schedule_service: ScheduleService,
) -> None:
    start, end = _make_times()
    slot = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    await schedule_service.update_slot(slot.id, status="BOOKED")
    with pytest.raises(SlotNotDeletableError):
        await schedule_service.delete_slot(slot.id)


async def test_list_slots(schedule_service: ScheduleService) -> None:
    for i in range(3):
        start, end = _make_times(offset_hours=i)
        await schedule_service.create_slot(
            order_id=uuid.uuid4(),
            room_id=f"ROOM-{i}",
            modality="CT",
            scheduled_start=start,
            scheduled_end=end,
        )
    items, total = await schedule_service.list_slots()
    assert total == 3


async def test_list_rooms(schedule_service: ScheduleService) -> None:
    start, end = _make_times()
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CT-1",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )
    s2, e2 = _make_times(offset_hours=1)
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-MR-1",
        modality="MR",
        scheduled_start=s2,
        scheduled_end=e2,
    )
    rooms = await schedule_service.list_rooms()
    assert set(rooms) == {"ROOM-CT-1", "ROOM-MR-1"}


# ---------------------------------------------------------------------------
# GAP: ScheduleService._publish error logging
# ---------------------------------------------------------------------------


async def test_schedule_publish_handler_error_is_logged_as_error(
    db_session: AsyncSession,
) -> None:
    """ScheduleService._publish logs ERROR for each failing event handler.

    R2-H5: ScheduleService uses logger.error for handler failures to ensure
    event delivery problems are visible in monitoring.
    """
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _failing_handler(event: object) -> None:
        raise ValueError("schedule notification system down")

    bus.subscribe("schedule.slot_created", _failing_handler)
    svc = ScheduleService(db_session, event_bus=bus)

    start = datetime.now(UTC) + timedelta(hours=5)
    end = start + timedelta(minutes=30)

    with patch("sautiris.services.schedule_service.logger") as mock_logger:
        await svc.create_slot(
            order_id=uuid.uuid4(),
            room_id="ROOM-TEST-1",
            modality="CT",
            scheduled_start=start,
            scheduled_end=end,
        )
        # _publish must call logger.error for the handler failure
        mock_logger.error.assert_called()
        error_calls = mock_logger.error.call_args_list
        assert any("event_bus.handler_error" in str(call.args) for call in error_calls), (
            f"Expected 'event_bus.handler_error' in errors. Got: {error_calls}"
        )


async def test_schedule_publish_no_error_does_not_log_error(
    db_session: AsyncSession,
) -> None:
    """ScheduleService._publish does NOT log error when all handlers succeed."""
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _ok_handler(event: object) -> None:
        pass  # success

    bus.subscribe("schedule.slot_created", _ok_handler)
    svc = ScheduleService(db_session, event_bus=bus)

    start = datetime.now(UTC) + timedelta(hours=6)
    end = start + timedelta(minutes=30)

    with patch("sautiris.services.schedule_service.logger") as mock_logger:
        await svc.create_slot(
            order_id=uuid.uuid4(),
            room_id="ROOM-TEST-OK",
            modality="MR",
            scheduled_start=start,
            scheduled_end=end,
        )
        handler_error_calls = [
            call
            for call in mock_logger.error.call_args_list
            if "event_bus.handler_error" in str(call.args)
        ]
        assert len(handler_error_calls) == 0


# ---------------------------------------------------------------------------
# GAP-R4-2: update_slot conflict detection
# ---------------------------------------------------------------------------


async def test_update_slot_to_overlap_raises_conflict(
    schedule_service: ScheduleService,
) -> None:
    """Updating a slot's time range to overlap an existing slot raises ScheduleConflictError."""
    # Slot A: hours 10–10:30
    start_a = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=10)
    end_a = start_a + timedelta(minutes=30)
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CONFLICT-1",
        modality="CT",
        scheduled_start=start_a,
        scheduled_end=end_a,
    )

    # Slot B: hours 11–11:30 (non-overlapping initially)
    start_b = start_a + timedelta(hours=1)
    end_b = start_b + timedelta(minutes=30)
    slot_b = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-CONFLICT-1",
        modality="CT",
        scheduled_start=start_b,
        scheduled_end=end_b,
    )

    # Now update slot_b to overlap with slot_a (10:15–10:45 overlaps 10:00–10:30)
    with pytest.raises(ScheduleConflictError):
        await schedule_service.update_slot(
            slot_b.id,
            scheduled_start=start_a + timedelta(minutes=15),
            scheduled_end=end_a + timedelta(minutes=15),
        )


async def test_update_slot_no_overlap_succeeds(
    schedule_service: ScheduleService,
) -> None:
    """Updating a slot's time range to a non-overlapping window does not raise."""
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=20)
    slot = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-UPDATE-OK",
        modality="MR",
        scheduled_start=base,
        scheduled_end=base + timedelta(minutes=30),
    )
    # Move to a completely different time — should succeed
    new_start = base + timedelta(hours=3)
    updated = await schedule_service.update_slot(
        slot.id,
        scheduled_start=new_start,
        scheduled_end=new_start + timedelta(minutes=30),
    )
    # SQLite strips timezone when reading back; compare naive datetimes
    updated_start = updated.scheduled_start
    if hasattr(updated_start, "tzinfo") and updated_start.tzinfo is not None:
        assert updated_start == new_start
    else:
        assert updated_start == new_start.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# GAP-R4-4: detect_conflicts and check_availability
# ---------------------------------------------------------------------------


async def test_detect_conflicts_returns_overlapping_slots(
    schedule_service: ScheduleService,
) -> None:
    """detect_conflicts returns all slots that overlap the given time window."""
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=30)
    # Create one slot in ROOM-DETECT at base to base+30
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-DETECT",
        modality="CT",
        scheduled_start=base,
        scheduled_end=base + timedelta(minutes=30),
    )

    # Query a window that overlaps (base+15 to base+45)
    conflicts = await schedule_service.detect_conflicts(
        room_id="ROOM-DETECT",
        start=base + timedelta(minutes=15),
        end=base + timedelta(minutes=45),
    )
    assert len(conflicts) == 1


async def test_detect_conflicts_non_overlapping_returns_empty(
    schedule_service: ScheduleService,
) -> None:
    """detect_conflicts returns empty list when no slots overlap the window."""
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=35)
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-DETECT-EMPTY",
        modality="MR",
        scheduled_start=base,
        scheduled_end=base + timedelta(minutes=30),
    )

    # Query a window entirely after the slot
    conflicts = await schedule_service.detect_conflicts(
        room_id="ROOM-DETECT-EMPTY",
        start=base + timedelta(hours=1),
        end=base + timedelta(hours=2),
    )
    assert conflicts == []


async def test_check_availability_returns_available_slots(
    schedule_service: ScheduleService,
) -> None:
    """check_availability returns only AVAILABLE slots matching the filter criteria."""
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=40)

    # Create two AVAILABLE CT slots
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-AVAIL-1",
        modality="CT",
        scheduled_start=base,
        scheduled_end=base + timedelta(minutes=30),
    )
    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-AVAIL-2",
        modality="CT",
        scheduled_start=base + timedelta(hours=1),
        scheduled_end=base + timedelta(hours=1, minutes=30),
    )

    available = await schedule_service.check_availability(modality="CT")
    # At least the two we just created must appear
    assert len(available) >= 2
    assert all(str(s.status) == "AVAILABLE" for s in available)


async def test_check_availability_filters_by_modality(
    schedule_service: ScheduleService,
) -> None:
    """check_availability with modality filter excludes slots of other modalities."""
    base = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=45)

    await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-MR-AVAIL",
        modality="MR",
        scheduled_start=base,
        scheduled_end=base + timedelta(minutes=30),
    )

    # Filter by a different modality — should not include the MR slot
    available = await schedule_service.check_availability(modality="NM")
    mr_ids = [s.id for s in available if s.modality == "MR"]
    assert mr_ids == []


# ---------------------------------------------------------------------------
# GAP-M1: ScheduleService.update_slot() — unknown field warning
# ---------------------------------------------------------------------------


async def test_update_slot_unknown_field_logs_warning(
    schedule_service: ScheduleService,
) -> None:
    """GAP-M1: Passing an unknown field to update_slot() logs a warning and does not crash."""
    from unittest.mock import patch

    start, end = _make_times(offset_hours=50)
    slot = await schedule_service.create_slot(
        order_id=uuid.uuid4(),
        room_id="ROOM-UNKNOWN-FIELD",
        modality="CT",
        scheduled_start=start,
        scheduled_end=end,
    )

    with patch("sautiris.services.schedule_service.logger") as mock_logger:
        updated = await schedule_service.update_slot(
            slot.id, nonexistent_schedule_field="should_be_ignored"
        )

    assert updated is not None  # no crash
    mock_logger.warning.assert_called()
    warning_key = mock_logger.warning.call_args[0][0]
    assert "unknown_fields" in warning_key


# ---------------------------------------------------------------------------
# R2-H5: ScheduleService._publish uses logger.error (not warning)
# ---------------------------------------------------------------------------


async def test_schedule_publish_handler_error_logged_at_error_level(
    db_session: AsyncSession,
) -> None:
    """ScheduleService._publish logs handler failures at ERROR level."""
    from unittest.mock import patch

    from sautiris.core.events import EventBus

    bus = EventBus()

    async def _failing_handler(event: object) -> None:
        raise ValueError("schedule notification down")

    bus.subscribe("schedule.slot_created", _failing_handler)
    svc = ScheduleService(db_session, event_bus=bus)

    start, end = _make_times(offset_hours=100)
    with patch("sautiris.services.schedule_service.logger") as mock_logger:
        await svc.create_slot(
            order_id=uuid.uuid4(),
            room_id="ROOM-PUBLISH-ERR",
            modality="CT",
            scheduled_start=start,
            scheduled_end=end,
        )
        # Must be logger.error, not logger.warning
        mock_logger.error.assert_called()
        error_key = mock_logger.error.call_args[0][0]
        assert "event_bus.handler_error" in error_key
