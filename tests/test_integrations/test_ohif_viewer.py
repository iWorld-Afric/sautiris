"""Tests for OHIF viewer adapter."""

from __future__ import annotations

import pytest

from sautiris.integrations.viewer.base import ViewerAdapter
from sautiris.integrations.viewer.ohif import OHIFViewerAdapter


class TestOHIFViewerAdapter:
    """Tests for OHIFViewerAdapter."""

    def setup_method(self) -> None:
        self.adapter = OHIFViewerAdapter(
            ohif_base_url="http://localhost:3000",
            dicomweb_url="http://localhost:8042/dicom-web",
            datasource_name="Test DICOMweb",
        )

    def test_implements_viewer_adapter(self) -> None:
        assert isinstance(self.adapter, ViewerAdapter)

    def test_build_study_url(self) -> None:
        url = self.adapter.build_study_url("1.2.3.4.5.6")
        assert url == "http://localhost:3000/viewer?StudyInstanceUIDs=1.2.3.4.5.6"

    def test_build_study_url_encodes_uid(self) -> None:
        url = self.adapter.build_study_url("1.2.840.113619")
        assert "StudyInstanceUIDs=1.2.840.113619" in url

    def test_build_study_url_invalid_uid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            self.adapter.build_study_url("")

    def test_build_study_url_non_numeric_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            self.adapter.build_study_url("abc.def")

    def test_build_study_url_too_long_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            self.adapter.build_study_url("1." * 33)  # > 64 chars

    def test_get_launch_url_study_only(self) -> None:
        url = self.adapter.get_launch_url("1.2.3.4")
        assert "StudyInstanceUIDs=1.2.3.4" in url
        assert "SeriesInstanceUIDs" not in url

    def test_get_launch_url_with_series(self) -> None:
        url = self.adapter.get_launch_url("1.2.3.4", series_instance_uid="5.6.7.8")
        assert "StudyInstanceUIDs=1.2.3.4" in url
        assert "SeriesInstanceUIDs=5.6.7.8" in url

    def test_get_launch_url_invalid_series_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid DICOM UID"):
            self.adapter.get_launch_url("1.2.3", series_instance_uid="invalid!")

    def test_build_config_structure(self) -> None:
        config = self.adapter.build_config()
        assert config["friendlyName"] == "Test DICOMweb"
        assert config["namespace"] == "@ohif/extension-default.dataSourcesModule.dicomweb"
        assert "configuration" in config
        cfg = config["configuration"]
        assert cfg["wadoUriRoot"] == "http://localhost:8042/dicom-web"
        assert cfg["qidoRoot"] == "http://localhost:8042/dicom-web"
        assert cfg["wadoRoot"] == "http://localhost:8042/dicom-web"
        assert cfg["qidoSupportsIncludeField"] is True
        assert cfg["imageRendering"] == "wadors"
        assert cfg["thumbnailRendering"] == "wadors"

    def test_build_full_app_config(self) -> None:
        config = self.adapter.build_full_app_config()
        assert config["routerBasename"] == "/"
        assert config["showStudyList"] is True
        assert len(config["dataSources"]) == 1
        assert config["defaultDataSourceName"] == "dicomweb"

    def test_custom_base_url(self) -> None:
        adapter = OHIFViewerAdapter(ohif_base_url="https://viewer.hospital.com/")
        url = adapter.build_study_url("1.2.3")
        assert url.startswith("https://viewer.hospital.com/viewer")

    def test_trailing_slash_stripped(self) -> None:
        adapter = OHIFViewerAdapter(ohif_base_url="http://host:3000/")
        url = adapter.build_study_url("1.2.3")
        assert "//viewer" not in url
