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
from pynetdicom import AE, evt

if TYPE_CHECKING:
    from pynetdicom.events import Event

    from sautiris.models.worklist import WorklistItem

logger = structlog.get_logger(__name__)

# Modality Worklist Information Model - FIND SOP Class
MWL_FIND_SOP_CLASS = "1.2.840.10008.5.1.4.31"


def worklist_item_to_dataset(item: WorklistItem) -> Dataset:
    """Convert a WorklistItem DB record to a DICOM MWL response dataset.

    Maps WorklistItem fields to the standard DICOM MWL response tags:
    - Patient-level: PatientName, PatientID, PatientBirthDate, PatientSex
    - Procedure-level: AccessionNumber, ReferringPhysicianName,
      RequestedProcedureID, RequestedProcedureDescription
    - Scheduled Procedure Step Sequence: Modality, ScheduledStationAETitle,
      ScheduledProcedureStepStartDate/Time, ScheduledProcedureStepID,
      ScheduledProcedureStepDescription
    """
    ds = Dataset()

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

    # Procedure-level attributes
    ds.AccessionNumber = item.accession_number or ""
    ds.ReferringPhysicianName = item.referring_physician_name or ""
    ds.RequestedProcedureID = item.requested_procedure_id or ""
    ds.RequestedProcedureDescription = item.requested_procedure_description or ""

    # Scheduled Procedure Step Sequence
    sps = Dataset()
    sps.Modality = item.modality or ""
    sps.ScheduledStationAETitle = item.scheduled_station_ae_title or ""
    sps.ScheduledProcedureStepID = item.scheduled_procedure_step_id or ""
    sps.ScheduledProcedureStepDescription = item.scheduled_procedure_step_description or ""

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

    Parses the incoming DICOM C-FIND request and returns a dict of filters
    that can be passed to the worklist repository's ``list_with_filters``.
    """
    filters: dict[str, Any] = {}

    # Check Scheduled Procedure Step Sequence for modality/AE title
    sps_seq = getattr(identifier, "ScheduledProcedureStepSequence", None)
    if sps_seq and len(sps_seq) > 0:
        sps = sps_seq[0]
        modality = getattr(sps, "Modality", None)
        if modality and str(modality).strip():
            filters["modality"] = str(modality).strip()

        ae_title = getattr(sps, "ScheduledStationAETitle", None)
        if ae_title and str(ae_title).strip():
            filters["scheduled_station_ae_title"] = str(ae_title).strip()

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
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_MWL",
        port: int = 11112,
        query_callback: Callable[..., Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._query_callback = query_callback
        self._loop = loop
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
                items = future.result(timeout=10.0)
            except Exception:
                logger.exception("mwl.query_callback_error")
                yield 0xC001, None
                return

        for item in items:
            ds = worklist_item_to_dataset(item)
            yield 0xFF00, ds

    def start(self) -> None:
        """Start the MWL SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)
        self._ae.add_supported_context(MWL_FIND_SOP_CLASS)

        handlers = [(evt.EVT_C_FIND, self._handle_find)]
        self._ae.start_server(
            ("0.0.0.0", self.port),
            block=False,
            evt_handlers=handlers,  # type: ignore[arg-type]
        )
        logger.info("mwl.server_started", ae_title=self.ae_title, port=self.port)

    def stop(self) -> None:
        """Stop the MWL SCP."""
        if self._ae:
            self._ae.shutdown()
            self._ae = None
            logger.info("mwl.server_stopped")
