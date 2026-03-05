"""Abstract base class for DICOM viewer adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ViewerAdapter(ABC):
    """Abstract viewer adapter for launching DICOM study viewers."""

    @abstractmethod
    def build_study_url(self, study_instance_uid: str) -> str:
        """Build the URL to open a specific study in the viewer.

        Args:
            study_instance_uid: DICOM Study Instance UID (e.g. ``1.2.3.4...``).

        Returns:
            Full URL to launch the viewer for this study.
        """

    @abstractmethod
    def build_config(self) -> dict[str, Any]:
        """Build the viewer configuration (e.g. data source config JSON).

        Returns:
            Configuration dict suitable for the viewer's setup.
        """

    @abstractmethod
    def get_launch_url(
        self,
        study_instance_uid: str,
        series_instance_uid: str | None = None,
    ) -> str:
        """Build a launch URL with optional series-level targeting.

        Args:
            study_instance_uid: DICOM Study Instance UID.
            series_instance_uid: Optional DICOM Series Instance UID.

        Returns:
            URL to launch the viewer.
        """
