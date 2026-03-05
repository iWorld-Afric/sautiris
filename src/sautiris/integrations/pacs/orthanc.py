"""Orthanc PACS adapter — DICOMweb (QIDO-RS, WADO-RS, STOW-RS) client.

Communicates with an Orthanc server via its DICOMweb plugin endpoints.
Follows the same async httpx pattern as SautiCare's DICOMwebClient.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import structlog

from sautiris.integrations.pacs.base import PACSAdapter

logger = structlog.get_logger(__name__)

DICOM_JSON = "application/dicom+json"


class OrthancPACSAdapter(PACSAdapter):
    """Orthanc DICOMweb adapter.

    Args:
        base_url: Orthanc server base URL (e.g. ``http://localhost:8042``).
        dicomweb_root: DICOMweb endpoint path (default ``/dicom-web``).
        username: HTTP Basic auth username.
        password: HTTP Basic auth password.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8042",
        dicomweb_root: str = "/dicom-web",
        username: str = "",
        password: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dicomweb_root = dicomweb_root.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the async HTTP client."""
        if self._client is None or self._client.is_closed:
            auth = (self._username, self._password) if self._username else None
            self._client = httpx.AsyncClient(
                base_url=f"{self._base_url}{self._dicomweb_root}",
                auth=auth,
                timeout=self._timeout,
                headers={"Accept": DICOM_JSON},
            )
        return self._client

    @staticmethod
    def _validate_uid(uid: str) -> None:
        """Validate DICOM UID format (numeric + dots, max 64 chars)."""
        if not uid or not re.match(r"^[0-9.]+$", uid) or len(uid) > 64:
            raise ValueError(f"Invalid DICOM UID: {uid!r}")

    # ------------------------------------------------------------------
    # QIDO-RS
    # ------------------------------------------------------------------

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
        client = await self._ensure_client()
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if patient_id:
            params["PatientID"] = re.sub(r"[^a-zA-Z0-9-]", "", patient_id)
        if patient_name:
            params["PatientName"] = patient_name
        if study_date:
            params["StudyDate"] = study_date
        if modality:
            params["ModalitiesInStudy"] = modality
        if accession_number:
            params["AccessionNumber"] = accession_number

        logger.info("orthanc.qido_search_studies", params=params)
        resp = await client.get("/studies", params=params)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def search_series(self, study_instance_uid: str) -> list[dict[str, Any]]:
        self._validate_uid(study_instance_uid)
        client = await self._ensure_client()
        resp = await client.get(f"/studies/{study_instance_uid}/series")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def search_instances(
        self,
        study_instance_uid: str,
        series_instance_uid: str | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_uid(study_instance_uid)
        if series_instance_uid:
            self._validate_uid(series_instance_uid)
        client = await self._ensure_client()
        if series_instance_uid:
            path = f"/studies/{study_instance_uid}/series/{series_instance_uid}/instances"
        else:
            path = f"/studies/{study_instance_uid}/instances"
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # WADO-RS
    # ------------------------------------------------------------------

    async def retrieve_study_metadata(
        self,
        study_instance_uid: str,
    ) -> list[dict[str, Any]]:
        self._validate_uid(study_instance_uid)
        client = await self._ensure_client()
        resp = await client.get(f"/studies/{study_instance_uid}/metadata")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def retrieve_instance(
        self,
        study_instance_uid: str,
        series_instance_uid: str,
        instance_uid: str,
    ) -> bytes:
        self._validate_uid(study_instance_uid)
        self._validate_uid(series_instance_uid)
        self._validate_uid(instance_uid)
        client = await self._ensure_client()
        path = (
            f"/studies/{study_instance_uid}/series/{series_instance_uid}/instances/{instance_uid}"
        )
        resp = await client.get(
            path,
            headers={"Accept": "multipart/related; type=application/dicom"},
        )
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # STOW-RS
    # ------------------------------------------------------------------

    async def store_instances(
        self,
        study_instance_uid: str,
        dicom_data: bytes,
    ) -> dict[str, Any]:
        self._validate_uid(study_instance_uid)
        client = await self._ensure_client()
        boundary = "----DICOMwebBoundary"
        body = (
            f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode()
            + dicom_data
            + f"\r\n--{boundary}--\r\n".encode()
        )
        logger.info("orthanc.stow_store", study_uid=study_instance_uid, size=len(dicom_data))
        resp = await client.post(
            f"/studies/{study_instance_uid}",
            content=body,
            headers={
                "Content-Type": (f"multipart/related; type=application/dicom; boundary={boundary}"),
            },
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------

    async def delete_study(self, study_instance_uid: str) -> bool:
        """Delete study via Orthanc's native REST API (not DICOMweb)."""
        self._validate_uid(study_instance_uid)
        auth = (self._username, self._password) if self._username else None
        async with httpx.AsyncClient(
            base_url=self._base_url,
            auth=auth,
            timeout=self._timeout,
        ) as client:
            resp = await client.post("/tools/lookup", json=study_instance_uid)
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return False
            orthanc_id = results[0]["ID"]
            del_resp = await client.delete(f"/studies/{orthanc_id}")
            del_resp.raise_for_status()
            logger.info("orthanc.study_deleted", study_uid=study_instance_uid)
            return True

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        try:
            client = await self._ensure_client()
            resp = await client.get("/studies", params={"limit": 1})
            resp.raise_for_status()
            return {"status": "ok", "pacs": "orthanc", "dicomweb": "reachable"}
        except httpx.HTTPError as exc:
            logger.warning("orthanc.health_check_failed", error=str(exc))
            return {"status": "error", "pacs": "orthanc", "detail": str(exc)}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
