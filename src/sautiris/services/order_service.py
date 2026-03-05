"""Order lifecycle management service."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, event_bus
from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.order import OrderStatus, RadiologyOrder, Urgency
from sautiris.repositories.order import OrderRepository

logger = structlog.get_logger(__name__)

_ORDER_UPDATABLE_FIELDS = frozenset(
    {
        "modality",
        "urgency",
        "body_part",
        "laterality",
        "procedure_code",
        "procedure_description",
        "clinical_indication",
        "patient_history",
        "requesting_physician_id",
        "requesting_physician_name",
        "encounter_id",
        "special_instructions",
        "transport_mode",
        "isolation_precautions",
        "pregnant",
    }
)

VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.REQUESTED: {OrderStatus.SCHEDULED, OrderStatus.CANCELLED},
    OrderStatus.SCHEDULED: {OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED},
    OrderStatus.IN_PROGRESS: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: {OrderStatus.REPORTED, OrderStatus.CANCELLED},
    OrderStatus.REPORTED: {OrderStatus.VERIFIED},
    OrderStatus.VERIFIED: {OrderStatus.DISTRIBUTED},
    OrderStatus.DISTRIBUTED: set(),
    OrderStatus.CANCELLED: set(),
}


class InvalidTransitionError(Exception):
    """Raised when an invalid status transition is attempted."""


class OrderNotFoundError(Exception):
    """Raised when an order is not found."""


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OrderRepository(session)

    async def create_order(
        self,
        *,
        patient_id: uuid.UUID,
        modality: str,
        urgency: str = Urgency.ROUTINE,
        body_part: str | None = None,
        laterality: str | None = None,
        procedure_code: str | None = None,
        procedure_description: str | None = None,
        clinical_indication: str | None = None,
        patient_history: str | None = None,
        requesting_physician_id: uuid.UUID | None = None,
        requesting_physician_name: str | None = None,
        encounter_id: uuid.UUID | None = None,
        special_instructions: str | None = None,
        transport_mode: str | None = None,
        isolation_precautions: str | None = None,
        pregnant: bool | None = None,
    ) -> RadiologyOrder:
        from sqlalchemy.exc import IntegrityError as _IntegrityError

        max_retries = 3
        now = datetime.now(UTC)
        date_prefix = now.strftime("%Y%m%d")

        for attempt in range(max_retries):
            accession = await self.repo.get_next_accession_number(modality, date_prefix)
            order = RadiologyOrder(
                patient_id=patient_id,
                modality=modality,
                urgency=urgency,
                accession_number=accession,
                status=OrderStatus.REQUESTED,
                body_part=body_part,
                laterality=laterality,
                procedure_code=procedure_code,
                procedure_description=procedure_description,
                clinical_indication=clinical_indication,
                patient_history=patient_history,
                requesting_physician_id=requesting_physician_id,
                requesting_physician_name=requesting_physician_name,
                encounter_id=encounter_id,
                special_instructions=special_instructions,
                transport_mode=transport_mode,
                isolation_precautions=isolation_precautions,
                pregnant=pregnant,
            )
            try:
                created = await self.repo.create(order)
            except _IntegrityError:
                if attempt == max_retries - 1:
                    raise
                await self.session.rollback()
                logger.warning(
                    "accession_collision_retry",
                    accession=accession,
                    attempt=attempt + 1,
                )
                continue
            logger.info(
                "order_created",
                order_id=str(created.id),
                modality=modality,
            )
            return created
        raise RuntimeError("Unreachable: accession retry exhausted")

    async def get_order(self, order_id: uuid.UUID) -> RadiologyOrder:
        order = await self.repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} not found")
        return order

    async def list_orders(
        self,
        *,
        modality: str | None = None,
        status: str | None = None,
        urgency: str | None = None,
        patient_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[RadiologyOrder], int]:
        offset = (page - 1) * page_size
        items, total = await self.repo.list_with_filters(
            modality=modality,
            status=status,
            urgency=urgency,
            patient_id=patient_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=page_size,
        )
        return list(items), total

    async def update_order(
        self,
        order_id: uuid.UUID,
        **updates: object,
    ) -> RadiologyOrder:
        order = await self.get_order(order_id)
        current_status = OrderStatus(order.status)
        if current_status not in (OrderStatus.REQUESTED, OrderStatus.SCHEDULED):
            raise InvalidTransitionError(f"Cannot update order in {current_status} status")
        for key, value in updates.items():
            if key in _ORDER_UPDATABLE_FIELDS:
                setattr(order, key, value)
        return await self.repo.update(order)

    async def _transition(
        self,
        order: RadiologyOrder,
        target: OrderStatus,
    ) -> RadiologyOrder:
        current = OrderStatus(order.status)
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(f"Cannot transition from {current} to {target}")
        old_status = order.status
        order.status = target.value
        updated = await self.repo.update(order)

        await event_bus.publish(
            DomainEvent(
                event_type="order.status_changed",
                payload={
                    "order_id": str(updated.id),
                    "from_status": old_status,
                    "to_status": target.value,
                },
                tenant_id=get_current_tenant_id(),
            )
        )
        logger.info(
            "order_transition",
            order_id=str(updated.id),
            from_status=old_status,
            to_status=target.value,
        )
        return updated

    async def cancel_order(self, order_id: uuid.UUID, *, reason: str) -> RadiologyOrder:
        order = await self.get_order(order_id)
        result = await self._transition(order, OrderStatus.CANCELLED)
        result.special_instructions = (
            f"{result.special_instructions or ''}\nCANCELLED: {reason}".strip()
        )
        await self.repo.update(result)
        return result

    async def schedule_order(self, order_id: uuid.UUID, scheduled_at: datetime) -> RadiologyOrder:
        order = await self.get_order(order_id)
        result = await self._transition(order, OrderStatus.SCHEDULED)
        result.scheduled_at = scheduled_at
        return await self.repo.update(result)

    async def start_exam(self, order_id: uuid.UUID) -> RadiologyOrder:
        order = await self.get_order(order_id)
        result = await self._transition(order, OrderStatus.IN_PROGRESS)
        result.started_at = datetime.now(UTC)
        return await self.repo.update(result)

    async def complete_exam(self, order_id: uuid.UUID) -> RadiologyOrder:
        order = await self.get_order(order_id)
        result = await self._transition(order, OrderStatus.COMPLETED)
        result.completed_at = datetime.now(UTC)
        return await self.repo.update(result)

    async def get_order_stats(self) -> dict[str, int]:
        return await self.repo.get_order_stats()

    async def get_next_accession(self, modality: str) -> str:
        now = datetime.now(UTC)
        date_prefix = now.strftime("%Y%m%d")
        return await self.repo.get_next_accession_number(modality, date_prefix)
