"""Tests for DoseService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, EventBus
from sautiris.models.dose import DoseSource
from sautiris.services.dose_service import DoseService
from tests.conftest import TEST_USER_ID, make_order


@pytest.fixture
async def order(db_session: AsyncSession) -> object:
    """Create a test order."""
    order = make_order(db_session, modality="CT")
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)
    return order


@pytest.fixture
def dose_service(db_session: AsyncSession) -> DoseService:
    return DoseService(db_session)


class TestRecordDose:
    async def test_record_dose_basic(self, dose_service: DoseService, order: object) -> None:
        record = await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            ctdi_vol=15.0,
            dlp=500.0,
            body_part="CHEST",
            recorded_by=TEST_USER_ID,
        )
        assert record.id is not None
        assert record.ctdi_vol == 15.0
        assert record.dlp == 500.0
        assert record.body_part == "CHEST"
        assert record.exceeds_drl is False  # Within DRL

    async def test_record_dose_exceeds_drl(self, dose_service: DoseService, order: object) -> None:
        record = await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            ctdi_vol=80.0,  # DRL for CT HEAD is 60
            dlp=1200.0,  # DRL for CT HEAD is 1050
            body_part="HEAD",
        )
        assert record.exceeds_drl is True

    async def test_record_dose_emits_drl_event(
        self, db_session: AsyncSession, order: object
    ) -> None:
        bus = EventBus()
        svc = DoseService(db_session, event_bus=bus)
        handler = AsyncMock()
        bus.subscribe("dose.drl_exceeded", handler)
        await svc.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            ctdi_vol=100.0,
            body_part="HEAD",
        )
        handler.assert_called_once()
        from sautiris.core.events import DRLExceeded as DRLExceededEvent

        event: DomainEvent = handler.call_args[0][0]
        assert isinstance(event, DRLExceededEvent)
        assert event.event_type == "dose.drl_exceeded"
        assert event.modality == "CT"

    async def test_record_dose_no_drl_defined(
        self, dose_service: DoseService, order: object
    ) -> None:
        record = await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="US",  # No DRL for US
            body_part="ABDOMEN",
        )
        assert record.exceeds_drl is None

    async def test_record_dose_with_all_fields(
        self, dose_service: DoseService, order: object
    ) -> None:
        record = await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            source=DoseSource.DICOM_SR,
            study_instance_uid="1.2.3.4.5",
            ctdi_vol=12.0,
            dlp=400.0,
            dap=None,
            effective_dose=6.5,
            entrance_dose=None,
            num_exposures=1,
            kvp=120.0,
            tube_current_ma=200.0,
            exposure_time_ms=500.0,
            protocol_name="CT Chest Standard",
            body_part="CHEST",
        )
        assert record.source == DoseSource.DICOM_SR
        assert record.kvp == 120.0
        assert record.effective_dose == 6.5


class TestGetDose:
    async def test_get_order_dose(self, dose_service: DoseService, order: object) -> None:
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            ctdi_vol=10.0,  # type: ignore[union-attr]
        )
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            ctdi_vol=12.0,  # type: ignore[union-attr]
        )
        records = await dose_service.get_order_dose(order.id)  # type: ignore[union-attr]
        assert len(records) == 2

    async def test_get_patient_dose_history(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        patient_id = uuid.uuid4()
        order1 = make_order(db_session, patient_id=patient_id, modality="CT")
        db_session.add(order1)
        await db_session.flush()
        await db_session.refresh(order1)

        order2 = make_order(db_session, patient_id=patient_id, modality="CR")
        db_session.add(order2)
        await db_session.flush()
        await db_session.refresh(order2)

        await dose_service.record_dose(order_id=order1.id, modality="CT", ctdi_vol=10.0)
        await dose_service.record_dose(order_id=order2.id, modality="CR", dap=0.2)

        history = await dose_service.get_patient_dose_history(patient_id)
        assert len(history) == 2


class TestDoseStats:
    async def test_stats_empty(self, dose_service: DoseService) -> None:
        stats = await dose_service.get_stats()
        assert len(stats) == 0

    async def test_stats_with_data(self, dose_service: DoseService, order: object) -> None:
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            ctdi_vol=10.0,  # type: ignore[union-attr]
        )
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            ctdi_vol=20.0,  # type: ignore[union-attr]
        )
        stats = await dose_service.get_stats()
        assert len(stats) == 1
        assert stats[0]["modality"] == "CT"
        assert stats[0]["count"] == 2


class TestDRLCompliance:
    async def test_compliance_empty(self, dose_service: DoseService) -> None:
        compliance = await dose_service.get_drl_compliance()
        assert compliance["compliance_rate"] == 100.0

    async def test_compliance_with_exceedances(
        self, dose_service: DoseService, order: object
    ) -> None:
        # Within DRL
        await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            ctdi_vol=10.0,
            body_part="CHEST",
        )
        # Exceeds DRL
        await dose_service.record_dose(
            order_id=order.id,  # type: ignore[union-attr]
            modality="CT",
            ctdi_vol=100.0,
            body_part="HEAD",
        )
        compliance = await dose_service.get_drl_compliance()
        assert compliance["exceeding_drl"] == 1
        assert compliance["compliance_rate"] < 100.0


# ---------------------------------------------------------------------------
# GAP: DoseService._publish error logging
# ---------------------------------------------------------------------------


class TestPublishErrorLogging:
    """_publish logs errors at ERROR level; DRLExceeded failures escalate to CRITICAL."""

    async def test_publish_handler_error_is_logged(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """_publish logs ERROR for each failing event handler on non-critical events."""
        from unittest.mock import patch

        bus = EventBus()

        async def _failing_handler(event: object) -> None:
            raise ValueError("notification system down")

        # Subscribe to a non-critical event type (any dose event when DRL not exceeded)
        # We can subscribe to all events by using a broad subscription;
        # for simplicity subscribe to "dose.drl_exceeded" but force a DRL exceedance.
        # However, to test non-critical path: subscribe to "order.created" is not
        # available here. Instead, we'll test that when DRL IS exceeded the error is logged.
        bus.subscribe("dose.drl_exceeded", _failing_handler)

        svc = DoseService(db_session, event_bus=bus)

        with patch("sautiris.services.dose_service.logger") as mock_logger:
            await svc.record_dose(
                order_id=order.id,  # type: ignore[union-attr]
                modality="CT",
                ctdi_vol=100.0,  # exceeds DRL → emits DRLExceeded
                body_part="HEAD",
            )
            # logger.error must be called for the handler failure
            mock_logger.error.assert_called()

    async def test_drl_exceeded_handler_failure_logs_critical(
        self, db_session: AsyncSession, order: object
    ) -> None:
        """When a DRLExceeded handler fails, _publish also logs at CRITICAL level.

        DRLExceeded is a patient-safety event (radiation overdose). Handler
        failures must be escalated to CRITICAL level.
        """
        from unittest.mock import patch

        bus = EventBus()

        async def _failing_handler(event: object) -> None:
            raise RuntimeError("dose alert system offline")

        bus.subscribe("dose.drl_exceeded", _failing_handler)
        svc = DoseService(db_session, event_bus=bus)

        with patch("sautiris.services.dose_service.logger") as mock_logger:
            await svc.record_dose(
                order_id=order.id,  # type: ignore[union-attr]
                modality="CT",
                ctdi_vol=100.0,  # exceeds DRL
                body_part="HEAD",
            )
            # CRITICAL must be logged for DRLExceeded handler failure
            mock_logger.critical.assert_called()
            call_args = mock_logger.critical.call_args
            event_key = call_args[0][0] if call_args[0] else ""
            assert "drl" in event_key.lower() or "drl_exceeded" in event_key.lower()


# ---------------------------------------------------------------------------
# GAP-R4-6: DoseService._check_drl DAP and entrance_dose paths
# ---------------------------------------------------------------------------


class TestCheckDrlDapAndEntranceDose:
    """_check_drl correctly evaluates DAP and entrance_dose metrics (CR modality)."""

    async def test_cr_chest_dap_exceeds_drl(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """CR CHEST with DAP above threshold (0.3 Gy·cm²) sets exceeds_drl=True."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            dap=0.5,  # DRL threshold is 0.3 → exceeds
        )
        assert record.exceeds_drl is True

    async def test_cr_chest_dap_within_drl(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """CR CHEST with DAP below threshold (0.3 Gy·cm²) sets exceeds_drl=False."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            dap=0.1,  # below threshold 0.3
        )
        assert record.exceeds_drl is False

    async def test_cr_chest_entrance_dose_exceeds_drl(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """CR CHEST with entrance_dose above threshold (0.4 mGy) sets exceeds_drl=True."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            entrance_dose=0.8,  # DRL threshold is 0.4 → exceeds
        )
        assert record.exceeds_drl is True

    async def test_cr_chest_entrance_dose_within_drl(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """CR CHEST with entrance_dose below threshold (0.4 mGy) sets exceeds_drl=False."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            entrance_dose=0.2,  # below threshold 0.4
        )
        assert record.exceeds_drl is False

    async def test_cr_abdomen_dap_exceeds_drl(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """CR ABDOMEN with DAP above threshold (3.0 Gy·cm²) sets exceeds_drl=True."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="ABDOMEN",
            dap=5.0,  # DRL threshold is 3.0 → exceeds
        )
        assert record.exceeds_drl is True

    async def test_drl_check_only_dap_provided_no_entrance_dose(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """When only DAP is provided (no entrance_dose), check_drl evaluates DAP alone."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            dap=0.4,  # above 0.3 → exceeds
            entrance_dose=None,
        )
        assert record.exceeds_drl is True

    async def test_drl_check_only_entrance_dose_provided_no_dap(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """When only entrance_dose is provided (no DAP), check_drl evaluates entrance_dose alone."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            dap=None,
            entrance_dose=0.3,  # below 0.4 → within DRL
        )
        assert record.exceeds_drl is False

    async def test_drl_exceeded_emits_event_on_dap_exceedance(
        self, db_session: AsyncSession
    ) -> None:
        """A DRLExceeded event is emitted when DAP exceeds the CR CHEST threshold."""
        from unittest.mock import AsyncMock

        from sautiris.core.events import DRLExceeded, EventBus

        bus = EventBus()
        handler = AsyncMock()
        bus.subscribe("dose.drl_exceeded", handler)
        svc = DoseService(db_session, event_bus=bus)

        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        await svc.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            dap=0.5,  # exceeds 0.3 threshold
        )

        handler.assert_called_once()
        event = handler.call_args[0][0]
        assert isinstance(event, DRLExceeded)
        assert event.modality == "CR"
        assert event.body_part == "CHEST"


# ---------------------------------------------------------------------------
# GAP: DRL entrance_dose boundary edge cases
# ---------------------------------------------------------------------------


class TestDoseEdgeCases:
    """Zero and very large entrance_dose values are stored without raising."""

    async def test_zero_entrance_dose_accepted(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """Zero entrance dose (e.g., aborted scan) is a valid value and within DRL."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            entrance_dose=0.0,  # DRL threshold is 0.4 — zero is well within
        )

        assert record.id is not None
        assert record.entrance_dose == 0.0
        assert record.exceeds_drl is False  # 0.0 > 0.4 is False

    async def test_very_large_dose_accepted(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """Very large dose values (e.g., equipment error) are stored, flagged as exceeding DRL."""
        order = make_order(db_session, modality="CR")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        record = await dose_service.record_dose(
            order_id=order.id,
            modality="CR",
            body_part="CHEST",
            entrance_dose=9999.0,  # far above DRL threshold of 0.4
        )

        assert record.id is not None
        assert record.entrance_dose == 9999.0
        assert record.exceeds_drl is True


# ---------------------------------------------------------------------------
# GAP-M10: DoseService.list_records() — filter by source
# ---------------------------------------------------------------------------


class TestListRecordsFilter:
    """list_records(source=...) filters correctly; no filter returns all records."""

    async def test_list_records_filter_by_manual(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """list_records(source=MANUAL) returns only manually-entered records."""
        order = make_order(db_session, modality="CT")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.MANUAL,
            ctdi_vol=10.0,
        )
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.DICOM_SR,
            ctdi_vol=12.0,
        )

        records, total = await dose_service.list_records(source=DoseSource.MANUAL)
        assert total == 1
        assert len(records) == 1
        assert records[0].source == DoseSource.MANUAL

    async def test_list_records_filter_by_dicom_sr(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """list_records(source=DICOM_SR) returns only DICOM SR-sourced records."""
        order = make_order(db_session, modality="CT")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.MANUAL,
            ctdi_vol=10.0,
        )
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.DICOM_SR,
            ctdi_vol=12.0,
        )

        records, total = await dose_service.list_records(source=DoseSource.DICOM_SR)
        assert total == 1
        assert len(records) == 1
        assert records[0].source == DoseSource.DICOM_SR

    async def test_list_records_no_filter_returns_all(
        self, dose_service: DoseService, db_session: AsyncSession
    ) -> None:
        """list_records() with no source filter returns records of all sources."""
        order = make_order(db_session, modality="CT")
        db_session.add(order)
        await db_session.flush()
        await db_session.refresh(order)

        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.MANUAL,
            ctdi_vol=10.0,
        )
        await dose_service.record_dose(
            order_id=order.id,
            modality="CT",
            source=DoseSource.DICOM_SR,
            ctdi_vol=12.0,
        )

        records, total = await dose_service.list_records()
        assert total == 2
        assert len(records) == 2
