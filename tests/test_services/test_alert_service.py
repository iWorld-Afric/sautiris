"""Tests for AlertService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import CriticalFinding, EventBus
from sautiris.models.alert import AlertType, AlertUrgency, CriticalAlert, NotificationMethod
from sautiris.services.alert_service import AlertService
from tests.conftest import TEST_USER_ID, make_order


@pytest.fixture
async def order(db_session: AsyncSession) -> CriticalAlert:
    """Create a test order."""
    order = make_order(db_session)
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)
    return order


@pytest.fixture
def alert_service(db_session: AsyncSession) -> AlertService:
    return AlertService(db_session, escalation_timeout_minutes=30)


class TestCreateAlert:
    async def test_create_alert_basic(
        self, alert_service: AlertService, order: object, db_session: AsyncSession
    ) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
            finding_description="Pneumothorax detected",
            urgency=AlertUrgency.IMMEDIATE,
        )
        assert alert.id is not None
        assert alert.order_id == order.id  # type: ignore[union-attr]
        assert alert.alert_type == AlertType.CRITICAL_FINDING
        assert alert.finding_description == "Pneumothorax detected"
        assert alert.urgency == AlertUrgency.IMMEDIATE
        assert alert.notified_at is not None
        assert alert.acknowledged_at is None
        assert alert.escalated is False

    async def test_create_alert_with_physician(
        self, alert_service: AlertService, order: object
    ) -> None:
        physician_id = uuid.uuid4()
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.UNEXPECTED_FINDING,
            notified_physician_id=physician_id,
            notified_physician_name="Dr. Kamau",
            notification_method=NotificationMethod.SMS,
        )
        assert alert.notified_physician_id == physician_id
        assert alert.notified_physician_name == "Dr. Kamau"
        assert alert.notification_method == NotificationMethod.SMS


class TestAcknowledgeAlert:
    async def test_acknowledge_alert(self, alert_service: AlertService, order: object) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        acked = await alert_service.acknowledge_alert(alert.id, user_id=TEST_USER_ID)
        assert acked.acknowledged_at is not None
        assert acked.acknowledged_by == TEST_USER_ID

    async def test_acknowledge_nonexistent(self, alert_service: AlertService) -> None:
        with pytest.raises(ValueError, match="not found"):
            await alert_service.acknowledge_alert(uuid.uuid4(), user_id=TEST_USER_ID)

    async def test_acknowledge_twice(self, alert_service: AlertService, order: object) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        await alert_service.acknowledge_alert(alert.id, user_id=TEST_USER_ID)
        with pytest.raises(ValueError, match="already acknowledged"):
            await alert_service.acknowledge_alert(alert.id, user_id=TEST_USER_ID)


class TestEscalateAlert:
    async def test_escalate_alert(self, alert_service: AlertService, order: object) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        escalated = await alert_service.escalate_alert(alert.id)
        assert escalated.escalated is True
        assert escalated.escalated_at is not None

    async def test_escalate_nonexistent(self, alert_service: AlertService) -> None:
        with pytest.raises(ValueError, match="not found"):
            await alert_service.escalate_alert(uuid.uuid4())

    async def test_escalate_twice(self, alert_service: AlertService, order: object) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        await alert_service.escalate_alert(alert.id)
        with pytest.raises(ValueError, match="already escalated"):
            await alert_service.escalate_alert(alert.id)


class TestListAlerts:
    async def test_list_all(self, alert_service: AlertService, order: object) -> None:
        await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.CRITICAL_FINDING,  # type: ignore[union-attr]
        )
        await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.INCIDENTAL,  # type: ignore[union-attr]
        )
        alerts = await alert_service.list_alerts()
        assert len(alerts) == 2

    async def test_list_by_urgency(self, alert_service: AlertService, order: object) -> None:
        await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
            urgency=AlertUrgency.IMMEDIATE,
        )
        await alert_service.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.INCIDENTAL,
            urgency=AlertUrgency.NON_URGENT,
        )
        immediate = await alert_service.list_alerts(urgency=AlertUrgency.IMMEDIATE)
        assert len(immediate) == 1
        assert immediate[0].urgency == AlertUrgency.IMMEDIATE


class TestAlertStats:
    async def test_stats_empty(self, alert_service: AlertService) -> None:
        stats = await alert_service.get_stats()
        assert stats["total"] == 0
        assert stats["pending"] == 0
        assert stats["escalation_rate"] == 0.0

    async def test_stats_with_data(self, alert_service: AlertService, order: object) -> None:
        alert1 = await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.CRITICAL_FINDING,  # type: ignore[union-attr]
        )
        await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.UNEXPECTED_FINDING,  # type: ignore[union-attr]
        )
        await alert_service.acknowledge_alert(alert1.id, user_id=TEST_USER_ID)

        stats = await alert_service.get_stats()
        assert stats["total"] == 2
        assert stats["acknowledged"] == 1
        assert stats["pending"] >= 0


class TestAutoEscalation:
    async def test_check_escalation_no_stale(
        self, alert_service: AlertService, order: object
    ) -> None:
        await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.CRITICAL_FINDING,  # type: ignore[union-attr]
        )
        # Just created, not stale yet
        escalated = await alert_service.check_escalation()
        assert len(escalated) == 0

    async def test_check_escalation_with_stale(
        self, alert_service: AlertService, order: object, db_session: AsyncSession
    ) -> None:
        alert = await alert_service.create_alert(
            order_id=order.id,
            alert_type=AlertType.CRITICAL_FINDING,  # type: ignore[union-attr]
        )
        # Manually backdate the created_at to simulate a stale alert
        alert.created_at = datetime.now(UTC) - timedelta(minutes=60)  # type: ignore[assignment]
        await db_session.flush()

        svc = AlertService(db_session, escalation_timeout_minutes=30)
        escalated = await svc.check_escalation()
        assert len(escalated) == 1
        assert escalated[0].escalated is True


# ---------------------------------------------------------------------------
# GAP: AlertService dispatch failure paths
# ---------------------------------------------------------------------------


class TestAlertServiceDispatchFailures:
    """Dispatcher failures are logged as CRITICAL; commit failures propagate."""

    async def test_create_alert_dispatch_failure_logged(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """When dispatcher raises, logger.critical is called and the alert is still created."""
        from unittest.mock import patch

        class _FailingDispatcher:
            async def dispatch(self, **kwargs: object) -> None:
                raise RuntimeError("SMS gateway down")

        svc = AlertService(db_session, notification_dispatcher=_FailingDispatcher())
        with patch("sautiris.services.alert_service.logger") as mock_logger:
            alert = await svc.create_alert(
                order_id=order.id,  # type: ignore[union-attr]
                alert_type=AlertType.CRITICAL_FINDING,
                finding_description="Tension pneumothorax",
            )
            mock_logger.critical.assert_called()
            event_key = mock_logger.critical.call_args[0][0]
            assert "dispatch_failed" in event_key

        # Alert must still be persisted despite dispatch failure
        assert alert.id is not None

    async def test_escalate_alert_dispatch_failure_logged(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """Escalation dispatch errors are logged as CRITICAL; escalated flag is still set."""
        from unittest.mock import patch

        class _FailingDispatcher:
            async def dispatch(self, **kwargs: object) -> None:
                raise RuntimeError("email server offline")

        svc = AlertService(db_session, notification_dispatcher=_FailingDispatcher())
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )

        with patch("sautiris.services.alert_service.logger") as mock_logger:
            escalated = await svc.escalate_alert(alert.id)
            mock_logger.critical.assert_called()
            event_key = mock_logger.critical.call_args[0][0]
            assert "dispatch_failed" in event_key

        assert escalated.escalated is True

    async def test_check_escalation_dispatch_failure_logged(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """Batch escalation dispatch errors per stale alert are logged as CRITICAL."""
        from unittest.mock import patch

        class _FailingDispatcher:
            async def dispatch(self, **kwargs: object) -> None:
                raise RuntimeError("notification service down")

        svc = AlertService(
            db_session,
            notification_dispatcher=_FailingDispatcher(),
            escalation_timeout_minutes=30,
        )
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        # Backdate to exceed the 30-minute escalation timeout
        alert.created_at = datetime.now(UTC) - timedelta(minutes=60)  # type: ignore[assignment]
        await db_session.flush()

        with patch("sautiris.services.alert_service.logger") as mock_logger:
            escalated_list = await svc.check_escalation()
            mock_logger.critical.assert_called()

        assert len(escalated_list) == 1

    async def test_create_alert_commit_failure_propagates(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """If session.commit raises during create_alert, the error propagates (not swallowed)."""
        from unittest.mock import AsyncMock, patch

        svc = AlertService(db_session)

        with patch.object(db_session, "commit", new_callable=AsyncMock) as mock_commit:
            mock_commit.side_effect = RuntimeError("DB connection lost")
            with pytest.raises(RuntimeError, match="DB connection lost"):
                await svc.create_alert(
                    order_id=order.id,  # type: ignore[union-attr]
                    alert_type=AlertType.CRITICAL_FINDING,
                )


# ---------------------------------------------------------------------------
# EventBus integration tests
# ---------------------------------------------------------------------------


class TestAlertServiceEventBus:
    """CriticalFinding event emission via EventBus."""

    async def test_critical_finding_event_emitted(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """CriticalFinding event is published when alert_type is CRITICAL_FINDING."""
        bus = EventBus()
        received: list[CriticalFinding] = []

        async def handler(event: CriticalFinding) -> None:  # type: ignore[type-arg]
            received.append(event)

        bus.subscribe("finding.critical", handler)

        svc = AlertService(db_session, event_bus=bus)
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
            finding_description="Pneumothorax detected",
            urgency=AlertUrgency.IMMEDIATE,
        )

        assert len(received) == 1
        evt = received[0]
        assert evt.event_type == "finding.critical"
        assert evt.order_id == str(order.id)  # type: ignore[union-attr]
        assert evt.alert_id == str(alert.id)
        assert evt.finding_description == "Pneumothorax detected"
        assert evt.urgency == "IMMEDIATE"

    async def test_no_event_for_non_critical_alert(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """No CriticalFinding event for non-CRITICAL_FINDING alert types."""
        bus = EventBus()
        received: list[CriticalFinding] = []

        async def handler(event: CriticalFinding) -> None:  # type: ignore[type-arg]
            received.append(event)

        bus.subscribe("finding.critical", handler)

        svc = AlertService(db_session, event_bus=bus)
        await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.INCIDENTAL,
            finding_description="Benign cyst noted",
            urgency=AlertUrgency.NON_URGENT,
        )

        assert len(received) == 0

    async def test_no_event_for_unexpected_finding(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """No CriticalFinding event for UNEXPECTED_FINDING alert type."""
        bus = EventBus()
        received: list[CriticalFinding] = []

        async def handler(event: CriticalFinding) -> None:  # type: ignore[type-arg]
            received.append(event)

        bus.subscribe("finding.critical", handler)

        svc = AlertService(db_session, event_bus=bus)
        await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.UNEXPECTED_FINDING,
        )

        assert len(received) == 0

    async def test_event_bus_handler_error_does_not_break_alert(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """If an event handler raises, the alert is still created successfully."""
        bus = EventBus()

        async def failing_handler(event: CriticalFinding) -> None:  # type: ignore[type-arg]
            raise RuntimeError("handler crashed")

        bus.subscribe("finding.critical", failing_handler)

        svc = AlertService(db_session, event_bus=bus)
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
            finding_description="Tension pneumothorax",
        )
        # Alert still persisted despite handler failure
        assert alert.id is not None

    async def test_no_event_bus_still_works(self, db_session: AsyncSession, order: object) -> None:
        """AlertService without event_bus works as before (backward compat)."""
        svc = AlertService(db_session)
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        assert alert.id is not None


# ---------------------------------------------------------------------------
# check_escalation commit failure — returns [] on failure
# ---------------------------------------------------------------------------


class TestCheckEscalationCommitFailure:
    async def test_check_escalation_returns_empty_on_commit_failure(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """check_escalation returns [] when session.commit() fails.

        The escalated records were not persisted, so returning them would
        mislead the caller into thinking they were saved.
        """
        from unittest.mock import AsyncMock, patch

        svc = AlertService(db_session, escalation_timeout_minutes=30)
        alert = await svc.create_alert(
            order_id=order.id,  # type: ignore[union-attr]
            alert_type=AlertType.CRITICAL_FINDING,
        )
        # Backdate to exceed the 30-minute escalation timeout
        alert.created_at = datetime.now(UTC) - timedelta(minutes=60)  # type: ignore[assignment]
        await db_session.flush()

        with patch.object(db_session, "commit", new_callable=AsyncMock) as mock_commit:
            mock_commit.side_effect = RuntimeError("DB went away")
            escalated = await svc.check_escalation()

        # Must return empty list since commit failed — records not persisted
        assert escalated == []
