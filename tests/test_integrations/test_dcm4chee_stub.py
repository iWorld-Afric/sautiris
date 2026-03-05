"""Tests for dcm4chee PACS adapter stub — verify ABC compliance."""

from __future__ import annotations

import pytest

from sautiris.integrations.pacs.base import PACSAdapter
from sautiris.integrations.pacs.dcm4chee import DCM4CheePACSAdapter


class TestDCM4CheePACSAdapter:
    """Tests for DCM4CheePACSAdapter stub."""

    def setup_method(self) -> None:
        self.adapter = DCM4CheePACSAdapter()

    def test_implements_pacs_adapter(self) -> None:
        assert isinstance(self.adapter, PACSAdapter)

    @pytest.mark.asyncio
    async def test_search_studies_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.search_studies()

    @pytest.mark.asyncio
    async def test_search_series_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.search_series("1.2.3")

    @pytest.mark.asyncio
    async def test_search_instances_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.search_instances("1.2.3")

    @pytest.mark.asyncio
    async def test_retrieve_study_metadata_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.retrieve_study_metadata("1.2.3")

    @pytest.mark.asyncio
    async def test_retrieve_instance_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.retrieve_instance("1.2.3", "4.5.6", "7.8.9")

    @pytest.mark.asyncio
    async def test_store_instances_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.store_instances("1.2.3", b"data")

    @pytest.mark.asyncio
    async def test_delete_study_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.delete_study("1.2.3")

    @pytest.mark.asyncio
    async def test_health_check_raises(self) -> None:
        with pytest.raises(NotImplementedError, match="dcm4chee"):
            await self.adapter.health_check()

    @pytest.mark.asyncio
    async def test_close_no_error(self) -> None:
        await self.adapter.close()  # Should not raise
