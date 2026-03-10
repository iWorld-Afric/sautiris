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
from pynetdicom import AE, evt

from sautiris.integrations.dicom.constants import (
    CHARSET_UTF8,
    DEFAULT_TRANSFER_SYNTAXES,
    build_dicom_ssl_context,
)

if TYPE_CHECKING:
    import ssl  # noqa: F401

    from pynetdicom.events import Event

    from sautiris.integrations.dicom.security import DicomAssociationSecurity  # noqa: F401
    from sautiris.models.worklist import WorklistItem

logger = structlog.get_logger(__name__)

# Modality Worklist Information Model - FIND SOP Class
MWL_FIND_SOP_CLASS = "1.2.840.10008.5.1.4.31"

# Re-exported for backwards compatibility
TRANSFER_SYNTAXES = DEFAULT_TRANSFER_SYNTAXES


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
    # PS3.4 Table K.6-1: PregnancyStatus is Type 2 — MUST be present even when unknown
    pregnancy = getattr(item, "pregnancy_status", None)
    ds.PregnancyStatus = int(pregnancy) if pregnancy is not None else ""
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

    # Type 1 — StudyInstanceUID: generate a new UID if the item has no study UID yet
    study_uid = getattr(item, "study_instance_uid", None)
    ds.StudyInstanceUID = study_uid if study_uid else generate_uid()

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
    if sps_seq and len(sps_seq) > 0:
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


class MWLServer:
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
        self.ae_title = ae_title
        self.port = port
        self._query_callback = query_callback
        self._loop = loop
        self._bind_address = bind_address
        self._security = security
        self._tls_cert = tls_cert
        self._tls_key = tls_key
        self._tls_ca_cert = tls_ca_cert
        self._ae: AE | None = None

    def _handle_find(self, event: Event) -> Any:
        """Handle a C-FIND request from a modality."""
        identifier = event.identifier
        filters = extract_query_filters(identifier)

        logger.info("mwl.c_find_request", filters=filters)

        items: list[WorklistItem] = []
        if self._query_callback and self._loop:
            future = asyncio.run_coroutine_threadsafe(self._query_callback(filters), self._loop)
            try:
                items = future.result(timeout=5.0)  # Reduced from 10 s to bound thread time
            except Exception:
                logger.exception("mwl.query_callback_error")
                yield 0xC001, None
                return

        for item in items:
            try:
                ds = worklist_item_to_dataset(item)
                yield 0xFF00, ds
            except Exception:
                logger.error(
                    "mwl.item_conversion_error",
                    item_id=str(getattr(item, "id", "unknown")),
                    exc_info=True,
                )

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        """Build an SSL context from TLS cert/key/CA parameters."""
        return build_dicom_ssl_context(self._tls_cert, self._tls_key, self._tls_ca_cert)

    def start(self) -> None:
        """Start the MWL SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)
        # Issue #9 — register all 8 supported transfer syntaxes
        self._ae.add_supported_context(MWL_FIND_SOP_CLASS, TRANSFER_SYNTAXES)

        handlers: list[tuple[Any, Any]] = [
            (evt.EVT_C_FIND, self._handle_find),
        ]

        # Issue #6 — wire DicomAssociationSecurity handlers
        if self._security:
            handlers.extend(
                [
                    (evt.EVT_REQUESTED, self._security.handle_association_request),
                    (evt.EVT_RELEASED, self._security.handle_association_released),
                    (evt.EVT_ABORTED, self._security.handle_association_aborted),
                ]
            )

        ssl_context = self._build_ssl_context()
        if ssl_context is None:
            logger.warning(
                "mwl.tls_disabled",
                ae_title=self.ae_title,
                port=self.port,
                msg="MWL SCP starting without TLS — DICOM traffic is unencrypted",
            )
        self._ae.start_server(
            (self._bind_address, self.port),
            block=False,
            ssl_context=ssl_context,
            evt_handlers=handlers,  # type: ignore[arg-type]
        )
        logger.info(
            "mwl.server_started",
            ae_title=self.ae_title,
            port=self.port,
            tls_enabled=ssl_context is not None,
        )

    def stop(self) -> None:
        """Stop the MWL SCP."""
        if self._ae:
            self._ae.shutdown()
            self._ae = None
            logger.info("mwl.server_stopped")
