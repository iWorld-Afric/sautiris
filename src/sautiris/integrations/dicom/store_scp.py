"""DICOM C-STORE SCP receiver using pynetdicom.

Receives DICOM instances from modalities and invokes a callback
to forward them to PACS (via the PACSAdapter) or process them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

import structlog
from pynetdicom import AE, evt

if TYPE_CHECKING:
    from pynetdicom.events import Event

logger = structlog.get_logger(__name__)

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
RDSR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.67"           # Radiation Dose SR
ENHANCED_SR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.22"    # Enhanced SR
COMPREHENSIVE_SR_STORAGE = "1.2.840.10008.5.1.4.1.1.88.33"  # Comprehensive SR
KEY_OBJECT_SELECTION = "1.2.840.10008.5.1.4.1.1.88.59"    # Key Object Selection

# Documents / Presentation
ENCAPSULATED_PDF = "1.2.840.10008.5.1.4.1.1.104.1"
GRAYSCALE_SOFTCOPY_PS = "1.2.840.10008.5.1.4.1.1.11.1"   # Grayscale Softcopy PS

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


class StoreSCPServer:
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
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_STORE",
        port: int = 11114,
        store_callback: Callable[[bytes, dict[str, str]], Coroutine[Any, Any, None]] | None = None,
        rdsr_callback: Callable[[Any, dict[str, str]], Coroutine[Any, Any, None]] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        storage_sop_classes: list[str] | None = None,
        bind_address: str = "127.0.0.1",
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._store_callback = store_callback
        self._rdsr_callback = rdsr_callback
        self._loop = loop
        self._storage_sop_classes = storage_sop_classes or DEFAULT_STORAGE_SOP_CLASSES
        self._bind_address = bind_address
        self._ae: AE | None = None
        self._received_count: int = 0

    @property
    def received_count(self) -> int:
        """Number of instances received since server started."""
        return self._received_count

    def _handle_store(self, event: Event) -> int:
        """Handle a C-STORE request from a modality."""
        dataset = event.dataset
        dataset.file_meta = event.file_meta

        metadata = extract_store_metadata(dataset)
        self._received_count += 1

        logger.info(
            "store_scp.received",
            sop_instance_uid=metadata["sop_instance_uid"],
            modality=metadata["modality"],
            sop_class_uid=metadata["sop_class_uid"],
            count=self._received_count,
        )

        # Issue #7 — route RDSR to dose extraction pipeline (fire-and-forget;
        # blocking 30 s here would stall the pynetdicom thread pool under load).
        if is_rdsr(metadata["sop_class_uid"]) and self._rdsr_callback and self._loop:
            sop_uid = metadata["sop_instance_uid"]
            rdsr_future = asyncio.run_coroutine_threadsafe(
                self._rdsr_callback(dataset, metadata), self._loop
            )

            def _log_rdsr_error(f: concurrent.futures.Future[None]) -> None:
                exc = f.exception()
                if exc is not None:
                    # Log with full identifiers so operators can manually reprocess.
                    # TODO: Future enhancement — persist failed RDSRs to a dead-letter
                    # queue for automatic reprocessing.
                    logger.error(
                        "store_scp.rdsr_callback_error",
                        sop_instance_uid=sop_uid,
                        study_instance_uid=metadata.get("study_instance_uid", ""),
                        error=str(exc),
                        msg="RDSR dose data may be lost — manual reprocessing required",
                    )

            rdsr_future.add_done_callback(_log_rdsr_error)

        if self._store_callback and self._loop:
            import io

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
                logger.warning(
                    "dicom.store_callback_timeout",
                    sop_instance_uid=metadata["sop_instance_uid"],
                    msg="Store callback still running — returning success",
                )
                return 0x0000  # image received, callback in-flight
            except Exception:
                logger.exception(
                    "dicom.store_callback_error",
                    sop_instance_uid=metadata["sop_instance_uid"],
                )
                return 0xC001

        return 0x0000  # Success

    def start(self) -> None:
        """Start the C-STORE SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)

        # Issue #9 — register all SOP classes with all 8 transfer syntaxes
        for sop_class in self._storage_sop_classes:
            self._ae.add_supported_context(sop_class, TRANSFER_SYNTAXES)

        handlers = [(evt.EVT_C_STORE, self._handle_store)]
        self._ae.start_server(
            (self._bind_address, self.port),
            block=False,
            evt_handlers=handlers,  # type: ignore[arg-type]
        )
        logger.info(
            "store_scp.server_started",
            ae_title=self.ae_title,
            port=self.port,
            sop_classes=len(self._storage_sop_classes),
        )

    def stop(self) -> None:
        """Stop the C-STORE SCP."""
        if self._ae:
            self._ae.shutdown()
            self._ae = None
            logger.info(
                "store_scp.server_stopped",
                total_received=self._received_count,
            )
