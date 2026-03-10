"""Order lifecycle management service."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.accession import generate_accession_number, peek_next_accession_number
from sautiris.core.events import (
    DomainEvent,
    EventBus,
    ExamCompleted,
    ExamStarted,
    OrderCreated,
    OrderScheduled,
)
from sautiris.core.tenancy import get_current_tenant_id as _get_tenant
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
    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.repo = OrderRepository(session)
        self._event_bus = event_bus

    async def _publish(self, event: DomainEvent) -> None:
        """Publish a domain event if an event bus is configured."""
        if self._event_bus is not None:
            errors = await self._event_bus.publish(event)
            if errors:
                for exc in errors:
                    logger.error(
                        "event_bus.handler_error",
                        event_type=event.event_type,
                        error=str(exc),
                    )
                if isinstance(event, (ExamCompleted, ExamStarted)):
                    logger.critical(
                        "event_bus.workflow_event_handlers_failed",
                        event_type=event.event_type,
                        error_count=len(errors),
                        msg=(
                            "Workflow-critical event handlers failed — exam state change"
                            " may not have been delivered"
                        ),
                    )

    async def create_order(
        self,
        *,
        patient_id: uuid.UUID,
        modality: str,
        urgency: Urgency = Urgency.ROUTINE,
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
        tenant_id = _get_tenant()
        accession = await generate_accession_number(self.session, tenant_id, modality)
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
        created = await self.repo.create(order)
        await self._publish(
            OrderCreated(
                order_id=str(created.id),
                patient_id=str(patient_id),
                modality=modality,
                urgency=urgency,
                procedure_code=procedure_code or "",
                requesting_physician_id=(
                    str(requesting_physician_id) if requesting_physician_id else ""
                ),
                tenant_id=created.tenant_id,
            )
        )
        logger.info(
            "order_created",
            order_id=str(created.id),
            modality=modality,
            accession_number=accession,
        )
        return created

    async def get_order(self, order_id: uuid.UUID) -> RadiologyOrder:
        order = await self.repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"Order {order_id} not found")
        return order

    async def list_orders(
        self,
        *,
        modality: str | None = None,
        status: OrderStatus | None = None,
        urgency: Urgency | None = None,
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
        current_status = order.status
        if current_status not in (OrderStatus.REQUESTED, OrderStatus.SCHEDULED):
            raise InvalidTransitionError(f"Cannot update order in {current_status} status")
        known_fields = {c.key for c in inspect(RadiologyOrder).mapper.column_attrs}
        unknown = set(updates.keys()) - known_fields
        if unknown:
            logger.warning("update.unknown_fields", fields=unknown, model="RadiologyOrder")
        for key, value in updates.items():
            if key in _ORDER_UPDATABLE_FIELDS:
                setattr(order, key, value)
            elif key in known_fields:
                logger.warning("update.non_updatable_field", field=key, model="RadiologyOrder")
        return await self.repo.update(order)

    async def _transition(
        self,
        order: RadiologyOrder,
        target: OrderStatus,
    ) -> RadiologyOrder:
        current = order.status
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise InvalidTransitionError(f"Cannot transition from {current} to {target}")
        old_status = order.status
        order.status = target
        updated = await self.repo.update(order)

        # Emit typed event matching the target status
        if target == OrderStatus.SCHEDULED:
            await self._publish(
                OrderScheduled(
                    order_id=str(updated.id),
                    tenant_id=updated.tenant_id,
                )
            )
        elif target == OrderStatus.IN_PROGRESS:
            await self._publish(
                ExamStarted(
                    order_id=str(updated.id),
                    tenant_id=updated.tenant_id,
                )
            )
        elif target == OrderStatus.COMPLETED:
            await self._publish(
                ExamCompleted(
                    order_id=str(updated.id),
                    tenant_id=updated.tenant_id,
                )
            )
        else:
            # Generic fallback for other transitions (cancelled, reported, etc.)
            await self._publish(
                DomainEvent(
                    event_type="order.status_changed",
                    payload={
                        "order_id": str(updated.id),
                        "from_status": old_status,
                        "to_status": target.value,
                    },
                    tenant_id=updated.tenant_id,
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
        """Generate (and consume) a real accession number — use only when creating an order."""
        tenant_id = _get_tenant()
        return await generate_accession_number(self.session, tenant_id, modality)

    async def peek_next_accession(self, modality: str) -> str:
        """Peek at what the next accession number would be WITHOUT incrementing.

        For display/preview purposes only.  Does not reserve a sequence number.
        """
        tenant_id = _get_tenant()
        return await peek_next_accession_number(self.session, tenant_id, modality)
