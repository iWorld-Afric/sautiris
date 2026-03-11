"""DICOM Modality Performed Procedure Step (MPPS) SCP using pynetdicom.

Handles N-CREATE and N-SET requests from modalities to track procedure
step status (IN PROGRESS, COMPLETED, DISCONTINUED).

Issue #14: Implements proper state machine validation:
  - N-CREATE only allowed with status "IN PROGRESS"
  - N-SET only allowed from "IN PROGRESS" -> "COMPLETED" | "DISCONTINUED"
  - Invalid transitions return DIMSE status 0x0110
"""

from __future__ import annotations

import asyncio
import copy
import threading
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import structlog
from pydicom.dataset import Dataset
from pynetdicom import AE, evt  # AE imported here so tests can patch this module's AE

from sautiris.integrations.dicom.base_scp import BaseSCPServer
from sautiris.integrations.dicom.constants import (
    CHARSET_UTF8,
    DicomHandlerList,
)
from sautiris.models.mpps import MPPSStatusEnum

if TYPE_CHECKING:
    from pynetdicom.events import Event

    from sautiris.integrations.dicom.security import DicomAssociationSecurity  # noqa: F401

logger = structlog.get_logger(__name__)

# MPPS SOP Class UID
MPPS_SOP_CLASS = "1.2.840.10008.3.1.2.3.3"

# Issue #14 — valid target statuses reachable via N-SET from IN PROGRESS
MPPS_TERMINAL_STATUSES: frozenset[MPPSStatusEnum] = frozenset(
    {MPPSStatusEnum.COMPLETED, MPPSStatusEnum.DISCONTINUED}
)

# PS3.4 F.7.2 — required Type 1 attributes for N-CREATE
NCREATE_REQUIRED_ATTRS: tuple[str, ...] = (
    "PerformedProcedureStepID",
    "PerformedStationAETitle",
    "PerformedProcedureStepStartDate",
    "PerformedProcedureStepStartTime",
)

# PS3.4 F.7.2 — required Type 1 attributes for N-SET to COMPLETED
NSET_COMPLETED_REQUIRED_ATTRS: tuple[str, ...] = (
    "PerformedProcedureStepEndDate",
    "PerformedProcedureStepEndTime",
)

# PS3.4 F.7.2 — required Type 1 attributes for N-SET to DISCONTINUED
NSET_DISCONTINUED_REQUIRED_ATTRS: tuple[str, ...] = (
    "PerformedProcedureStepEndDate",
    "PerformedProcedureStepEndTime",
    "PerformedProcedureStepDiscontinuationReasonCodeSequence",
)


def extract_mpps_data(dataset: Dataset) -> dict[str, Any]:
    """Extract relevant MPPS data from a DICOM dataset.

    Parses the N-CREATE or N-SET dataset and returns a dict with:
    - mpps_status: "IN PROGRESS", "COMPLETED", or "DISCONTINUED"
    - performed_procedure_step_id: The SPS ID being performed
    - performed_station_ae_title: AE title of the performing modality
    - accession_number: From the Scheduled Step Attributes Sequence
    - study_instance_uid: From the Scheduled Step Attributes Sequence

    Issue #24: also extracts PerformedSeriesSequence and additional
    procedure-step timing / protocol fields:
    - performed_series_sequence: serialised list of series-level data
    - performed_protocol_code_sequence: list of code items
    - performed_procedure_step_start_date / _start_time
    - performed_procedure_step_end_date / _end_time
    - performed_procedure_step_description
    - comments_on_performed_procedure_step
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

    # ---------------------------------------------------------------
    # Issue #24 — additional attributes
    # ---------------------------------------------------------------

    # Timing fields
    for field, key in (
        ("PerformedProcedureStepStartDate", "performed_procedure_step_start_date"),
        ("PerformedProcedureStepStartTime", "performed_procedure_step_start_time"),
        ("PerformedProcedureStepEndDate", "performed_procedure_step_end_date"),
        ("PerformedProcedureStepEndTime", "performed_procedure_step_end_time"),
    ):
        val = getattr(dataset, field, None)
        if val is not None:
            data[key] = str(val).strip()

    # Free-text description and comments
    description = getattr(dataset, "PerformedProcedureStepDescription", None)
    if description is not None:
        data["performed_procedure_step_description"] = str(description).strip()

    comments = getattr(dataset, "CommentsOnThePerformedProcedureStep", None)
    if comments is not None:
        data["comments_on_performed_procedure_step"] = str(comments).strip()

    # PerformedProtocolCodeSequence — list of code items
    ppc_seq = getattr(dataset, "PerformedProtocolCodeSequence", None)
    if ppc_seq is not None:
        codes: list[dict[str, str]] = []
        for item in ppc_seq:
            codes.append(
                {
                    "code_value": str(getattr(item, "CodeValue", "") or ""),
                    "coding_scheme_designator": str(
                        getattr(item, "CodingSchemeDesignator", "") or ""
                    ),
                    "code_meaning": str(getattr(item, "CodeMeaning", "") or ""),
                }
            )
        data["performed_protocol_code_sequence"] = codes

    # PerformedSeriesSequence — list of series-level data
    pss_seq = getattr(dataset, "PerformedSeriesSequence", None)
    if pss_seq is not None:
        series_list: list[dict[str, Any]] = []
        for series_item in pss_seq:
            series_entry: dict[str, Any] = {
                "series_instance_uid": str(getattr(series_item, "SeriesInstanceUID", "") or ""),
                "series_description": str(getattr(series_item, "SeriesDescription", "") or ""),
                "performing_physicians_name": str(
                    getattr(series_item, "PerformingPhysicianName", "") or ""
                ),
                "protocol_name": str(getattr(series_item, "ProtocolName", "") or ""),
                "operators_name": str(getattr(series_item, "OperatorsName", "") or ""),
            }
            # Referenced Image Sequence within the series
            ref_images = getattr(series_item, "ReferencedImageSequence", None)
            if ref_images is not None:
                series_entry["referenced_image_sequence"] = [
                    {
                        "referenced_sop_class_uid": str(
                            getattr(img, "ReferencedSOPClassUID", "") or ""
                        ),
                        "referenced_sop_instance_uid": str(
                            getattr(img, "ReferencedSOPInstanceUID", "") or ""
                        ),
                    }
                    for img in ref_images
                ]
            series_list.append(series_entry)
        data["performed_series_sequence"] = series_list

    return data


def _make_mpps_response(dataset: Dataset) -> Dataset:
    """Add SpecificCharacterSet to an outbound MPPS response dataset."""
    dataset.SpecificCharacterSet = CHARSET_UTF8
    return dataset


def _validate_required_attrs(
    dataset: Dataset, required: tuple[str, ...], context: str, sop_uid: str
) -> None:
    """Assert that all required DICOM attributes are present and non-empty.

    Issue #49: raises ValueError instead of returning bool so that callers
    can use a try/except pattern and return the appropriate DIMSE status code
    without having to check a return value.

    Args:
        dataset: The DICOM dataset to inspect.
        required: Attribute names that must be present and non-empty.
        context: Human-readable context label for error messages.
        sop_uid: SOP Instance UID for log correlation.

    Raises:
        ValueError: If one or more required attributes are missing or empty.
            The message lists all missing attribute names.
    """
    missing: list[str] = []
    for attr in required:
        val = getattr(dataset, attr, None)
        if val is None or str(val).strip() == "":
            missing.append(attr)
    if missing:
        msg = f"MPPS {context} missing required attrs for {sop_uid}: {', '.join(missing)}"
        logger.warning(
            "mpps.missing_required_attrs",
            missing=missing,
            context=context,
            sop_instance_uid=sop_uid,
        )
        raise ValueError(msg)


class MPPSServer(BaseSCPServer):
    """Modality Performed Procedure Step SCP server.

    Uses pynetdicom to handle N-CREATE and N-SET requests. On each
    request, calls the provided ``status_callback`` to update the
    worklist item status in the database.

    Issue #14: Enforces the MPPS state machine:
    - N-CREATE requires status = "IN PROGRESS" (0x0110 if violated)
    - N-SET validates current->new transition (0x0110 if invalid)
    - Duplicate N-CREATE returns 0x0111

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        status_callback: Async callable that receives (mpps_uid, mpps_data_dict)
            and updates the worklist item.
        loop: The asyncio event loop to run async callbacks on.
        bind_address: IP address to bind to (default ``"127.0.0.1"``).
        security: Optional DicomAssociationSecurity for AE whitelist/rate/connection limits.
        tls_cert: Path to TLS certificate file.  Empty string disables TLS.
        tls_key: Path to TLS private key file.  Empty string disables TLS.
        tls_ca_cert: Path to CA certificate for mutual TLS.  Empty string
            disables client verification.
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_MPPS",
        port: int = 11113,
        status_callback: (Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]] | None) = None,
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
        self._status_callback = status_callback
        # In-memory MPPS instance store: SOP Instance UID -> Dataset
        # Used for state machine tracking; DB persistence handled via callbacks.
        self._instances: dict[str, Dataset] = {}
        # Mutex for atomic duplicate-check + store in N-CREATE (prevents TOCTOU race)
        self._create_lock = threading.Lock()

    # ------------------------------------------------------------------
    # BaseSCPServer interface
    # ------------------------------------------------------------------

    def _make_ae(self) -> AE:
        """Use this module's AE so that ``patch('...mpps_scp.AE')`` works in tests."""
        return AE(ae_title=self.ae_title)

    def _get_sop_classes_and_handlers(self) -> tuple[list[str], DicomHandlerList]:
        return [MPPS_SOP_CLASS], [
            (evt.EVT_N_CREATE, self._handle_n_create),
            (evt.EVT_N_SET, self._handle_n_set),
        ]

    def _log_started(self, tls_enabled: bool) -> None:
        logger.info(
            "mpps.server_started",
            ae_title=self.ae_title,
            port=self.port,
            tls_enabled=tls_enabled,
        )

    # ------------------------------------------------------------------
    # State machine helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # N-CREATE handler
    # ------------------------------------------------------------------

    def _handle_n_create(self, event: Event) -> tuple[int, Dataset | None]:
        """Handle MPPS N-CREATE (procedure step started).

        Issue #14 state machine: initial status MUST be IN PROGRESS.
        """
        attr_list = event.attribute_list
        sop_instance_uid = str(
            event.request.AffectedSOPInstanceUID  # type: ignore[union-attr]
        )

        logger.info("mpps.n_create", sop_instance_uid=sop_instance_uid)

        # Issue #14 — N-CREATE MUST carry status "IN PROGRESS" (validate first,
        # before acquiring lock, since status check has no side effects)
        requested_status = str(getattr(attr_list, "PerformedProcedureStepStatus", "")).strip()
        if requested_status != MPPSStatusEnum.IN_PROGRESS:
            logger.warning(
                "mpps.invalid_initial_status",
                sop_instance_uid=sop_instance_uid,
                status=requested_status,
            )
            return 0x0110, None

        # PS3.4 F.7.2 — validate required Type 1 attributes (#49: raises ValueError)
        try:
            _validate_required_attrs(
                attr_list, NCREATE_REQUIRED_ATTRS, "N-CREATE", sop_instance_uid
            )
        except ValueError:
            return 0x0110, None

        # Atomic duplicate-check + store under lock to prevent TOCTOU race
        # (two concurrent N-CREATEs for the same UID both passing the check
        # before either writes — FIX-6)
        with self._create_lock:
            if sop_instance_uid in self._instances:
                logger.warning(
                    "mpps.duplicate_create",
                    sop_instance_uid=sop_instance_uid,
                )
                return 0x0111, None
            # Store the instance atomically
            self._instances[sop_instance_uid] = attr_list

        mpps_data = extract_mpps_data(attr_list)
        if not self._invoke_callback(sop_instance_uid, mpps_data):
            # Rollback in-memory state: instance was not persisted to DB,
            # so keeping it in _instances would create an inconsistent state
            # where N-SET could succeed against a phantom instance.
            self._instances.pop(sop_instance_uid, None)
            return 0xC001, None

        response = _make_mpps_response(Dataset())
        return 0x0000, response

    # ------------------------------------------------------------------
    # N-SET handler
    # ------------------------------------------------------------------

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
            logger.warning(
                "mpps.unknown_instance",
                sop_instance_uid=sop_instance_uid,
            )
            return 0x0110, None

        # Issue #14 — validate state machine transition
        current = self._current_status(sop_instance_uid)
        if current != MPPSStatusEnum.IN_PROGRESS:
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

        # PS3.4 F.7.2 — COMPLETED requires end date/time (#49: raises ValueError)
        if new_status == MPPSStatusEnum.COMPLETED:
            try:
                _validate_required_attrs(
                    mod_list, NSET_COMPLETED_REQUIRED_ATTRS, "N-SET-COMPLETED", sop_instance_uid
                )
            except ValueError:
                return 0x0110, None

        # PS3.4 F.7.2 — DISCONTINUED requires end date/time AND discontinuation reason
        if new_status == MPPSStatusEnum.DISCONTINUED:
            try:
                _validate_required_attrs(
                    mod_list,
                    NSET_DISCONTINUED_REQUIRED_ATTRS,
                    "N-SET-DISCONTINUED",
                    sop_instance_uid,
                )
            except ValueError:
                return 0x0110, None
            # DiscontinuationReasonCodeSequence must have at least one item
            reason_seq = getattr(
                mod_list, "PerformedProcedureStepDiscontinuationReasonCodeSequence", None
            )
            if reason_seq is not None and len(reason_seq) == 0:
                logger.warning(
                    "mpps.empty_discontinuation_reason_seq",
                    sop_instance_uid=sop_instance_uid,
                )
                return 0x0110, None

        # Build working copy; mutate _instances only after successful callback
        # to prevent irrecoverable state if callback fails (HIGH-4 fix).
        # Must use deepcopy: pydicom Dataset shallow copy shares DataElement
        # references, so add() on the working copy can mutate stored.
        stored = self._instances[sop_instance_uid]
        working = copy.deepcopy(stored)
        for elem in mod_list:
            working.add(elem)

        mpps_data = extract_mpps_data(working)
        if not self._invoke_callback(sop_instance_uid, mpps_data):
            return 0xC001, None

        # Commit to in-memory state only after successful DB write
        for elem in mod_list:
            stored.add(elem)

        response = _make_mpps_response(Dataset())
        return 0x0000, response

    # ------------------------------------------------------------------
    # Callback bridge
    # ------------------------------------------------------------------

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
                future.result(timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "mpps.callback_timeout",
                    mpps_uid=mpps_uid,
                    timeout_seconds=5.0,
                    msg="MPPS callback timed out — DB update may not have completed",
                )
                return False
            except Exception:
                logger.exception("mpps.callback_error", mpps_uid=mpps_uid)
                return False
        return True

    # ------------------------------------------------------------------
    # Preload
    # ------------------------------------------------------------------

    def preload_active_instances(self, instances: dict[str, Dataset]) -> None:
        """Preload active MPPS instances from the database on startup.

        This enables recovery after a server restart: any IN PROGRESS
        instances that were previously tracked can be re-loaded so that
        subsequent N-SET requests succeed.

        Issue #20: only instances with status IN_PROGRESS are loaded.
        Instances with any other status are skipped with a warning.

        Args:
            instances: Mapping of SOP Instance UID -> Dataset with at least
                PerformedProcedureStepStatus set.
        """
        loaded = 0
        skipped = 0
        for uid, dataset in instances.items():
            raw_status = str(getattr(dataset, "PerformedProcedureStepStatus", "")).strip()
            try:
                status = MPPSStatusEnum(raw_status)
            except ValueError:
                logger.warning(
                    "mpps.preload_invalid_status",
                    sop_instance_uid=uid,
                    raw_status=raw_status,
                    msg="Skipping preload — status value is not a recognised MPPSStatusEnum",
                )
                skipped += 1
                continue

            if status != MPPSStatusEnum.IN_PROGRESS:
                logger.warning(
                    "mpps.preload_skip_non_active",
                    sop_instance_uid=uid,
                    status=status,
                    msg="Skipping preload — only IN_PROGRESS instances are preloaded",
                )
                skipped += 1
                continue

            self._instances[uid] = dataset
            loaded += 1

        logger.info("mpps.preload_complete", loaded=loaded, skipped=skipped)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop the MPPS SCP."""
        super().stop()
        self._instances.clear()
        logger.info("mpps.server_stopped")
