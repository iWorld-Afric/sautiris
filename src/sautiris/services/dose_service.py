"""DoseService — radiation dose tracking, DRL compliance checking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import ClassVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.events import DomainEvent, DRLExceeded, EventBus
from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.dose import DoseRecord, DoseSource
from sautiris.repositories.dose import DoseRepository
from sautiris.services.mixins import EventPublisherMixin

logger = structlog.get_logger(__name__)


# Kenya NHIF Diagnostic Reference Levels (default, overridable)
# Format: {modality: {body_part: {metric: value}}}
DEFAULT_DRL: dict[str, dict[str, dict[str, float]]] = {
    "CT": {
        "HEAD": {"ctdi_vol": 60.0, "dlp": 1050.0},
        "CHEST": {"ctdi_vol": 15.0, "dlp": 600.0},
        "ABDOMEN": {"ctdi_vol": 20.0, "dlp": 700.0},
        "PELVIS": {"ctdi_vol": 20.0, "dlp": 700.0},
        "SPINE": {"ctdi_vol": 25.0, "dlp": 800.0},
    },
    "CR": {
        "CHEST": {"dap": 0.3, "entrance_dose": 0.4},
        "ABDOMEN": {"dap": 3.0, "entrance_dose": 7.0},
        "PELVIS": {"dap": 3.0, "entrance_dose": 7.0},
        "SKULL": {"dap": 2.0, "entrance_dose": 5.0},
        "SPINE": {"dap": 2.5, "entrance_dose": 6.0},
    },
    "MG": {
        "BREAST": {"dap": 1.0, "entrance_dose": 3.0},
    },
    "XA": {
        "DEFAULT": {"dap": 50.0},
    },
}


class DoseService(EventPublisherMixin):
    """Service for radiation dose tracking and DRL compliance."""

    _critical_event_types: ClassVar[tuple[type[DomainEvent], ...]] = (DRLExceeded,)

    def __init__(
        self,
        session: AsyncSession,
        *,
        drl_reference: dict[str, dict[str, dict[str, float]]] | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.repo = DoseRepository(session)
        self.drl = drl_reference or DEFAULT_DRL
        self._event_bus = event_bus

    async def record_dose(
        self,
        *,
        order_id: uuid.UUID,
        modality: str,
        source: DoseSource = DoseSource.MANUAL,
        recorded_by: uuid.UUID | None = None,
        study_instance_uid: str | None = None,
        ctdi_vol: float | None = None,
        dlp: float | None = None,
        dap: float | None = None,
        effective_dose: float | None = None,
        entrance_dose: float | None = None,
        num_exposures: int | None = None,
        kvp: float | None = None,
        tube_current_ma: float | None = None,
        exposure_time_ms: float | None = None,
        protocol_name: str | None = None,
        body_part: str | None = None,
    ) -> DoseRecord:
        """Record a radiation dose and check against DRLs."""
        exceeds_drl = self._check_drl(
            modality=modality,
            body_part=body_part,
            ctdi_vol=ctdi_vol,
            dlp=dlp,
            dap=dap,
            entrance_dose=entrance_dose,
        )

        record = DoseRecord(
            tenant_id=get_current_tenant_id(),
            order_id=order_id,
            study_instance_uid=study_instance_uid,
            modality=modality,
            ctdi_vol=ctdi_vol,
            dlp=dlp,
            dap=dap,
            effective_dose=effective_dose,
            entrance_dose=entrance_dose,
            num_exposures=num_exposures,
            kvp=kvp,
            tube_current_ma=tube_current_ma,
            exposure_time_ms=exposure_time_ms,
            protocol_name=protocol_name,
            body_part=body_part,
            exceeds_drl=exceeds_drl,
            source=source,
            recorded_by=recorded_by,
            recorded_at=datetime.now(UTC),
        )
        created = await self.repo.create(record)
        await self.session.flush()

        logger.info(
            "dose_recorded",
            dose_id=str(created.id),
            order_id=str(order_id),
            modality=modality,
            exceeds_drl=exceeds_drl,
        )

        # Emit typed DRLExceeded event when dose exceeds reference levels
        if exceeds_drl:
            await self._publish(
                DRLExceeded(
                    order_id=str(order_id),
                    dose_record_id=str(created.id),
                    modality=modality,
                    body_part=body_part,
                    ctdi_vol=ctdi_vol,
                    dlp=dlp,
                    dap=dap,
                    entrance_dose=entrance_dose,
                    tenant_id=get_current_tenant_id(),
                )
            )
            logger.warning(
                "drl_exceeded",
                dose_id=str(created.id),
                modality=modality,
                body_part=body_part,
            )

        return created

    async def get_order_dose(self, order_id: uuid.UUID) -> list[DoseRecord]:
        """Get dose records for a specific order."""
        results = await self.repo.get_for_order(order_id)
        return list(results)

    async def get_patient_dose_history(
        self, patient_id: uuid.UUID, *, offset: int = 0, limit: int = 200
    ) -> list[DoseRecord]:
        """Get cumulative dose history for a patient."""
        results = await self.repo.get_for_patient(patient_id, offset=offset, limit=limit)
        return list(results)

    async def get_stats(self) -> list[dict[str, object]]:
        """Get facility-wide dose statistics grouped by modality."""
        return await self.repo.stats_by_modality()

    async def list_records(
        self,
        *,
        order_id: uuid.UUID | None = None,
        source: DoseSource | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DoseRecord], int]:
        """List dose records with optional filtering."""
        offset = (page - 1) * page_size
        items, total = await self.repo.list_with_filters(
            order_id=order_id,
            source=source,
            offset=offset,
            limit=page_size,
        )
        return list(items), total

    async def get_drl_compliance(self) -> dict[str, object]:
        """Get DRL compliance report."""
        return await self.repo.drl_compliance_stats()

    def _check_drl(
        self,
        *,
        modality: str,
        body_part: str | None,
        ctdi_vol: float | None,
        dlp: float | None,
        dap: float | None,
        entrance_dose: float | None,
    ) -> bool | None:
        """Check if dose values exceed DRL thresholds.

        Returns True if exceeds, False if within limits, None if no DRL defined.
        """
        modality_drl = self.drl.get(modality.upper())
        if modality_drl is None:
            return None

        part = (body_part or "DEFAULT").upper()
        part_drl = modality_drl.get(part)
        if part_drl is None:
            part_drl = modality_drl.get("DEFAULT")
        if part_drl is None:
            return None

        # Check each metric against reference
        if ctdi_vol is not None and "ctdi_vol" in part_drl and ctdi_vol > part_drl["ctdi_vol"]:
            return True
        if dlp is not None and "dlp" in part_drl and dlp > part_drl["dlp"]:
            return True
        if dap is not None and "dap" in part_drl and dap > part_drl["dap"]:
            return True
        return (
            entrance_dose is not None
            and "entrance_dose" in part_drl
            and entrance_dose > part_drl["entrance_dose"]
        )
