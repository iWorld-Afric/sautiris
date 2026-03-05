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
