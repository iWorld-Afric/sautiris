"""Worklist management service."""

from __future__ import annotations

import uuid
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, event_bus
from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.worklist import MPPSStatus, WorklistItem, WorklistStatus
from sautiris.repositories.worklist import WorklistRepository

logger = structlog.get_logger(__name__)

VALID_WL_TRANSITIONS: dict[WorklistStatus, set[WorklistStatus]] = {
    WorklistStatus.SCHEDULED: {WorklistStatus.IN_PROGRESS, WorklistStatus.DISCONTINUED},
    WorklistStatus.IN_PROGRESS: {WorklistStatus.COMPLETED, WorklistStatus.DISCONTINUED},
    WorklistStatus.COMPLETED: set(),
    WorklistStatus.DISCONTINUED: set(),
}


class WorklistItemNotFoundError(Exception):
    pass


class InvalidWorklistTransitionError(Exception):
    pass


class WorklistService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WorklistRepository(session)

    async def create_worklist_item(
        self,
        *,
        order_id: uuid.UUID,
        accession_number: str,
        patient_id: str,
        patient_name: str,
        modality: str,
        schedule_slot_id: uuid.UUID | None = None,
        patient_dob: date | None = None,
        patient_sex: str | None = None,
        scheduled_station_ae_title: str | None = None,
        scheduled_procedure_step_id: str | None = None,
        scheduled_procedure_step_description: str | None = None,
        scheduled_start: object | None = None,
        requested_procedure_id: str | None = None,
        requested_procedure_description: str | None = None,
        referring_physician_name: str | None = None,
    ) -> WorklistItem:
        item = WorklistItem(
            order_id=order_id,
            schedule_slot_id=schedule_slot_id,
            accession_number=accession_number,
            patient_id=patient_id,
            patient_name=patient_name,
            modality=modality,
            patient_dob=patient_dob,
            patient_sex=patient_sex,
            scheduled_station_ae_title=scheduled_station_ae_title,
            scheduled_procedure_step_id=scheduled_procedure_step_id,
            scheduled_procedure_step_description=scheduled_procedure_step_description,
            scheduled_start=scheduled_start,
            requested_procedure_id=requested_procedure_id,
            requested_procedure_description=requested_procedure_description,
            referring_physician_name=referring_physician_name,
            status=WorklistStatus.SCHEDULED,
        )
        created = await self.repo.create(item)
        logger.info("worklist_item_created", item_id=str(created.id))
        return created

    async def get_item(self, item_id: uuid.UUID) -> WorklistItem:
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise WorklistItemNotFoundError(f"Worklist item {item_id} not found")
        return item

    async def list_items(
        self,
        *,
        modality: str | None = None,
        status: str | None = None,
        scheduled_station_ae_title: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[WorklistItem], int]:
        offset = (page - 1) * page_size
        items, total = await self.repo.list_with_filters(
            modality=modality,
            status=status,
            scheduled_station_ae_title=scheduled_station_ae_title,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=page_size,
        )
        return list(items), total

    async def update_procedure_step_status(
        self,
        item_id: uuid.UUID,
        new_status: WorklistStatus,
    ) -> WorklistItem:
        item = await self.get_item(item_id)
        current = WorklistStatus(item.status)
        allowed = VALID_WL_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise InvalidWorklistTransitionError(
                f"Cannot transition from {current} to {new_status}"
            )
        old_status = item.status
        item.status = new_status
        updated = await self.repo.update(item)
        await self._emit(
            "worklist.status_changed",
            updated,
            extra={"from_status": old_status, "to_status": str(new_status)},
        )
        logger.info(
            "worklist_status_changed",
            item_id=str(item_id),
            new_status=new_status,
        )
        return updated

    async def receive_mpps(
        self,
        item_id: uuid.UUID,
        *,
        mpps_status: str,
        mpps_uid: str | None = None,
    ) -> WorklistItem:
        item = await self.get_item(item_id)
        item.mpps_status = mpps_status
        if mpps_uid:
            item.mpps_uid = mpps_uid

        if mpps_status == MPPSStatus.COMPLETED and item.status == WorklistStatus.IN_PROGRESS:
            item.status = WorklistStatus.COMPLETED
        elif mpps_status == MPPSStatus.DISCONTINUED and item.status in (
            WorklistStatus.SCHEDULED,
            WorklistStatus.IN_PROGRESS,
        ):
            item.status = WorklistStatus.DISCONTINUED

        updated = await self.repo.update(item)
        await self._emit(
            "worklist.mpps_received",
            updated,
            extra={"mpps_status": mpps_status, "mpps_uid": mpps_uid or ""},
        )
        logger.info("mpps_received", item_id=str(item_id), mpps_status=mpps_status)
        return updated

    async def get_stats(self) -> dict[str, int]:
        return await self.repo.get_stats()

    async def _emit(
        self,
        event_type: str,
        item: WorklistItem,
        *,
        extra: dict[str, str] | None = None,
    ) -> None:
        payload: dict[str, str] = {
            "item_id": str(item.id),
            "order_id": str(item.order_id),
            "status": str(item.status),
        }
        if extra:
            payload.update(extra)
        await event_bus.publish(
            DomainEvent(
                event_type=event_type,
                payload=payload,
                tenant_id=get_current_tenant_id(),
            )
        )
