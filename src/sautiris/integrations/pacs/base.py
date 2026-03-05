"""Abstract base class for PACS (Picture Archiving and Communication System) adapters.

Defines the DICOMweb interface that all PACS adapter implementations must follow:
QIDO-RS (Query), WADO-RS (Retrieve), STOW-RS (Store).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PACSAdapter(ABC):
    """Abstract PACS adapter — DICOMweb (QIDO-RS, WADO-RS, STOW-RS) interface."""

    # ------------------------------------------------------------------
    # QIDO-RS: Query
    # ------------------------------------------------------------------

    @abstractmethod
    async def search_studies(
        self,
        patient_id: str | None = None,
        patient_name: str | None = None,
        study_date: str | None = None,
        modality: str | None = None,
        accession_number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Search for studies using QIDO-RS.

        Returns list of DICOM JSON study metadata dicts.
        """

    @abstractmethod
    async def search_series(self, study_instance_uid: str) -> list[dict[str, Any]]:
        """Search for series in a study."""

    @abstractmethod
    async def search_instances(
        self,
        study_instance_uid: str,
        series_instance_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for instances in a study or series."""

    # ------------------------------------------------------------------
    # WADO-RS: Retrieve
    # ------------------------------------------------------------------

    @abstractmethod
    async def retrieve_study_metadata(
        self,
        study_instance_uid: str,
    ) -> list[dict[str, Any]]:
        """Retrieve study-level metadata (WADO-RS)."""

    @abstractmethod
    async def retrieve_instance(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        instance_uid: str,
    ) -> bytes:
        """Retrieve a single DICOM instance (WADO-RS)."""

    # ------------------------------------------------------------------
    # STOW-RS: Store
    # ------------------------------------------------------------------

    @abstractmethod
    async def store_instances(
        self,
        study_instance_uid: str,
        dicom_data: bytes,
    ) -> dict[str, Any]:
        """Store DICOM instances via STOW-RS."""

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    @abstractmethod
    async def delete_study(self, study_instance_uid: str) -> bool:
        """Delete a study from PACS. Returns True on success."""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check PACS connectivity. Returns dict with 'status' key."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def close(self) -> None:
        """Close underlying HTTP client connections."""
