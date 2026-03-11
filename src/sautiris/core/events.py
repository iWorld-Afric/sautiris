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

# MEDIUM-13: EventHandler uses base DomainEvent intentionally — the subscriber
# registry must accept any domain event. Handlers narrow the type themselves.
EventHandler = Callable[["DomainEvent"], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------


@dataclass
class DomainEvent:
    """Base domain event.

    ``event_type`` and ``payload`` are required on the base class so that
    ``DomainEvent(event_type="...", payload={...})`` still works for ad-hoc
    events.  Concrete subclasses override ``event_type`` with
    ``field(init=False)`` so callers cannot accidentally override the type
    string (HIGH-5).

    ``payload`` is a convenience dict for legacy consumers; typed subclasses
    carry their data in dedicated fields instead.  Both exist to avoid a dual
    source-of-truth: populate ``payload`` explicitly if you need it
    (MEDIUM-11).
    """

    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tenant_id: UUID | None = None


# ---------------------------------------------------------------------------
# Concrete radiology events
# ---------------------------------------------------------------------------


@dataclass
class OrderCreated(DomainEvent):
    """Emitted when a radiology order is created.

    Semantically mandatory: order_id, patient_id.  Cannot enforce via required
    fields due to Python dataclass ordering constraints with inherited defaults
    (HIGH-6 deferred — requires test refactoring).
    """

    # HIGH-5: init=False prevents callers from overriding the event type string
    event_type: str = field(init=False, default="order.created")

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

    event_type: str = field(init=False, default="order.scheduled")  # HIGH-5

    order_id: str = ""
    schedule_slot_id: str = ""
    scheduled_start: str = ""
    room_id: str = ""
    technologist_id: str = ""


@dataclass
class ExamStarted(DomainEvent):
    """Emitted when an exam begins (MPPS N-CREATE)."""

    event_type: str = field(init=False, default="exam.started")  # HIGH-5

    order_id: str = ""
    worklist_item_id: str = ""
    mpps_uid: str = ""
    station_ae_title: str = ""


@dataclass
class ExamCompleted(DomainEvent):
    """Emitted when an exam finishes (MPPS N-SET completed)."""

    event_type: str = field(init=False, default="exam.completed")  # HIGH-5

    order_id: str = ""
    worklist_item_id: str = ""
    mpps_uid: str = ""
    study_instance_uid: str = ""


@dataclass
class ReportFinalized(DomainEvent):
    """Emitted when a radiology report reaches FINAL status."""

    event_type: str = field(init=False, default="report.finalized")  # HIGH-5

    order_id: str = ""
    report_id: str = ""
    accession_number: str = ""
    reported_by: str = ""
    is_critical: bool = False


@dataclass
class CriticalFinding(DomainEvent):
    """Emitted when a critical finding is identified."""

    event_type: str = field(init=False, default="finding.critical")  # HIGH-5

    order_id: str = ""
    report_id: str = ""
    alert_id: str = ""
    finding_description: str = ""
    urgency: str = "IMMEDIATE"
    notified_physician_id: str = ""

    def __post_init__(self) -> None:
        if not self.order_id:
            raise ValueError("order_id is required for CriticalFinding")


@dataclass
class DRLExceeded(DomainEvent):
    """Emitted when a dose record exceeds Diagnostic Reference Level thresholds."""

    event_type: str = field(init=False, default="dose.drl_exceeded")  # HIGH-5

    order_id: str = ""
    dose_record_id: str = ""
    modality: str = ""
    body_part: str | None = None
    ctdi_vol: float | None = None
    dlp: float | None = None
    dap: float | None = None
    entrance_dose: float | None = None


@dataclass
class AIFindingCreated(DomainEvent):
    """Emitted when an AI model creates a new finding on a study."""

    event_type: str = field(init=False, default="ai.finding_created")  # HIGH-5

    order_id: str = ""
    study_instance_uid: str = ""
    finding_type: str = ""
    # MEDIUM-12: None means confidence not reported; 0.0 was ambiguous with
    # "zero confidence" vs "not available".
    confidence: float | None = None
    finding_id: str = ""
    ai_provider: str = ""


# ---------------------------------------------------------------------------
# Order lifecycle events (Issue #16)
# ---------------------------------------------------------------------------


@dataclass
class OrderCancelled(DomainEvent):
    """Emitted when a radiology order is cancelled."""

    event_type: str = field(init=False, default="order.cancelled")

    order_id: str = ""
    from_status: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.order_id:
            raise ValueError("order_id is required for OrderCancelled")


@dataclass
class OrderReported(DomainEvent):
    """Emitted when a radiology order transitions to REPORTED status."""

    event_type: str = field(init=False, default="order.reported")

    order_id: str = ""
    from_status: str = ""


@dataclass
class OrderVerified(DomainEvent):
    """Emitted when a radiology order transitions to VERIFIED status."""

    event_type: str = field(init=False, default="order.verified")

    order_id: str = ""
    from_status: str = ""


@dataclass
class OrderDistributed(DomainEvent):
    """Emitted when a radiology order transitions to DISTRIBUTED status."""

    event_type: str = field(init=False, default="order.distributed")

    order_id: str = ""
    from_status: str = ""


# ---------------------------------------------------------------------------
# Report lifecycle events (Issue #16)
# ---------------------------------------------------------------------------


@dataclass
class ReportCreated(DomainEvent):
    """Emitted when a radiology report is created."""

    event_type: str = field(init=False, default="report.created")

    report_id: str = ""
    order_id: str = ""
    accession_number: str = ""
    reported_by: str = ""


@dataclass
class ReportAmended(DomainEvent):
    """Emitted when a radiology report is amended."""

    event_type: str = field(init=False, default="report.amended")

    report_id: str = ""
    order_id: str = ""
    accession_number: str = ""
    changed_by: str = ""


# ---------------------------------------------------------------------------
# Worklist lifecycle events (Issue #16)
# ---------------------------------------------------------------------------


@dataclass
class WorklistStatusChanged(DomainEvent):
    """Emitted when a worklist item status changes (e.g. DISCONTINUED)."""

    event_type: str = field(init=False, default="worklist.status_changed")

    item_id: str = ""
    order_id: str = ""
    from_status: str = ""
    to_status: str = ""


@dataclass
class WorklistMPPSReceived(DomainEvent):
    """Emitted when an MPPS message is received for a worklist item."""

    event_type: str = field(init=False, default="worklist.mpps_received")

    item_id: str = ""
    order_id: str = ""
    mpps_status: str = ""
    mpps_uid: str = ""


# ---------------------------------------------------------------------------
# Schedule lifecycle events (Issue #16)
# ---------------------------------------------------------------------------


@dataclass
class ScheduleSlotCreated(DomainEvent):
    """Emitted when a schedule slot is first created.

    Semantically distinct from ScheduleSlotUpdated: subscribers that care about
    *new* slot availability (e.g. patient-booking notification, capacity dashboards)
    should listen for this event.  Downstream consumers that track any change to an
    existing slot subscribe to ScheduleSlotUpdated instead.
    """

    event_type: str = field(init=False, default="schedule.slot_created")

    slot_id: str = ""
    order_id: str = ""
    room_id: str = ""
    modality: str = ""
    status: str = ""


@dataclass
class ScheduleSlotUpdated(DomainEvent):
    """Emitted when an existing schedule slot is modified.

    Semantically distinct from ScheduleSlotCreated: subscribers that audit slot
    changes (e.g. conflict monitors, calendar sync, audit trails) subscribe here.
    The slot already exists; this event signals a *modification*, not creation.
    """

    event_type: str = field(init=False, default="schedule.slot_updated")

    slot_id: str = ""
    order_id: str = ""
    room_id: str = ""
    modality: str = ""
    status: str = ""


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
        # Tracks which handlers are marked critical (bubbles exceptions on failure)
        self._critical: set[EventHandler] = set()

    def subscribe(
        self, event_type: str, handler: EventHandler, *, is_critical: bool = False
    ) -> None:
        """Register a handler for an event type.

        Args:
            event_type: The event type string to listen for.
            handler: Async callable that receives the event.
            is_critical: If True, any exception raised by this handler will
                propagate out of ``publish()``.  Non-critical handler failures
                are logged and accumulated in the return value only.
        """
        self._handlers[event_type].append(handler)
        if is_critical:
            self._critical.add(handler)
        logger.debug(
            "event_bus.subscribed",
            event_type=event_type,
            handler=getattr(handler, "__name__", repr(handler)),
            is_critical=is_critical,
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a handler for an event type."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
        self._critical.discard(handler)

    async def publish(self, event: DomainEvent) -> list[Exception]:
        """Publish an event to all subscribers.

        Fan-out is always attempted for ALL handlers regardless of failures.
        Critical handlers (registered with ``is_critical=True``) re-raise
        their exception after fan-out completes.  Non-critical handler
        exceptions are accumulated and returned.

        Returns:
            List of exceptions from non-critical handlers that failed.
            An empty list means all handlers succeeded.

        Raises:
            The first exception from a *critical* handler (after full fan-out).
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

        # #34: Call handlers directly — _safe_call was a no-op try/except/re-raise.
        # asyncio.gather(return_exceptions=True) already captures exceptions without
        # the intermediate wrapper.
        results = await asyncio.gather(
            *(h(event) for h in handlers),
            return_exceptions=True,
        )

        errors: list[Exception] = []
        critical_error: Exception | None = None

        for handler, result in zip(handlers, results, strict=True):
            if isinstance(result, Exception):
                if handler in self._critical and critical_error is None:
                    critical_error = result
                else:
                    errors.append(result)

        if errors:
            logger.warning(
                "event_bus.handler_errors",
                event_type=event.event_type,
                event_id=str(event.event_id),
                error_count=len(errors),
            )

        if critical_error is not None:
            raise critical_error

        return errors

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._handlers.clear()
        self._critical.clear()

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers across all event types."""
        return sum(len(h) for h in self._handlers.values())
