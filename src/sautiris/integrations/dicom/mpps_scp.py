"""DICOM Modality Performed Procedure Step (MPPS) SCP using pynetdicom.

Handles N-CREATE and N-SET requests from modalities to track procedure
step status (IN PROGRESS, COMPLETED, DISCONTINUED).

Issue #14: Implements proper state machine validation:
  - N-CREATE only allowed with status "IN PROGRESS"
  - N-SET only allowed from "IN PROGRESS" → "COMPLETED" | "DISCONTINUED"
  - Invalid transitions return DIMSE status 0x0110
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import structlog
from pydicom.dataset import Dataset
from pynetdicom import AE, evt

from sautiris.models.mpps import MPPSStatusEnum

if TYPE_CHECKING:
    from pynetdicom.events import Event

logger = structlog.get_logger(__name__)

# MPPS SOP Class UID
MPPS_SOP_CLASS = "1.2.840.10008.3.1.2.3.3"

# SpecificCharacterSet for UTF-8 (ISO_IR 192) — Issue #5
CHARSET_UTF8 = "ISO_IR 192"

# Transfer syntaxes supported by this SCP — Issue #9
TRANSFER_SYNTAXES: list[str] = [
    "1.2.840.10008.1.2.1",    # Explicit VR Little Endian
    "1.2.840.10008.1.2",      # Implicit VR Little Endian
    "1.2.840.10008.1.2.4.50", # JPEG Baseline (Process 1)
    "1.2.840.10008.1.2.4.70", # JPEG Lossless (Process 14 SV1)
    "1.2.840.10008.1.2.4.90", # JPEG 2000 Lossless Only
    "1.2.840.10008.1.2.4.91", # JPEG 2000
    "1.2.840.10008.1.2.5",    # RLE Lossless
    "1.2.840.10008.1.2.1.99", # Deflated Explicit VR Little Endian
]

# Issue #14 — valid MPPS status values (use enum for type safety)
MPPS_STATUS_IN_PROGRESS = MPPSStatusEnum.IN_PROGRESS
MPPS_STATUS_COMPLETED = MPPSStatusEnum.COMPLETED
MPPS_STATUS_DISCONTINUED = MPPSStatusEnum.DISCONTINUED

# Issue #14 — valid target statuses reachable via N-SET from IN PROGRESS
MPPS_TERMINAL_STATUSES: frozenset[MPPSStatusEnum] = frozenset(
    {MPPSStatusEnum.COMPLETED, MPPSStatusEnum.DISCONTINUED}
)


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


def _make_mpps_response(dataset: Dataset) -> Dataset:
    """Add SpecificCharacterSet to an outbound MPPS response dataset."""
    dataset.SpecificCharacterSet = CHARSET_UTF8
    return dataset


class MPPSServer:
    """Modality Performed Procedure Step SCP server.

    Uses pynetdicom to handle N-CREATE and N-SET requests. On each
    request, calls the provided ``status_callback`` to update the
    worklist item status in the database.

    Issue #14: Enforces the MPPS state machine:
    - N-CREATE requires status = "IN PROGRESS" (0x0110 if violated)
    - N-SET validates current→new transition (0x0110 if invalid)
    - Duplicate N-CREATE returns 0x0110

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        status_callback: Async callable that receives (mpps_uid, mpps_data_dict)
            and updates the worklist item.
        loop: The asyncio event loop to run async callbacks on.
        bind_address: IP address to bind to (default ``"127.0.0.1"``).
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_MPPS",
        port: int = 11113,
        status_callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        bind_address: str = "127.0.0.1",
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._status_callback = status_callback
        self._loop = loop
        self._bind_address = bind_address
        self._ae: AE | None = None
        # In-memory MPPS instance store: SOP Instance UID → Dataset
        # Used for state machine tracking; DB persistence handled via callbacks.
        self._instances: dict[str, Dataset] = {}
        # Mutex for atomic duplicate-check + store in N-CREATE (prevents TOCTOU race)
        self._create_lock = threading.Lock()

    def _current_status(self, sop_instance_uid: str) -> MPPSStatusEnum | None:
        """Return current PerformedProcedureStepStatus for a known UID, or None."""
        if sop_instance_uid not in self._instances:
            return None
        stored = self._instances[sop_instance_uid]
        val = getattr(stored, "PerformedProcedureStepStatus", None)
        if not val:
            return None
        try:
            return MPPSStatusEnum(str(val).strip())
        except ValueError:
            return None

    def _handle_n_create(self, event: Event) -> tuple[int, Dataset | None]:
        """Handle MPPS N-CREATE (procedure step started).

        Issue #14 state machine: initial status MUST be IN PROGRESS.
        """
        attr_list = event.attribute_list
        sop_instance_uid = str(event.request.AffectedSOPInstanceUID)  # type: ignore[union-attr]

        logger.info("mpps.n_create", sop_instance_uid=sop_instance_uid)

        # Issue #14 — N-CREATE MUST carry status "IN PROGRESS" (validate first,
        # before acquiring lock, since status check has no side effects)
        requested_status = str(
            getattr(attr_list, "PerformedProcedureStepStatus", "")
        ).strip()
        if requested_status != MPPS_STATUS_IN_PROGRESS:
            logger.warning(
                "mpps.invalid_initial_status",
                sop_instance_uid=sop_instance_uid,
                status=requested_status,
            )
            return 0x0110, None

        # Atomic duplicate-check + store under lock to prevent TOCTOU race
        # (two concurrent N-CREATEs for the same UID both passing the check
        # before either writes — FIX-6)
        with self._create_lock:
            if sop_instance_uid in self._instances:
                logger.warning("mpps.duplicate_create", sop_instance_uid=sop_instance_uid)
                return 0x0110, None
            # Store the instance atomically
            self._instances[sop_instance_uid] = attr_list

        mpps_data = extract_mpps_data(attr_list)
        if not self._invoke_callback(sop_instance_uid, mpps_data):
            return 0xC001, None

        response = _make_mpps_response(Dataset())
        return 0x0000, response

    def _handle_n_set(self, event: Event) -> tuple[int, Dataset | None]:
        """Handle MPPS N-SET (procedure step completed/discontinued).

        Issue #14 state machine:
        - Instance must exist (else 0x0110)
        - Current status must be IN PROGRESS (else 0x0110)
        - New status must be COMPLETED or DISCONTINUED (else 0x0110)
        """
        mod_list = event.modification_list
        sop_instance_uid = str(
            event.request.RequestedSOPInstanceUID  # type: ignore[union-attr]
        )

        logger.info("mpps.n_set", sop_instance_uid=sop_instance_uid)

        if sop_instance_uid not in self._instances:
            logger.warning("mpps.unknown_instance", sop_instance_uid=sop_instance_uid)
            return 0x0110, None

        # Issue #14 — validate state machine transition
        current = self._current_status(sop_instance_uid)
        if current != MPPS_STATUS_IN_PROGRESS:
            logger.warning(
                "mpps.invalid_transition_from_terminal",
                sop_instance_uid=sop_instance_uid,
                current_status=current,
            )
            return 0x0110, None

        new_status = str(getattr(mod_list, "PerformedProcedureStepStatus", "")).strip()
        if new_status not in MPPS_TERMINAL_STATUSES:
            logger.warning(
                "mpps.invalid_target_status",
                sop_instance_uid=sop_instance_uid,
                new_status=new_status,
            )
            return 0x0110, None

        # Apply modification list to stored dataset
        stored = self._instances[sop_instance_uid]
        for elem in mod_list:
            stored.add(elem)

        mpps_data = extract_mpps_data(stored)
        if not self._invoke_callback(sop_instance_uid, mpps_data):
            return 0xC001, None

        response = _make_mpps_response(Dataset())
        return 0x0000, response

    def _invoke_callback(self, mpps_uid: str, mpps_data: dict[str, Any]) -> bool:
        """Invoke the async status callback from the sync pynetdicom thread.

        Returns:
            True if the callback succeeded (or no callback configured), False on failure.
        """
        if self._status_callback and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._status_callback(mpps_uid, mpps_data), self._loop
            )
            try:
                future.result(timeout=5.0)  # Reduced from 10 s to bound thread time
            except Exception:
                logger.exception("mpps.callback_error", mpps_uid=mpps_uid)
                return False
        return True

    def start(self) -> None:
        """Start the MPPS SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)
        # Issue #9 — register with all 8 supported transfer syntaxes
        self._ae.add_supported_context(MPPS_SOP_CLASS, TRANSFER_SYNTAXES)

        handlers = [
            (evt.EVT_N_CREATE, self._handle_n_create),
            (evt.EVT_N_SET, self._handle_n_set),
        ]
        self._ae.start_server(
            (self._bind_address, self.port),
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
