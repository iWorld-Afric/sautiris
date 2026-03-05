"""AlertService — critical result alerting, notification dispatch, escalation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.alert import AlertType, AlertUrgency, CriticalAlert, NotificationMethod
from sautiris.repositories.alert import AlertRepository

logger = structlog.get_logger(__name__)


class NotificationDispatcher(Protocol):
    """Pluggable notification dispatch protocol."""

    async def dispatch(
        self,
        *,
        method: str,
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
        method: str,
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


class AlertService:
    """Service for critical result alerting and escalation workflow."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        notification_dispatcher: NotificationDispatcher | None = None,
        escalation_timeout_minutes: int = DEFAULT_ESCALATION_TIMEOUT,
    ) -> None:
        self.session = session
        self.repo = AlertRepository(session)
        self.dispatcher = notification_dispatcher or LoggingNotificationDispatcher()
        self.escalation_timeout = escalation_timeout_minutes

    async def create_alert(
        self,
        *,
        order_id: uuid.UUID,
        report_id: uuid.UUID | None = None,
        alert_type: str = AlertType.CRITICAL_FINDING,
        finding_description: str | None = None,
        urgency: str = AlertUrgency.URGENT,
        notified_physician_id: uuid.UUID | None = None,
        notified_physician_name: str | None = None,
        notification_method: str = NotificationMethod.IN_APP,
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
        await self.dispatcher.dispatch(
            method=notification_method,
            recipient_id=notified_physician_id,
            recipient_name=notified_physician_name,
            message=message,
            alert_id=created.id,
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
        status: str | None = None,
        urgency: str | None = None,
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

        updated = await self.repo.escalate(alert)
        await self.session.commit()

        # Re-dispatch notification for escalation
        desc = alert.finding_description or "Critical finding requires attention"
        message = f"ESCALATED ALERT: {alert.alert_type} — {desc}"
        await self.dispatcher.dispatch(
            method=alert.notification_method or NotificationMethod.IN_APP,
            recipient_id=alert.notified_physician_id,
            recipient_name=alert.notified_physician_name,
            message=message,
            alert_id=alert_id,
        )

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
        """Check for alerts needing auto-escalation. Called by background worker."""
        cutoff = datetime.now(UTC) - timedelta(minutes=self.escalation_timeout)
        stale_alerts = await self.repo.get_unacknowledged_before(cutoff)

        escalated: list[CriticalAlert] = []
        for alert in stale_alerts:
            updated = await self.repo.escalate(alert)
            escalated.append(updated)

            message = (
                f"AUTO-ESCALATED: {alert.alert_type}"
                f" — unacknowledged for {self.escalation_timeout} minutes"
            )
            await self.dispatcher.dispatch(
                method=alert.notification_method or NotificationMethod.IN_APP,
                recipient_id=alert.notified_physician_id,
                recipient_name=alert.notified_physician_name,
                message=message,
                alert_id=alert.id,
            )

        if escalated:
            await self.session.commit()
            logger.warning(
                "auto_escalation_completed",
                escalated_count=len(escalated),
            )
        return escalated
