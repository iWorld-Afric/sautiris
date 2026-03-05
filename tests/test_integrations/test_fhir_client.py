"""Tests for FHIR client with mocked httpx responses."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from sautiris.integrations.fhir.client import FHIRClient


def _mock_response(
    status_code: int = 200,
    json_data: object = None,
) -> httpx.Response:
    """Create a mock httpx.Response with a request set."""
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("GET", "http://test"),
    )


class TestFHIRClient:
    """Tests for FHIRClient."""

    def setup_method(self) -> None:
        self.client = FHIRClient(
            base_url="http://fhir.example.com/fhir",
            auth_token="test-token",
        )

    def _inject_mock(self) -> AsyncMock:
        mock = AsyncMock(spec=httpx.AsyncClient)
        mock.is_closed = False
        self.client._client = mock
        return mock

    def test_base_url_trailing_slash_stripped(self) -> None:
        c = FHIRClient(base_url="http://fhir.example.com/fhir/")
        assert c.base_url == "http://fhir.example.com/fhir"

    def test_auth_token_stored(self) -> None:
        assert self.client.auth_token == "test-token"

    @pytest.mark.asyncio
    async def test_create(self) -> None:
        mock = self._inject_mock()
        mock.post.return_value = _mock_response(
            json_data={"resourceType": "ImagingStudy", "id": "s1"}
        )
        result = await self.client.create("ImagingStudy", {"resourceType": "ImagingStudy"})
        assert result["resourceType"] == "ImagingStudy"
        mock.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_with_model(self) -> None:
        from fhir.resources.imagingstudy import ImagingStudy

        mock = self._inject_mock()
        mock.post.return_value = _mock_response(
            json_data={"resourceType": "ImagingStudy", "id": "s1"}
        )
        study = ImagingStudy(
            id="s1",
            status="available",
            subject={"reference": "Patient/p1"},
        )
        result = await self.client.create("ImagingStudy", study)
        assert result["id"] == "s1"
        # Verify model_dump was used (json body is a dict, not raw model)
        call_kwargs = mock.post.call_args
        assert isinstance(call_kwargs.kwargs["json"], dict)

    @pytest.mark.asyncio
    async def test_update(self) -> None:
        mock = self._inject_mock()
        mock.put.return_value = _mock_response(
            json_data={"resourceType": "ImagingStudy", "id": "s1"}
        )
        result = await self.client.update("ImagingStudy", "s1", {"resourceType": "ImagingStudy"})
        assert result["id"] == "s1"
        mock.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_read(self) -> None:
        mock = self._inject_mock()
        mock.get.return_value = _mock_response(
            json_data={"resourceType": "ImagingStudy", "id": "s1"}
        )
        result = await self.client.read("ImagingStudy", "s1")
        assert result["id"] == "s1"

    @pytest.mark.asyncio
    async def test_search(self) -> None:
        mock = self._inject_mock()
        mock.get.return_value = _mock_response(
            json_data={
                "resourceType": "Bundle",
                "type": "searchset",
                "total": 1,
                "entry": [{"resource": {"resourceType": "ImagingStudy"}}],
            }
        )
        result = await self.client.search("ImagingStudy", params={"patient": "p1"})
        assert result["resourceType"] == "Bundle"
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        mock = self._inject_mock()
        mock.aclose = AsyncMock()
        await self.client.close()
        mock.aclose.assert_awaited_once()
        assert self.client._client is None

    @pytest.mark.asyncio
    async def test_no_auth_header_without_token(self) -> None:
        client = FHIRClient(base_url="http://fhir.example.com/fhir")
        assert client.auth_token == ""
