"""Worklist management service."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import ClassVar

import structlog
from pydicom.uid import generate_uid
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import (
    DomainEvent,
    EventBus,
    ExamCompleted,
    ExamStarted,
    WorklistMPPSReceived,
    WorklistStatusChanged,
)
from sautiris.models.worklist import MPPSStatus, WorklistItem, WorklistStatus
from sautiris.repositories.worklist import WorklistRepository
from sautiris.services.mixins import EventPublisherMixin

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


class WorklistService(EventPublisherMixin):
    _critical_event_types: ClassVar[tuple[type[DomainEvent], ...]] = (ExamCompleted, ExamStarted)

    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.repo = WorklistRepository(session)
        self._event_bus = event_bus

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
        scheduled_start: datetime | None = None,
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
            study_instance_uid=generate_uid(),
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
        status: WorklistStatus | None = None,
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
        current = item.status
        allowed = VALID_WL_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise InvalidWorklistTransitionError(
                f"Cannot transition from {current} to {new_status}"
            )
        old_status = item.status
        item.status = new_status
        updated = await self.repo.update(item)

        if new_status == WorklistStatus.IN_PROGRESS:
            await self._publish(
                ExamStarted(
                    order_id=str(updated.order_id),
                    worklist_item_id=str(updated.id),
                    tenant_id=updated.tenant_id,
                )
            )
        elif new_status == WorklistStatus.COMPLETED:
            await self._publish(
                ExamCompleted(
                    order_id=str(updated.order_id),
                    worklist_item_id=str(updated.id),
                    tenant_id=updated.tenant_id,
                )
            )
        else:
            await self._publish(
                WorklistStatusChanged(
                    item_id=str(updated.id),
                    order_id=str(updated.order_id),
                    from_status=str(old_status),
                    to_status=str(new_status),
                    tenant_id=updated.tenant_id,
                )
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
        mpps_status: MPPSStatus,
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
        await self._publish(
            WorklistMPPSReceived(
                item_id=str(updated.id),
                order_id=str(updated.order_id),
                mpps_status=str(mpps_status),
                mpps_uid=mpps_uid or "",
                tenant_id=updated.tenant_id,
            )
        )
        logger.info("mpps_received", item_id=str(item_id), mpps_status=mpps_status)
        return updated

    async def get_stats(self) -> dict[str, int]:
        return await self.repo.get_stats()


