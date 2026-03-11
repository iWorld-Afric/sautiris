"""Shared service mixins for SautiRIS services."""

from __future__ import annotations

from typing import ClassVar

import structlog

from sautiris.core.events import DomainEvent, EventBus

logger = structlog.get_logger(__name__)


class EventPublisherMixin:
    """Mixin that provides a typed ``_publish()`` method for domain event emission.

    Services that inherit this mixin must assign ``_event_bus`` before calling
    ``_publish()``.  Each service should also declare its own
    ``_critical_event_types`` class variable to identify events whose handler
    failures should be logged at CRITICAL severity (patient-safety events).

    Usage::

        class MyService(EventPublisherMixin):
            _critical_event_types: ClassVar[tuple[type[DomainEvent], ...]] = (MyEvent,)

            def __init__(self, ..., event_bus: EventBus | None = None) -> None:
                self._event_bus = event_bus
    """

    # Subclasses override this to mark safety-critical event types.
    # Handler failures for these events will be logged at CRITICAL level.
    _critical_event_types: ClassVar[tuple[type[DomainEvent], ...]] = ()

    # Declared here for type-checking; concrete services assign in __init__.
    _event_bus: EventBus | None

    async def _publish(self, event: DomainEvent) -> None:
        """Publish a domain event if an event bus is configured.

        - All handler errors are logged at ERROR level.
        - If the event is an instance of any type in ``_critical_event_types``,
          handler failures are additionally logged at CRITICAL level.
        """
        if self._event_bus is not None:
            errors = await self._event_bus.publish(event)
            if errors:
                for exc in errors:
                    logger.error(
                        "event_bus.handler_error",
                        event_type=event.event_type,
                        error=str(exc),
                    )
                if self._critical_event_types and isinstance(
                    event, self._critical_event_types
                ):
                    logger.critical(
                        "event_bus.critical_event_handlers_failed",
                        event_type=event.event_type,
                        error_count=len(errors),
                    )
