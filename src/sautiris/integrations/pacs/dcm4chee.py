"""dcm4chee PACS adapter stub.

Implements the PACSAdapter interface for dcm4chee Arc. Currently a stub
with NotImplementedError on all methods — ready for future implementation.
"""

from __future__ import annotations

from typing import Any

from sautiris.integrations.pacs.base import PACSAdapter


class DCM4CheePACSAdapter(PACSAdapter):
    """dcm4chee Arc DICOMweb adapter (stub).

    All methods raise NotImplementedError until dcm4chee support is implemented.
    """

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
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def search_series(self, study_instance_uid: str) -> list[dict[str, Any]]:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def search_instances(
        self,
        study_instance_uid: str,
        series_instance_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def retrieve_study_metadata(
        self,
        study_instance_uid: str,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def retrieve_instance(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        instance_uid: str,
    ) -> bytes:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def store_instances(
        self,
        study_instance_uid: str,
        dicom_data: bytes,
    ) -> dict[str, Any]:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def delete_study(self, study_instance_uid: str) -> bool:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def health_check(self) -> dict[str, Any]:
        raise NotImplementedError("dcm4chee adapter not yet implemented")

    async def close(self) -> None:
        pass  # No client to close in stub
