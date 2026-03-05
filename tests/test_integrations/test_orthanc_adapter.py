"""Tests for Orthanc PACS adapter with mocked httpx responses."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from sautiris.integrations.pacs.base import PACSAdapter
from sautiris.integrations.pacs.orthanc import OrthancPACSAdapter


def _mock_response(
    status_code: int = 200,
    json_data: object = None,
    content: bytes = b"",
) -> httpx.Response:
    """Create a mock httpx.Response with a request set (needed for raise_for_status)."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        content=content if json_data is None else None,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


class TestOrthancPACSAdapter:
    """Tests for OrthancPACSAdapter."""

    def setup_method(self) -> None:
        self.adapter = OrthancPACSAdapter(
            base_url="http://localhost:8042",
            dicomweb_root="/dicom-web",
            username="orthanc",
            password="orthanc",
        )

    def _inject_mock_client(self) -> AsyncMock:
        """Inject a mock httpx.AsyncClient into the adapter."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        self.adapter._client = mock_client
        return mock_client

    def test_implements_pacs_adapter(self) -> None:
        assert isinstance(self.adapter, PACSAdapter)

    def test_validate_uid_valid(self) -> None:
        OrthancPACSAdapter._validate_uid("1.2.840.113619.2.55")

    def test_validate_uid_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            OrthancPACSAdapter._validate_uid("")

    def test_validate_uid_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            OrthancPACSAdapter._validate_uid("abc.def")

    def test_validate_uid_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            OrthancPACSAdapter._validate_uid("1." * 33)

    @pytest.mark.asyncio
    async def test_search_studies(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(json_data=[{"StudyInstanceUID": "1.2.3"}])
        results = await self.adapter.search_studies(patient_id="PAT-001")
        assert len(results) == 1
        assert results[0]["StudyInstanceUID"] == "1.2.3"
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_series(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(json_data=[{"SeriesInstanceUID": "4.5.6"}])
        results = await self.adapter.search_series("1.2.3")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_instances(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(json_data=[{"SOPInstanceUID": "7.8.9"}])
        results = await self.adapter.search_instances("1.2.3", "4.5.6")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_retrieve_study_metadata(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(json_data=[{"StudyDescription": "Chest CT"}])
        metadata = await self.adapter.retrieve_study_metadata("1.2.3")
        assert len(metadata) == 1

    @pytest.mark.asyncio
    async def test_retrieve_instance(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(content=b"DICOM_BYTES")
        data = await self.adapter.retrieve_instance("1.2.3", "4.5.6", "7.8.9")
        assert data == b"DICOM_BYTES"

    @pytest.mark.asyncio
    async def test_store_instances(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.post.return_value = _mock_response(json_data={"status": "stored"})
        result = await self.adapter.store_instances("1.2.3", b"DICOM_DATA")
        assert result["status"] == "stored"
        mock_client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_check_ok(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.return_value = _mock_response(json_data=[])
        health = await self.adapter.health_check()
        assert health["status"] == "ok"
        assert health["pacs"] == "orthanc"

    @pytest.mark.asyncio
    async def test_health_check_error(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.get.side_effect = httpx.ConnectError("connection refused")
        health = await self.adapter.health_check()
        assert health["status"] == "error"

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        mock_client = self._inject_mock_client()
        mock_client.aclose = AsyncMock()
        await self.adapter.close()
        mock_client.aclose.assert_awaited_once()
        assert self.adapter._client is None

    @pytest.mark.asyncio
    async def test_no_auth_when_empty_username(self) -> None:
        adapter = OrthancPACSAdapter(base_url="http://localhost:8042", username="")
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get.return_value = _mock_response(json_data=[])
        adapter._client = mock_client
        await adapter.health_check()
        mock_client.get.assert_awaited_once()
