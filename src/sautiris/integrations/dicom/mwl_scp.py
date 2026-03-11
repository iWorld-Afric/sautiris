"""DICOM Modality Worklist SCP using pynetdicom.

Provides a C-FIND SCP that returns scheduled worklist items from
the SautiRIS database. Modalities query this to get their worklists.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import structlog
from pydicom.dataset import Dataset
from pydicom.uid import generate_uid
from pynetdicom import AE, evt  # AE imported here so tests can patch this module's AE

from sautiris.integrations.dicom.base_scp import BaseSCPServer
from sautiris.integrations.dicom.constants import (
    CHARSET_UTF8,
    DicomHandlerList,
)

if TYPE_CHECKING:
    from pynetdicom.events import Event

    from sautiris.integrations.dicom.security import DicomAssociationSecurity  # noqa: F401
    from sautiris.models.worklist import WorklistItem

logger = structlog.get_logger(__name__)

# Modality Worklist Information Model - FIND SOP Class
MWL_FIND_SOP_CLASS = "1.2.840.10008.5.1.4.31"


def worklist_item_to_dataset(item: WorklistItem) -> Dataset:
    """Convert a WorklistItem DB record to a DICOM MWL response dataset.

    Includes all required Type 1, Type 1C, and Type 2 tags per DICOM
    PS3.4 Annex K (Modality Worklist Information Model).

    Issue #3: adds StudyInstanceUID, ReferencedStudySequence,
    RequestedProcedureCodeSequence, RequestAttributesSequence, StudyID,
    StudyDate, StudyTime, RequestedProcedurePriority, PatientWeight,
    MedicalAlerts, Allergies, PregnancyStatus.
    Issue #5: sets SpecificCharacterSet = ISO_IR 192 as the first tag.
    """
    ds = Dataset()

    # Issue #5 — MUST be the first tag in every outbound dataset
    ds.SpecificCharacterSet = CHARSET_UTF8

    # Patient-level attributes
    ds.PatientName = item.patient_name or ""
    ds.PatientID = item.patient_id or ""
    if item.patient_dob:
        ds.PatientBirthDate = (
            item.patient_dob.strftime("%Y%m%d") if isinstance(item.patient_dob, date) else ""
        )
    else:
        ds.PatientBirthDate = ""
    ds.PatientSex = item.patient_sex or ""

    # Type 2 patient tags (required, may be zero-length)
    ds.PatientWeight = str(getattr(item, "patient_weight", "") or "")
    ds.MedicalAlerts = str(getattr(item, "medical_alerts", "") or "")
    ds.Allergies = str(getattr(item, "allergies", "") or "")
    # PS3.4 Table K.6-1: PregnancyStatus (0010,21C0) is VR US, Type 2.
    # Zero-length US value must be represented as None (not ""), otherwise
    # pydicom emits a warning flood for the empty-string sentinel (#15).
    pregnancy = getattr(item, "pregnancy_status", None)
    ds.PregnancyStatus = int(pregnancy) if pregnancy is not None else None
    # Type 2: IssuerOfPatientID (0010,0021) — required, may be zero-length
    ds.IssuerOfPatientID = str(getattr(item, "issuer_of_patient_id", "") or "")

    # Type 2: AdmissionID (0038,0010) — required, may be zero-length
    ds.AdmissionID = str(getattr(item, "admission_id", "") or "")
    # Type 2: ReferencedPatientSequence (0008,1120) — required, may be empty Sequence
    ds.ReferencedPatientSequence = []

    # Procedure-level attributes
    ds.AccessionNumber = item.accession_number or ""
    ds.ReferringPhysicianName = item.referring_physician_name or ""
    ds.RequestedProcedureID = item.requested_procedure_id or ""
    ds.RequestedProcedureDescription = item.requested_procedure_description or ""
    ds.RequestedProcedurePriority = str(getattr(item, "requested_procedure_priority", "") or "")

    # Type 1 — StudyInstanceUID: generate a new UID if the item has no study UID yet.
    # #19: log a warning when falling back to a generated UID so operators are aware.
    study_uid = getattr(item, "study_instance_uid", None)
    if study_uid:
        ds.StudyInstanceUID = study_uid
    else:
        generated = generate_uid()
        logger.warning(
            "mwl.study_uid_generated",
            item_id=str(getattr(item, "id", "unknown")),
            generated_uid=str(generated),
        )
        ds.StudyInstanceUID = generated

    # Type 2 study-level tags
    ds.StudyID = str(getattr(item, "study_id", "") or "")
    if item.scheduled_start and isinstance(item.scheduled_start, datetime):
        ds.StudyDate = item.scheduled_start.strftime("%Y%m%d")
        ds.StudyTime = item.scheduled_start.strftime("%H%M%S")
    else:
        ds.StudyDate = ""
        ds.StudyTime = ""

    # Type 1C — empty if no referenced study
    ds.ReferencedStudySequence = []

    # Type 1C — empty if no procedure code
    ds.RequestedProcedureCodeSequence = []

    # Type 2 — RequestAttributesSequence (empty sequence is valid)
    ds.RequestAttributesSequence = []

    # Scheduled Procedure Step Sequence
    sps = Dataset()
    sps.Modality = item.modality or ""
    sps.ScheduledStationAETitle = item.scheduled_station_ae_title or ""
    sps.ScheduledProcedureStepID = item.scheduled_procedure_step_id or ""
    sps.ScheduledProcedureStepDescription = item.scheduled_procedure_step_description or ""
    sps.ScheduledProcedureStepStatus = str(getattr(item, "status", "") or "")
    sps.ScheduledPerformingPhysicianName = str(
        getattr(item, "scheduled_performing_physician_name", "") or ""
    )
    # Type 2: ScheduledProtocolCodeSequence (0040,0008) — required, may be empty Sequence
    sps.ScheduledProtocolCodeSequence = []

    if item.scheduled_start:
        if isinstance(item.scheduled_start, datetime):
            sps.ScheduledProcedureStepStartDate = item.scheduled_start.strftime("%Y%m%d")
            sps.ScheduledProcedureStepStartTime = item.scheduled_start.strftime("%H%M%S")
        else:
            sps.ScheduledProcedureStepStartDate = ""
            sps.ScheduledProcedureStepStartTime = ""
    else:
        sps.ScheduledProcedureStepStartDate = ""
        sps.ScheduledProcedureStepStartTime = ""

    ds.ScheduledProcedureStepSequence = [sps]

    return ds


def extract_query_filters(identifier: Dataset) -> dict[str, Any]:
    """Extract query filters from a C-FIND request identifier dataset.

    Implements DICOM universal matching: an absent or zero-length value in
    the query means "match all" (no filter added for that attribute).

    Issue #3: adds PatientID, PatientName, AccessionNumber,
    RequestedProcedureID, and ScheduledProcedureStepStatus filters.
    """
    filters: dict[str, Any] = {}

    # Top-level patient / procedure attributes (universal matching)
    patient_id = getattr(identifier, "PatientID", None)
    if patient_id and str(patient_id).strip():
        filters["patient_id"] = str(patient_id).strip()

    patient_name = getattr(identifier, "PatientName", None)
    if patient_name and str(patient_name).strip():
        name_str = str(patient_name).strip()
        if "*" in name_str or "?" in name_str:
            # DICOM wildcard query (PS3.4 C.2.2.2.4) — convert to SQL LIKE pattern.
            # Escape SQL LIKE metacharacters first, then convert DICOM wildcards.
            escaped = name_str.replace("%", r"\%").replace("_", r"\_")
            like_pattern = escaped.replace("*", "%").replace("?", "_")
            filters["patient_name_pattern"] = like_pattern
        else:
            filters["patient_name"] = name_str

    accession = getattr(identifier, "AccessionNumber", None)
    if accession and str(accession).strip():
        filters["accession_number"] = str(accession).strip()

    rp_id = getattr(identifier, "RequestedProcedureID", None)
    if rp_id and str(rp_id).strip():
        filters["requested_procedure_id"] = str(rp_id).strip()

    # Check Scheduled Procedure Step Sequence for modality/AE title/date/status
    sps_seq = getattr(identifier, "ScheduledProcedureStepSequence", None)
    if sps_seq:
        sps = sps_seq[0]
        modality = getattr(sps, "Modality", None)
        if modality and str(modality).strip():
            filters["modality"] = str(modality).strip()

        ae_title = getattr(sps, "ScheduledStationAETitle", None)
        if ae_title and str(ae_title).strip():
            filters["scheduled_station_ae_title"] = str(ae_title).strip()

        sps_status = getattr(sps, "ScheduledProcedureStepStatus", None)
        if sps_status and str(sps_status).strip():
            filters["scheduled_procedure_step_status"] = str(sps_status).strip()

        # Date range from ScheduledProcedureStepStartDate
        start_date = getattr(sps, "ScheduledProcedureStepStartDate", None)
        if start_date and str(start_date).strip():
            date_str = str(start_date).strip()
            if "-" in date_str:
                # Range query: YYYYMMDD-YYYYMMDD
                parts = date_str.split("-")
                if parts[0]:
                    filters["date_from"] = datetime.strptime(parts[0], "%Y%m%d").date()
                if len(parts) > 1 and parts[1]:
                    filters["date_to"] = datetime.strptime(parts[1], "%Y%m%d").date()
            else:
                # Single date
                d = datetime.strptime(date_str, "%Y%m%d").date()
                filters["date_from"] = d
                filters["date_to"] = d

    return filters


class MWLServer(BaseSCPServer):
    """Modality Worklist SCP server.

    Uses pynetdicom to run a C-FIND SCP. On each query, it calls the
    provided ``query_callback`` to fetch worklist items from the database
    (bridging async to sync via ``asyncio.run_coroutine_threadsafe``).

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        query_callback: Async callable that receives filter dict and returns
            list of WorklistItem objects.
        loop: The asyncio event loop to run async callbacks on.
        bind_address: IP address to bind to (default ``"127.0.0.1"``).
            Issue #17: changed default from 0.0.0.0 to localhost-only.
        security: Optional DicomAssociationSecurity for AE whitelist/rate/connection limits.
        tls_cert: Path to TLS certificate file.  Empty string disables TLS.
        tls_key: Path to TLS private key file.  Empty string disables TLS.
        tls_ca_cert: Path to CA certificate for mutual TLS.  Empty string
            disables client verification.
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_MWL",
        port: int = 11112,
        query_callback: Callable[..., Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        bind_address: str = "127.0.0.1",
        security: DicomAssociationSecurity | None = None,
        tls_cert: str = "",
        tls_key: str = "",
        tls_ca_cert: str = "",
    ) -> None:
        super().__init__(
            ae_title=ae_title,
            port=port,
            loop=loop,
            bind_address=bind_address,
            security=security,
            tls_cert=tls_cert,
            tls_key=tls_key,
            tls_ca_cert=tls_ca_cert,
        )
        self._query_callback = query_callback

    # ------------------------------------------------------------------
    # BaseSCPServer interface
    # ------------------------------------------------------------------

    def _make_ae(self) -> AE:
        """Use this module's AE so that ``patch('...mwl_scp.AE')`` works in tests."""
        return AE(ae_title=self.ae_title)

    def _get_sop_classes_and_handlers(self) -> tuple[list[str], DicomHandlerList]:
        return [MWL_FIND_SOP_CLASS], [(evt.EVT_C_FIND, self._handle_find)]

    def _log_started(self, tls_enabled: bool) -> None:
        logger.info(
            "mwl.server_started",
            ae_title=self.ae_title,
            port=self.port,
            tls_enabled=tls_enabled,
        )

    # ------------------------------------------------------------------
    # C-FIND handler
    # ------------------------------------------------------------------

    def _handle_find(self, event: Event) -> Any:
        """Handle a C-FIND request from a modality."""
        identifier = event.identifier
        filters = extract_query_filters(identifier)

        safe_filters = {
            k: "[REDACTED]" if k in ("patient_name", "patient_name_pattern", "patient_id") else v
            for k, v in filters.items()
        }
        logger.info("mwl.c_find_request", filters=safe_filters)

        items: list[WorklistItem] = []
        if self._query_callback and self._loop:
            future = asyncio.run_coroutine_threadsafe(self._query_callback(filters), self._loop)
            try:
                items = future.result(timeout=5.0)  # Reduced from 10 s to bound thread time
            except Exception:
                logger.exception("mwl.query_callback_error")
                yield 0xC001, None
                return

        total = len(items)
        skipped = 0
        for item in items:
            try:
                ds = worklist_item_to_dataset(item)
                yield 0xFF00, ds
            except Exception:
                skipped += 1
                logger.error(
                    "mwl.item_conversion_error",
                    item_id=str(getattr(item, "id", "unknown")),
                    exc_info=True,
                )

        # #18: log at CRITICAL when items were skipped so operators can investigate
        if skipped:
            logger.critical(
                "mwl.items_skipped",
                skipped_count=skipped,
                total=total,
            )

    # ------------------------------------------------------------------
    # Lifecycle — delegate to base; keep stop() for instance-clearing
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop the MWL SCP."""
        super().stop()
        logger.info("mwl.server_stopped")
