"""DICOM C-STORE SCP receiver using pynetdicom.

Receives DICOM instances from modalities and invokes a callback
to forward them to PACS (via the PACSAdapter) or process them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog
from pynetdicom import AE, evt

if TYPE_CHECKING:
    from pynetdicom.events import Event

logger = structlog.get_logger(__name__)

# Common storage SOP Class UIDs
CT_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.2"
MR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.4"
CR_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.1"
DX_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.1.1"
US_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.6.1"
SC_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.7"
ENHANCED_CT_STORAGE = "1.2.840.10008.5.1.4.1.1.2.1"
ENHANCED_MR_STORAGE = "1.2.840.10008.5.1.4.1.1.4.1"

DEFAULT_STORAGE_SOP_CLASSES = [
    CT_IMAGE_STORAGE,
    MR_IMAGE_STORAGE,
    CR_IMAGE_STORAGE,
    DX_IMAGE_STORAGE,
    US_IMAGE_STORAGE,
    SC_IMAGE_STORAGE,
    ENHANCED_CT_STORAGE,
    ENHANCED_MR_STORAGE,
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


class StoreSCPServer:
    """C-STORE SCP receiver.

    Accepts incoming DICOM instances and invokes a callback for each
    received dataset (e.g., to forward to PACS via STOW-RS).

    Args:
        ae_title: Application Entity title for this SCP.
        port: TCP port to listen on.
        store_callback: Async callable that receives (dataset_bytes, metadata_dict)
            for each received DICOM instance.
        loop: The asyncio event loop to run async callbacks on.
        storage_sop_classes: List of Storage SOP Class UIDs to accept.
    """

    def __init__(
        self,
        ae_title: str = "SAUTIRIS_STORE",
        port: int = 11114,
        store_callback: Callable[..., Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
        storage_sop_classes: list[str] | None = None,
    ) -> None:
        self.ae_title = ae_title
        self.port = port
        self._store_callback = store_callback
        self._loop = loop
        self._storage_sop_classes = storage_sop_classes or DEFAULT_STORAGE_SOP_CLASSES
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
            count=self._received_count,
        )

        if self._store_callback and self._loop:
            # Encode dataset to bytes for forwarding
            import io

            buffer = io.BytesIO()
            dataset.save_as(buffer, write_like_original=False)
            dicom_bytes = buffer.getvalue()

            future = asyncio.run_coroutine_threadsafe(
                self._store_callback(dicom_bytes, metadata), self._loop
            )
            try:
                future.result(timeout=30.0)
            except Exception:
                logger.exception(
                    "store_scp.callback_error",
                    sop_instance_uid=metadata["sop_instance_uid"],
                )
                return 0xC001  # Processing failure

        return 0x0000  # Success

    def start(self) -> None:
        """Start the C-STORE SCP in non-blocking mode."""
        self._ae = AE(ae_title=self.ae_title)

        for sop_class in self._storage_sop_classes:
            self._ae.add_supported_context(sop_class)

        handlers = [(evt.EVT_C_STORE, self._handle_store)]
        self._ae.start_server(
            ("0.0.0.0", self.port),
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
