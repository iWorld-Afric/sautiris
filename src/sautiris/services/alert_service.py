"""AlertService — critical result alerting, notification dispatch, escalation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import CriticalFinding, DomainEvent, EventBus
from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.alert import AlertType, AlertUrgency, CriticalAlert, NotificationMethod
from sautiris.repositories.alert import AlertRepository
from sautiris.services.mixins import EventPublisherMixin

logger = structlog.get_logger(__name__)


class NotificationDispatcher(Protocol):
    """Pluggable notification dispatch protocol."""

    async def dispatch(
        self,
        *,
        method: NotificationMethod,
        recipient_id: uuid.UUID | None,
        recipient_name: str | None,
        message: str,
        alert_id: uuid.UUID,
    ) -> None: ...


class LoggingNotificationDispatcher:
    """Default dispatcher that logs notifications (no-op for production injection)."""

    async def dispatch(
        self,
        *,
        method: NotificationMethod,
        recipient_id: uuid.UUID | None,
        recipient_name: str | None,
        message: str,
        alert_id: uuid.UUID,
    ) -> None:
        logger.info(
            "notification_dispatched",
            method=method,
            recipient_id=str(recipient_id) if recipient_id else None,
            recipient_name=recipient_name,
            alert_id=str(alert_id),
        )


# Default escalation timeout (minutes)
DEFAULT_ESCALATION_TIMEOUT = 30


class AlertService(EventPublisherMixin):
    """Service for critical result alerting and escalation workflow."""

    _critical_event_types: ClassVar[tuple[type[DomainEvent], ...]] = (CriticalFinding,)

    def __init__(
        self,
        session: AsyncSession,
        *,
        event_bus: EventBus | None = None,
        notification_dispatcher: NotificationDispatcher | None = None,
        escalation_timeout_minutes: int = DEFAULT_ESCALATION_TIMEOUT,
    ) -> None:
        self.session = session
        self.repo = AlertRepository(session)
        self._event_bus = event_bus
        self.dispatcher = notification_dispatcher or LoggingNotificationDispatcher()
        self.escalation_timeout = escalation_timeout_minutes

    async def create_alert(
        self,
        *,
        order_id: uuid.UUID,
        report_id: uuid.UUID | None = None,
        alert_type: AlertType = AlertType.CRITICAL_FINDING,
        finding_description: str | None = None,
        urgency: AlertUrgency = AlertUrgency.URGENT,
        notified_physician_id: uuid.UUID | None = None,
        notified_physician_name: str | None = None,
        notification_method: NotificationMethod = NotificationMethod.IN_APP,
    ) -> CriticalAlert:
        """Create a critical alert and dispatch notification."""
        now = datetime.now(UTC)
        alert = CriticalAlert(
            tenant_id=get_current_tenant_id(),
            order_id=order_id,
            report_id=report_id,
            alert_type=alert_type,
            finding_description=finding_description,
            urgency=urgency,
            notified_physician_id=notified_physician_id,
            notified_physician_name=notified_physician_name,
            notification_method=notification_method,
            notified_at=now,
        )
        created = await self.repo.create(alert)
        await self.session.commit()

        # Dispatch notification
        message = (
            f"CRITICAL ALERT: {alert_type} — {finding_description or 'Critical finding detected'}"
        )
        try:
            await self.dispatcher.dispatch(
                method=notification_method,
                recipient_id=notified_physician_id,
                recipient_name=notified_physician_name,
                message=message,
                alert_id=created.id,
            )
        except Exception as exc:
            try:
                created.notification_failed = True
                created.notification_error = str(exc)[:500]
                await self.repo.update(created)
                await self.session.flush()
            except Exception:
                logger.critical(
                    "alert.notification_failure_persistence_failed",
                    alert_id=str(created.id),
                    exc_info=True,
                )
            logger.critical(
                "alert.notification_dispatch_failed",
                alert_id=str(created.id),
                method=notification_method,
                exc_info=True,
                msg=(
                    "Critical alert notification could not be dispatched"
                    " — manual follow-up required"
                ),
            )

        # Emit domain event for critical findings
        if alert_type == AlertType.CRITICAL_FINDING:
            await self._publish(
                CriticalFinding(
                    order_id=str(order_id),
                    report_id=str(report_id) if report_id else "",
                    alert_id=str(created.id),
                    finding_description=finding_description or "",
                    urgency=urgency.value,
                    notified_physician_id=(
                        str(notified_physician_id) if notified_physician_id else ""
                    ),
                    tenant_id=get_current_tenant_id(),
                )
            )

        logger.warning(
            "critical_alert_created",
            alert_id=str(created.id),
            alert_type=alert_type,
            urgency=urgency,
            order_id=str(order_id),
        )
        return created

    async def list_alerts(
        self,
        *,
        status: Literal["PENDING", "ACKNOWLEDGED", "ESCALATED"] | None = None,
        urgency: AlertUrgency | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CriticalAlert]:
        """List alerts with optional filtering."""
        results = await self.repo.list_filtered(
            status=status, urgency=urgency, offset=offset, limit=limit
        )
        return list(results)

    async def acknowledge_alert(
        self,
        alert_id: uuid.UUID,
        *,
        user_id: uuid.UUID,
    ) -> CriticalAlert:
        """Acknowledge a critical alert."""
        alert = await self.repo.get_by_id(alert_id)
        if alert is None:
            raise ValueError(f"Alert {alert_id} not found")
        if alert.acknowledged_at is not None:
            raise ValueError(f"Alert {alert_id} already acknowledged")

        updated = await self.repo.acknowledge(alert, user_id=user_id)
        await self.session.commit()

        logger.info(
            "alert_acknowledged",
            alert_id=str(alert_id),
            acknowledged_by=str(user_id),
            order_id=str(alert.order_id),
            alert_type=str(alert.alert_type),
        )
        return updated

    async def escalate_alert(
        self,
        alert_id: uuid.UUID,
    ) -> CriticalAlert:
        """Escalate an unacknowledged alert."""
        alert = await self.repo.get_by_id(alert_id)
        if alert is None:
            raise ValueError(f"Alert {alert_id} not found")
        if alert.escalated:
            raise ValueError(f"Alert {alert_id} already escalated")

        # Attempt notification BEFORE committing escalation status.
        # If dispatch fails, do NOT mark as escalated — leave for retry (#43).
        desc = alert.finding_description or "Critical finding requires attention"
        message = f"ESCALATED ALERT: {alert.alert_type} — {desc}"
        dispatch_failed = False
        dispatch_error: str = ""
        try:
            await self.dispatcher.dispatch(
                method=alert.notification_method or NotificationMethod.IN_APP,
                recipient_id=alert.notified_physician_id,
                recipient_name=alert.notified_physician_name,
                message=message,
                alert_id=alert_id,
            )
        except Exception as exc:
            dispatch_failed = True
            dispatch_error = str(exc)
            logger.critical(
                "alert.notification_dispatch_failed",
                alert_id=str(alert_id),
                method=alert.notification_method or NotificationMethod.IN_APP,
                exc_info=True,
                msg=(
                    "Critical alert notification could not be dispatched"
                    " — manual follow-up required"
                ),
            )

        if dispatch_failed:
            # Track that notification failed; do not mark escalated (#43)
            alert.notification_failed = True
            alert.notification_error = dispatch_error
            await self.repo.update(alert)
            await self.session.commit()
            logger.warning(
                "alert_escalation_notification_failed",
                alert_id=str(alert_id),
            )
            return alert

        updated = await self.repo.escalate(alert)
        await self.session.commit()

        logger.warning(
            "alert_escalated",
            alert_id=str(alert_id),
        )
        return updated

    async def get_stats(self) -> dict[str, Any]:
        """Get alert statistics."""
        counts = await self.repo.count_by_status()
        avg_ack_time = await self.repo.avg_acknowledgment_time_minutes()

        escalation_rate = 0.0
        if counts["total"] > 0:
            escalation_rate = counts["escalated"] / counts["total"] * 100.0

        return {
            **counts,
            "avg_acknowledgment_time_minutes": round(avg_ack_time, 2),
            "escalation_rate": round(escalation_rate, 2),
        }

    async def check_escalation(self) -> list[CriticalAlert]:
        """Check for alerts needing auto-escalation. Called by background worker.

        Candidates are unacknowledged alerts that either:
        - have been pending longer than the escalation timeout, or
        - previously had a notification failure and need re-notification (#44).
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=self.escalation_timeout)
        stale_alerts = await self.repo.get_unacknowledged_before(cutoff)

        # Also include alerts that had notification failures — they need retry (#44).
        # Query inline since this is a service-level concern, not a repo concern.
        failed_stmt = select(CriticalAlert).where(
            CriticalAlert.tenant_id == get_current_tenant_id(),
            CriticalAlert.notification_failed.is_(True),
            CriticalAlert.acknowledged_at.is_(None),
        )
        failed_result = await self.session.execute(failed_stmt)
        failed_alerts: Sequence[CriticalAlert] = failed_result.scalars().all()
        # Merge, deduplicating by id
        seen_ids: set[uuid.UUID] = {a.id for a in stale_alerts}
        candidates = list(stale_alerts)
        for alert in failed_alerts:
            if alert.id not in seen_ids:
                candidates.append(alert)
                seen_ids.add(alert.id)

        escalated: list[CriticalAlert] = []
        any_modified = False
        for alert in candidates:
            try:
                updated = await self.repo.escalate(alert)
            except Exception:
                logger.error(
                    "alert.escalation_failed",
                    alert_id=str(alert.id),
                    exc_info=True,
                )
                continue

            message = (
                f"AUTO-ESCALATED: {alert.alert_type}"
                f" — unacknowledged for {self.escalation_timeout} minutes"
            )
            dispatch_failed = False
            dispatch_error: str = ""
            try:
                await self.dispatcher.dispatch(
                    method=alert.notification_method or NotificationMethod.IN_APP,
                    recipient_id=alert.notified_physician_id,
                    recipient_name=alert.notified_physician_name,
                    message=message,
                    alert_id=alert.id,
                )
                # Dispatch succeeded — clear any prior failure flag
                updated.notification_failed = False
                updated.notification_error = None
            except Exception as exc:
                dispatch_failed = True
                dispatch_error = str(exc)[:500]
                updated.notification_failed = True
                updated.notification_error = dispatch_error
                any_modified = True
                logger.critical(
                    "alert.notification_dispatch_failed",
                    alert_id=str(alert.id),
                    method=alert.notification_method or NotificationMethod.IN_APP,
                    exc_info=True,
                    msg=(
                        "Critical alert notification could not be dispatched"
                        " — manual follow-up required"
                    ),
                )

            if not dispatch_failed:
                escalated.append(updated)

        if escalated or any_modified:
            try:
                await self.session.commit()
            except Exception:
                logger.critical(
                    "alert.escalation_commit_failed",
                    escalated_count=len(escalated),
                    exc_info=True,
                    msg="Failed to persist auto-escalation records — manual follow-up required",
                )
                return []
            if escalated:
                logger.warning(
                    "auto_escalation_completed",
                    escalated_count=len(escalated),
                )
        return escalated
