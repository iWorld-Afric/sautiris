"""DICOM Modality Performed Procedure Step (MPPS) SCP using pynetdicom.

Handles N-CREATE and N-SET requests from modalities to track procedure
step status (IN PROGRESS, COMPLETED, DISCONTINUED).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from pydicom.dataset import Dataset
from pynetdicom import AE, evt

if TYPE_CHECKING:
    from pynetdicom.events import Event

logger = structlog.get_logger(__name__)

# MPPS SOP Class UID
MPPS_SOP_CLASS = "1.2.840.10008.3.1.2.3.3"


def extract_mpps_data(dataset: Dataset) -> dict[str, Any]:
    """Extract relevant MPPS data from a DICOM dataset.

    Parses the N-CREATE or N-SET dataset and returns a dict with:
    - mpps_status: "IN PROGRESS", "COMPLETED", or "DISCONTINUED"
    - performed_procedure_step_id: The SPS ID being performed
    - performed_station_ae_title: AE title of the performing modality
    - accession_number: From the Scheduled Step Attributes Sequence
    - study_instance_uid: From the Scheduled Step Attributes Sequence
    """
    data: dict[str, Any] = {}

    status = getattr(dataset, "PerformedProcedureStepStatus", None)
    if status:
        data["mpps_status"] = str(status).strip()

    ppsi = getattr(dataset, "PerformedProcedureStepID", None)
    if ppsi:
        data["performed_procedure_step_id"] = str(ppsi).strip()

    ae_title = getattr(dataset, "PerformedStationAETitle", None)
    if ae_title:
        data["performed_station_ae_title"] = str(ae_title).strip()

    # Extract from Scheduled Step Attributes Sequence
    ssas = getattr(dataset, "ScheduledStepAttributesSequence", None)
    if ssas and len(ssas) > 0:
        step = ssas[0]
        accession = getattr(step, "AccessionNumber", None)
        if accession:
            data["accession_number"] = str(accession).strip()

        study_uid = getattr(step, "StudyInstanceUID", None)
        if study_uid:
            data["study_instance_uid"] = str(study_uid).strip()

    return data


class MPPSServer:
    """Modality Performed Procedure Step SCP server.

    Uses pynetdicom to handle N-CREATE and N-SET requests. On each
    request, calls the provided ``status_callback`` to update the
    worklist item status in the database.

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        status_callback: Async callable that receives (mpps_uid, mpps_data_dict)
            and updates the worklist item.
        loop: The asyncio event loop to run async callbacks on.
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_MPPS",
        port: int = 11113,
        status_callback: Callable[..., Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._status_callback = status_callback
        self._loop = loop
        self._ae: AE | None = None
        # In-memory MPPS instance store (SOP Instance UID -> Dataset)
        self._instances: dict[str, Dataset] = {}

    def _handle_n_create(self, event: Event) -> tuple[Dataset | None, int]:
        """Handle MPPS N-CREATE (procedure step started)."""
        attr_list = event.attribute_list
        sop_instance_uid = str(event.request.AffectedSOPInstanceUID)  # type: ignore[union-attr]

        logger.info("mpps.n_create", sop_instance_uid=sop_instance_uid)

        if sop_instance_uid in self._instances:
            logger.warning("mpps.duplicate_create", sop_instance_uid=sop_instance_uid)
            return None, 0xC001

        # Store the instance
        self._instances[sop_instance_uid] = attr_list

        mpps_data = extract_mpps_data(attr_list)
        self._invoke_callback(sop_instance_uid, mpps_data)

        return attr_list, 0x0000

    def _handle_n_set(self, event: Event) -> tuple[Dataset | None, int]:
        """Handle MPPS N-SET (procedure step completed/discontinued)."""
        mod_list = event.modification_list
        sop_instance_uid = str(event.request.RequestedSOPInstanceUID)  # type: ignore[union-attr]

        logger.info("mpps.n_set", sop_instance_uid=sop_instance_uid)

        if sop_instance_uid not in self._instances:
            logger.warning("mpps.unknown_instance", sop_instance_uid=sop_instance_uid)
            return None, 0xC001

        # Update the stored instance
        stored = self._instances[sop_instance_uid]
        for elem in mod_list:
            stored.add(elem)

        mpps_data = extract_mpps_data(stored)
        self._invoke_callback(sop_instance_uid, mpps_data)

        return stored, 0x0000

    def _invoke_callback(self, mpps_uid: str, mpps_data: dict[str, Any]) -> None:
        """Invoke the async status callback from the sync pynetdicom thread."""
        if self._status_callback and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._status_callback(mpps_uid, mpps_data), self._loop
            )
            try:
                future.result(timeout=10.0)
            except Exception:
                logger.exception("mpps.callback_error", mpps_uid=mpps_uid)

    def start(self) -> None:
        """Start the MPPS SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)
        self._ae.add_supported_context(MPPS_SOP_CLASS)

        handlers = [
            (evt.EVT_N_CREATE, self._handle_n_create),
            (evt.EVT_N_SET, self._handle_n_set),
        ]
        self._ae.start_server(
            ("0.0.0.0", self.port),
            block=False,
            evt_handlers=handlers,  # type: ignore[arg-type]
        )
        logger.info("mpps.server_started", ae_title=self.ae_title, port=self.port)

    def stop(self) -> None:
        """Stop the MPPS SCP."""
        if self._ae:
            self._ae.shutdown()
            self._ae = None
            self._instances.clear()
            logger.info("mpps.server_stopped")
