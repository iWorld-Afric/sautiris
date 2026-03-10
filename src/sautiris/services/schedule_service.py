"""Scheduling service with conflict detection."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import structlog
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, EventBus
from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.schedule import ScheduleSlot, SlotStatus
from sautiris.repositories.schedule import ScheduleRepository

logger = structlog.get_logger(__name__)

_SLOT_UPDATABLE_FIELDS = frozenset(
    {
        "room_id",
        "modality",
        "scheduled_start",
        "scheduled_end",
        "duration_minutes",
        "technologist_id",
        "technologist_name",
        "status",
        "notes",
        "order_id",
    }
)


class ScheduleConflictError(Exception):
    """Raised when a scheduling conflict is detected."""


class SlotNotFoundError(Exception):
    """Raised when a slot is not found."""


class SlotNotDeletableError(Exception):
    """Raised when trying to delete a non-AVAILABLE slot."""


class ScheduleService:
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.repo = ScheduleRepository(session)
        self._event_bus = event_bus

    async def _publish(self, event: DomainEvent) -> None:
        """Publish a domain event if an event bus is configured."""
        if self._event_bus is not None:
            errors = await self._event_bus.publish(event)
            if errors:
                for exc in errors:
                    logger.warning(
                        "event_bus.handler_error",
                        event_type=event.event_type,
                        error=str(exc),
                    )

    async def create_slot(
        self,
        *,
        order_id: uuid.UUID,
        room_id: str,
        modality: str,
        scheduled_start: datetime,
        scheduled_end: datetime,
        duration_minutes: int = 30,
        technologist_id: uuid.UUID | None = None,
        technologist_name: str | None = None,
        status: SlotStatus = SlotStatus.AVAILABLE,
        notes: str | None = None,
    ) -> ScheduleSlot:
        conflicts = await self.repo.find_conflicts(
            room_id=room_id,
            technologist_id=technologist_id,
            start=scheduled_start,
            end=scheduled_end,
        )
        if conflicts:
            conflict_ids = [str(c.id) for c in conflicts]
            raise ScheduleConflictError(
                f"Scheduling conflict with slot(s): {', '.join(conflict_ids)}"
            )

        slot = ScheduleSlot(
            order_id=order_id,
            room_id=room_id,
            modality=modality,
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            duration_minutes=duration_minutes,
            technologist_id=technologist_id,
            technologist_name=technologist_name,
            status=status,
            notes=notes,
        )
        created = await self.repo.create(slot)
        await self._emit("schedule.slot_created", created)
        logger.info("slot_created", slot_id=str(created.id), room=room_id)
        return created

    async def get_slot(self, slot_id: uuid.UUID) -> ScheduleSlot:
        slot = await self.repo.get_by_id(slot_id)
        if slot is None:
            raise SlotNotFoundError(f"Slot {slot_id} not found")
        return slot

    async def update_slot(
        self,
        slot_id: uuid.UUID,
        **updates: object,
    ) -> ScheduleSlot:
        slot = await self.get_slot(slot_id)

        new_start = updates.get("scheduled_start", slot.scheduled_start)
        new_end = updates.get("scheduled_end", slot.scheduled_end)
        new_room = updates.get("room_id", slot.room_id)
        new_tech = updates.get("technologist_id", slot.technologist_id)

        conflicts = await self.repo.find_conflicts(
            room_id=str(new_room) if new_room else None,
            technologist_id=new_tech if isinstance(new_tech, uuid.UUID) else None,
            start=new_start if isinstance(new_start, datetime) else slot.scheduled_start,
            end=new_end if isinstance(new_end, datetime) else slot.scheduled_end,
            exclude_id=slot_id,
        )
        if conflicts:
            raise ScheduleConflictError("Update would cause scheduling conflict")

        known_fields = {c.key for c in inspect(ScheduleSlot).mapper.column_attrs}
        unknown = set(updates.keys()) - known_fields
        if unknown:
            logger.warning("update.unknown_fields", fields=unknown, model="ScheduleSlot")
        for key, value in updates.items():
            if key in _SLOT_UPDATABLE_FIELDS:
                setattr(slot, key, value)
            elif key in known_fields:
                logger.warning("update.non_updatable_field", field=key, model="ScheduleSlot")
        updated = await self.repo.update(slot)
        await self._emit("schedule.slot_updated", updated)
        return updated

    async def delete_slot(self, slot_id: uuid.UUID) -> None:
        slot = await self.get_slot(slot_id)
        if slot.status not in (SlotStatus.AVAILABLE, SlotStatus.CANCELLED):
            raise SlotNotDeletableError(f"Cannot delete slot in {slot.status} status")
        await self.repo.delete(slot)
        logger.info("slot_deleted", slot_id=str(slot_id))

    async def list_slots(
        self,
        *,
        room_id: str | None = None,
        modality: str | None = None,
        technologist_id: uuid.UUID | None = None,
        status: SlotStatus | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[ScheduleSlot], int]:
        offset = (page - 1) * page_size
        items, total = await self.repo.list_with_filters(
            room_id=room_id,
            modality=modality,
            technologist_id=technologist_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=page_size,
        )
        return list(items), total

    async def check_availability(
        self,
        *,
        modality: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ScheduleSlot]:
        items = await self.repo.get_availability(
            modality=modality,
            date_from=date_from,
            date_to=date_to,
        )
        return list(items)

    async def list_rooms(self) -> list[str]:
        rooms = await self.repo.list_rooms()
        return list(rooms)

    async def detect_conflicts(
        self,
        *,
        room_id: str | None = None,
        start: datetime,
        end: datetime,
    ) -> list[ScheduleSlot]:
        conflicts = await self.repo.find_conflicts(
            room_id=room_id,
            start=start,
            end=end,
        )
        return list(conflicts)

    async def _emit(self, event_type: str, slot: ScheduleSlot) -> None:
        await self._publish(
            DomainEvent(
                event_type=event_type,
                payload={
                    "slot_id": str(slot.id),
                    "order_id": str(slot.order_id),
                    "room_id": slot.room_id,
                    "status": slot.status,
                },
                tenant_id=get_current_tenant_id(),
            )
        )
