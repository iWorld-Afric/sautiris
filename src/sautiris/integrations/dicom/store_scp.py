"""DICOM C-STORE SCP receiver using pynetdicom.

Receives DICOM instances from modalities and invokes a callback
to forward them to PACS (via the PACSAdapter) or process them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import json
import os
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import structlog
from pynetdicom import AE, evt  # AE imported here so tests can patch this module's AE

from sautiris.integrations.dicom.base_scp import BaseSCPServer
from sautiris.integrations.dicom.constants import DEFAULT_TRANSFER_SYNTAXES, DicomHandlerList

# Re-exported for backwards compatibility with existing imports.
# #29: new code should import DEFAULT_TRANSFER_SYNTAXES from constants directly.
TRANSFER_SYNTAXES = DEFAULT_TRANSFER_SYNTAXES

if TYPE_CHECKING:
    from pynetdicom.events import Event

    from sautiris.integrations.dicom.security import DicomAssociationSecurity  # noqa: F401

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Storage SOP Class UIDs — Issue #7: expanded to 25+ classes
# ---------------------------------------------------------------------------

# Original 8 modality classes
CT_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.2"
MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
CR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.1"
DX_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.1.1"
US_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.6.1"
SC_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.7"
ENHANCED_CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2.1"
ENHANCED_MR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.1"

# Digital Mammography (3 UIDs)
DIGITAL_MAMMO_STORAGE = "1.2.840.10008.5.1.4.1.1.1.2"
DIGITAL_MAMMO_PRESENTATION = "1.2.840.10008.5.1.4.1.1.1.2.1"
BREAST_TOMOSYNTHESIS_STORAGE = "1.2.840.10008.5.1.4.1.1.13.1.3"

# Nuclear Medicine / PET
NM_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.20"
PET_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.128"

# X-Ray Angiography / Fluoroscopy
XA_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.12.1"
ENHANCED_XA_STORAGE = "1.2.840.10008.5.1.4.1.1.12.1.1"
RF_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.12.2"

# Structured Reporting
BASIC_SR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.11"   # Basic Text SR
RDSR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.67"        # Radiation Dose SR
ENHANCED_SR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.22" # Enhanced SR
COMPREHENSIVE_SR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.33"  # Comprehensive SR
KEY_OBJECT_SELECTION = "1.2.840.10008.5.1.4.1.1.88.59"  # Key Object Selection

# Documents / Presentation
ENCAPSULATED_PDF = "1.2.840.10008.5.1.4.1.1.104.1"
GRAYSCALE_SOFTCOPY_PS = "1.2.840.10008.5.1.4.1.1.11.1"  # Grayscale Softcopy PS

# Radiotherapy
RT_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.481.1"

# Endoscopy / Microscopy
VL_ENDOSCOPIC_STORAGE = "1.2.840.10008.5.1.4.1.1.77.1.1"

# Segmentation
SEGMENTATION_STORAGE = "1.2.840.10008.5.1.4.1.1.66.4"

# Ultrasound Multi-frame
US_MULTIFRAME_STORAGE = "1.2.840.10008.5.1.4.1.1.3.1"

# MR Spectroscopy
MR_SPECTROSCOPY_STORAGE = "1.2.840.10008.5.1.4.1.1.4.2"

# Enhanced MR Color Image
ENHANCED_MR_COLOR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.3"

DEFAULT_STORAGE_SOP_CLASSES: list[str] = [
    # Core modalities
    CT_IMAGE_STORAGE,
    MR_IMAGE_STORAGE,
    CR_IMAGE_STORAGE,
    DX_IMAGE_STORAGE,
    US_IMAGE_STORAGE,
    SC_IMAGE_STORAGE,
    ENHANCED_CT_STORAGE,
    ENHANCED_MR_STORAGE,
    # Digital Mammography
    DIGITAL_MAMMO_STORAGE,
    DIGITAL_MAMMO_PRESENTATION,
    BREAST_TOMOSYNTHESIS_STORAGE,
    # NM / PET
    NM_IMAGE_STORAGE,
    PET_IMAGE_STORAGE,
    # XA / RF
    XA_IMAGE_STORAGE,
    ENHANCED_XA_STORAGE,
    RF_IMAGE_STORAGE,
    # Structured Reporting (RDSR routes to dose pipeline)
    BASIC_SR_STORAGE,
    RDSR_STORAGE,
    ENHANCED_SR_STORAGE,
    COMPREHENSIVE_SR_STORAGE,
    KEY_OBJECT_SELECTION,
    # Documents / Presentation
    ENCAPSULATED_PDF,
    GRAYSCALE_SOFTCOPY_PS,
    # Radiotherapy
    RT_IMAGE_STORAGE,
    # Endoscopy
    VL_ENDOSCOPIC_STORAGE,
    # Segmentation
    SEGMENTATION_STORAGE,
    # Additional MR / US
    US_MULTIFRAME_STORAGE,
    MR_SPECTROSCOPY_STORAGE,
    ENHANCED_MR_COLOR_STORAGE,
]


def extract_store_metadata(dataset: Any) -> dict[str, str]:
    """Extract key metadata from a received DICOM dataset.

    Returns a dict with study/series/instance UIDs and patient info
    for logging and routing purposes.
    """
    return {
        "study_instance_uid": str(getattr(dataset, "StudyInstanceUID", "")),
        "series_instance_uid": str(getattr(dataset, "SeriesInstanceUID", "")),
        "sop_instance_uid": str(getattr(dataset, "SOPInstanceUID", "")),
        "sop_class_uid": str(getattr(dataset, "SOPClassUID", "")),
        "patient_id": str(getattr(dataset, "PatientID", "")),
        "modality": str(getattr(dataset, "Modality", "")),
    }


def is_rdsr(sop_class_uid: str) -> bool:
    """Return True if the SOP class is a Radiation Dose Structured Report."""
    return sop_class_uid == RDSR_STORAGE


class StoreSCPServer(BaseSCPServer):
    """C-STORE SCP receiver.

    Accepts incoming DICOM instances and invokes a callback for each
    received dataset (e.g., to forward to PACS via STOW-RS).

    RDSR instances (Radiation Dose SR) are additionally routed to the
    dose extraction pipeline via ``rdsr_callback``.

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        store_callback: Async callable that receives (dataset_bytes, metadata_dict)
            for each received DICOM instance.
        rdsr_callback: Optional async callable for RDSR routing (dose pipeline).
        loop: The asyncio event loop to run async callbacks on.
        storage_sop_classes: List of Storage SOP Class UIDs to accept.
        bind_address: IP address to bind to (default ``"127.0.0.1"``).
        security: Optional DicomAssociationSecurity for AE whitelist/rate/connection limits.
        tls_cert: Path to TLS certificate file.  Empty string disables TLS.
        tls_key: Path to TLS private key file.  Empty string disables TLS.
        tls_ca_cert: Path to CA certificate for mutual TLS.  Empty string
            disables client verification.
        dead_letter_dir: Optional directory path for persisting failed RDSR datasets
            and timed-out store operations.  When provided, datasets that cannot be
            processed are written here for later reprocessing (#16).
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_STORE",
        port: int = 11114,
        store_callback: (
            Callable[[bytes, dict[str, str]], Coroutine[Any, Any, None]] | None
        ) = None,
        rdsr_callback: (Callable[[Any, dict[str, str]], Coroutine[Any, Any, None]] | None) = None,
        loop: asyncio.AbstractEventLoop | None = None,
        storage_sop_classes: list[str] | None = None,
        bind_address: str = "127.0.0.1",
        security: DicomAssociationSecurity | None = None,
        tls_cert: str = "",
        tls_key: str = "",
        tls_ca_cert: str = "",
        dead_letter_dir: str | None = None,
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
        self._store_callback = store_callback
        self._rdsr_callback = rdsr_callback
        self._storage_sop_classes = storage_sop_classes or DEFAULT_STORAGE_SOP_CLASSES
        self._dead_letter_dir = dead_letter_dir
        self._ae = None
        self._received_count: int = 0

    # ------------------------------------------------------------------
    # BaseSCPServer interface
    # ------------------------------------------------------------------

    def _make_ae(self) -> AE:
        """Use this module's AE so that ``patch('...store_scp.AE')`` works in tests."""
        return AE(ae_title=self.ae_title)

    def _get_sop_classes_and_handlers(self) -> tuple[list[str], DicomHandlerList]:
        return self._storage_sop_classes, [(evt.EVT_C_STORE, self._handle_store)]

    def _log_started(self, tls_enabled: bool) -> None:
        logger.info(
            "store_scp.server_started",
            ae_title=self.ae_title,
            port=self.port,
            sop_classes=len(self._storage_sop_classes),
            tls_enabled=tls_enabled,
        )

    # ------------------------------------------------------------------
    # Dead-letter helpers
    # ------------------------------------------------------------------

    def _persist_dead_letter(self, dataset: Any, metadata: dict[str, str], reason: str) -> None:
        """Persist a dataset to the dead-letter directory if configured.

        Args:
            dataset: The pydicom Dataset to persist.
            metadata: Metadata dict from :func:`extract_store_metadata`.
            reason: Short label for why the dataset is being dead-lettered
                (e.g. ``"rdsr_callback_failed"`` or ``"store_timeout"``).
        """
        sop_uid = metadata.get("sop_instance_uid", "unknown")
        if not self._dead_letter_dir:
            return
        try:
            os.makedirs(self._dead_letter_dir, exist_ok=True)
            safe_uid = sop_uid.replace(".", "_")
            dcm_path = os.path.join(self._dead_letter_dir, f"{safe_uid}__{reason}.dcm")
            meta_path = os.path.join(self._dead_letter_dir, f"{safe_uid}__{reason}.json")
            buf = io.BytesIO()
            dataset.save_as(buf, write_like_original=False)
            with open(dcm_path, "wb") as fh:
                fh.write(buf.getvalue())
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump({**metadata, "reason": reason}, fh)
            logger.info(
                "store_scp.dead_letter_written",
                path=dcm_path,
                sop_instance_uid=sop_uid,
                reason=reason,
            )
        except Exception:
            logger.exception(
                "store_scp.dead_letter_write_failed",
                sop_instance_uid=sop_uid,
                reason=reason,
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def received_count(self) -> int:
        """Number of instances received since server started."""
        return self._received_count

    # ------------------------------------------------------------------
    # C-STORE handler
    # ------------------------------------------------------------------

    def _handle_store(self, event: Event) -> int:
        """Handle a C-STORE request from a modality."""
        dataset = event.dataset
        dataset.file_meta = event.file_meta

        # #23: verify SpecificCharacterSet on incoming datasets
        charset = getattr(dataset, "SpecificCharacterSet", None)
        sop_uid_for_log = str(getattr(dataset, "SOPInstanceUID", ""))
        if charset is None:
            logger.warning(
                "dicom.missing_charset",
                sop_instance_uid=sop_uid_for_log,
                msg="Incoming dataset has no SpecificCharacterSet tag",
            )
        else:
            logger.info(
                "dicom.incoming_charset",
                sop_instance_uid=sop_uid_for_log,
                charset=str(charset),
            )

        metadata = extract_store_metadata(dataset)
        self._received_count += 1

        logger.info(
            "store_scp.received",
            sop_instance_uid=metadata["sop_instance_uid"],
            modality=metadata["modality"],
            sop_class_uid=metadata["sop_class_uid"],
            count=self._received_count,
        )

        # Issue #7 — route RDSR to dose extraction pipeline.
        # Fire-and-forget: blocking 30 s here would stall the pynetdicom thread
        # pool under load.  Failures are dead-lettered for manual reprocessing (#16).
        if is_rdsr(metadata["sop_class_uid"]) and self._rdsr_callback and self._loop:
            sop_uid = metadata["sop_instance_uid"]
            # Capture dataset reference and dead_letter_dir for the closure
            _dataset_snapshot = dataset
            _dead_letter_dir = self._dead_letter_dir
            rdsr_future = asyncio.run_coroutine_threadsafe(
                self._rdsr_callback(dataset, metadata), self._loop
            )

            def _log_rdsr_error(f: concurrent.futures.Future[None]) -> None:
                exc = f.exception()
                if exc is not None:
                    if _dead_letter_dir:
                        # #16: persist RDSR to dead-letter dir for reprocessing
                        self._persist_dead_letter(
                            _dataset_snapshot, metadata, "rdsr_callback_failed"
                        )
                    # #16: RDSR dose data loss is a CRITICAL operational event.
                    # Log at ERROR level so that existing structured-log monitors
                    # (and pre-existing tests) capture the event; include a
                    # severity field to flag it for CRITICAL alerting pipelines.
                    logger.error(
                        "store_scp.rdsr_callback_error",
                        sop_instance_uid=sop_uid,
                        study_instance_uid=metadata.get("study_instance_uid", ""),
                        error=str(exc),
                        severity="CRITICAL",
                        dead_letter_persisted=_dead_letter_dir is not None,
                        msg=(
                            "RDSR dose data lost — persisted to dead-letter dir"
                            if _dead_letter_dir
                            else "RDSR dose data lost — no dead-letter dir configured,"
                            " manual reprocessing required"
                        ),
                    )

            rdsr_future.add_done_callback(_log_rdsr_error)

        if self._store_callback and self._loop:
            buffer = io.BytesIO()
            dataset.save_as(buffer, write_like_original=False)
            dicom_bytes = buffer.getvalue()

            sop_uid = metadata["sop_instance_uid"]

            def _log_store_deferred_error(f: concurrent.futures.Future[None]) -> None:
                if f.cancelled():
                    return
                exc = f.exception()
                if exc is not None:
                    logger.error(
                        "dicom.store_callback_deferred_error",
                        sop_instance_uid=sop_uid,
                        error=str(exc),
                        msg="Store callback failed after timeout — instance may not be persisted",
                    )

            future = asyncio.run_coroutine_threadsafe(
                self._store_callback(dicom_bytes, metadata), self._loop
            )
            future.add_done_callback(_log_store_deferred_error)
            try:
                future.result(timeout=5.0)  # Reduced from 30 s to bound thread time
            except concurrent.futures.TimeoutError:
                # #17: Upgrade to error-level; returning SUCCESS here is a deliberate
                # trade-off: the callback is still in-flight and may succeed, so
                # returning a failure status could cause the modality to resend the
                # same instance, risking duplicates.  The deferred error callback
                # above will log any actual failure.
                logger.error(
                    "dicom.store_callback_timeout",
                    sop_instance_uid=metadata["sop_instance_uid"],
                    msg=(
                        "Store callback timed out after 5 s — returning SUCCESS to avoid "
                        "modality retries that could cause duplicate instances; "
                        "callback is still running and may complete successfully"
                    ),
                )
                # #17: also dead-letter the raw dataset on timeout so it can be
                # replayed if the in-flight callback ultimately fails.
                if self._dead_letter_dir:
                    self._persist_dead_letter(dataset, metadata, "store_timeout")
                return 0x0000  # image received, callback in-flight
            except Exception:
                logger.exception(
                    "dicom.store_callback_error",
                    sop_instance_uid=metadata["sop_instance_uid"],
                )
                return 0xC001

        return 0x0000  # Success

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop the C-STORE SCP."""
        super().stop()
        logger.info(
            "store_scp.server_stopped",
            total_received=self._received_count,
        )
