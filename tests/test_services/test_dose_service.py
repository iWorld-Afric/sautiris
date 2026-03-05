"""Tests for DoseService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, event_bus
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
        self, dose_service: DoseService, order: object
    ) -> None:
        handler = AsyncMock()
        event_bus.subscribe("DRLExceeded", handler)
        try:
            await dose_service.record_dose(
                order_id=order.id,  # type: ignore[union-attr]
                modality="CT",
                ctdi_vol=100.0,
                body_part="HEAD",
            )
            handler.assert_called_once()
            event: DomainEvent = handler.call_args[0][0]
            assert event.event_type == "DRLExceeded"
            assert event.payload["modality"] == "CT"
        finally:
            event_bus.unsubscribe("DRLExceeded", handler)

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
