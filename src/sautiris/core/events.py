"""Domain event bus for SautiRIS.

Provides a lightweight publish/subscribe event system for domain events
such as OrderCreated, ReportFinalized, CriticalFinding, etc.
Handlers are async callables that receive the event and can trigger
side effects like FHIR publishing, HL7v2 messaging, or webhooks.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger(__name__)

EventHandler = Callable[["DomainEvent"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


@dataclass
class DomainEvent:
    """Base domain event."""

    event_type: str
    payload: dict[str, Any]
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tenant_id: UUID | None = None


# ---------------------------------------------------------------------------
# Concrete radiology events
# ---------------------------------------------------------------------------


@dataclass
class OrderCreated(DomainEvent):
    """Emitted when a radiology order is created."""

    event_type: str = "order.created"
    payload: dict[str, Any] = field(default_factory=dict)

    # Typed convenience fields
    order_id: str = ""
    patient_id: str = ""
    modality: str = ""
    urgency: str = ""
    procedure_code: str = ""
    requesting_physician_id: str = ""


@dataclass
class OrderScheduled(DomainEvent):
    """Emitted when a radiology order is scheduled."""

    event_type: str = "order.scheduled"
    payload: dict[str, Any] = field(default_factory=dict)

    order_id: str = ""
    schedule_slot_id: str = ""
    scheduled_start: str = ""
    room_id: str = ""
    technologist_id: str = ""


@dataclass
class ExamStarted(DomainEvent):
    """Emitted when an exam begins (MPPS N-CREATE)."""

    event_type: str = "exam.started"
    payload: dict[str, Any] = field(default_factory=dict)

    order_id: str = ""
    worklist_item_id: str = ""
    mpps_uid: str = ""
    station_ae_title: str = ""


@dataclass
class ExamCompleted(DomainEvent):
    """Emitted when an exam finishes (MPPS N-SET completed)."""

    event_type: str = "exam.completed"
    payload: dict[str, Any] = field(default_factory=dict)

    order_id: str = ""
    worklist_item_id: str = ""
    mpps_uid: str = ""
    study_instance_uid: str = ""


@dataclass
class ReportFinalized(DomainEvent):
    """Emitted when a radiology report reaches FINAL status."""

    event_type: str = "report.finalized"
    payload: dict[str, Any] = field(default_factory=dict)

    order_id: str = ""
    report_id: str = ""
    accession_number: str = ""
    reported_by: str = ""
    is_critical: bool = False


@dataclass
class CriticalFinding(DomainEvent):
    """Emitted when a critical finding is identified."""

    event_type: str = "finding.critical"
    payload: dict[str, Any] = field(default_factory=dict)

    order_id: str = ""
    report_id: str = ""
    alert_id: str = ""
    finding_description: str = ""
    urgency: str = "IMMEDIATE"
    notified_physician_id: str = ""


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class EventBus:
    """In-process async event bus with pluggable handlers.

    Usage::

        bus = EventBus()
        bus.subscribe("order.created", my_handler)
        await bus.publish(OrderCreated(order_id="123", patient_id="456"))

    Handlers run concurrently via ``asyncio.gather``. A failing handler
    is logged but does not prevent other handlers from executing.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)
        logger.debug(
            "event_bus.subscribed",
            event_type=event_type,
            handler=getattr(handler, "__name__", repr(handler)),
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler for an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: DomainEvent) -> list[Exception]:
        """Publish an event to all subscribers.

        Returns a list of exceptions from handlers that failed. An empty list
        means all handlers succeeded.
        """
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            logger.debug("event_bus.no_handlers", event_type=event.event_type)
            return []

        logger.info(
            "event_bus.publishing",
            event_type=event.event_type,
            event_id=str(event.event_id),
            handler_count=len(handlers),
        )

        results = await asyncio.gather(
            *(self._safe_call(h, event) for h in handlers),
            return_exceptions=True,
        )

        errors: list[Exception] = [r for r in results if isinstance(r, Exception)]
        if errors:
            logger.warning(
                "event_bus.handler_errors",
                event_type=event.event_type,
                event_id=str(event.event_id),
                error_count=len(errors),
            )
        return errors

    @staticmethod
    async def _safe_call(handler: EventHandler, event: DomainEvent) -> None:
        """Invoke handler with structured error logging."""
        try:
            await handler(event)
        except Exception:
            logger.error(
                "event_bus.handler_failed",
                handler=getattr(handler, "__name__", repr(handler)),
                event_type=event.event_type,
                event_id=str(event.event_id),
                exc_info=True,
            )
            raise

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._handlers.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all event types."""
        return sum(len(h) for h in self._handlers.values())


# Module-level singleton
event_bus = EventBus()
