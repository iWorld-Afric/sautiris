"""OHIF Viewer v3 adapter — URL builder and configuration generator."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import structlog

from sautiris.integrations.viewer.base import ViewerAdapter

logger = structlog.get_logger(__name__)


class OHIFViewerAdapter(ViewerAdapter):
    """OHIF v3 viewer integration.

    Generates study/series URLs and DICOMweb data source configuration
    compatible with OHIF Viewer v3.

    Args:
        ohif_base_url: Base URL of the OHIF viewer instance (e.g. ``http://localhost:3000``).
        dicomweb_url: DICOMweb endpoint URL that OHIF should use as its data source.
        datasource_name: Display name for the data source in OHIF config.
    """

    def __init__(
        self,
        ohif_base_url: str = "http://localhost:3000",
        dicomweb_url: str = "http://localhost:8042/dicom-web",
        datasource_name: str = "SautiRIS DICOMweb",
    ) -> None:
        self._base_url = ohif_base_url.rstrip("/")
        self._dicomweb_url = dicomweb_url.rstrip("/")
        self._datasource_name = datasource_name

    @staticmethod
    def _validate_uid(uid: str) -> None:
        """Validate DICOM UID format — numeric with dots, max 64 chars."""
        if not uid or not re.match(r"^[0-9.]+$", uid) or len(uid) > 64:
            raise ValueError(f"Invalid DICOM UID: {uid!r}")

    def build_study_url(self, study_instance_uid: str) -> str:
        """Build OHIF viewer URL for a study.

        Returns URL like: ``http://localhost:3000/viewer?StudyInstanceUIDs=1.2.3``
        """
        self._validate_uid(study_instance_uid)
        params = urlencode({"StudyInstanceUIDs": study_instance_uid})
        url = f"{self._base_url}/viewer?{params}"
        logger.debug("ohif.study_url", url=url, study_uid=study_instance_uid)
        return url

    def get_launch_url(
        self,
        study_instance_uid: str,
        series_instance_uid: str | None = None,
    ) -> str:
        """Build OHIF launch URL with optional series targeting.

        Returns URL like:
        ``http://localhost:3000/viewer?StudyInstanceUIDs=1.2.3&SeriesInstanceUIDs=4.5.6``
        """
        self._validate_uid(study_instance_uid)
        params: dict[str, str] = {"StudyInstanceUIDs": study_instance_uid}
        if series_instance_uid:
            self._validate_uid(series_instance_uid)
            params["SeriesInstanceUIDs"] = series_instance_uid
        url = f"{self._base_url}/viewer?{urlencode(params)}"
        logger.debug(
            "ohif.launch_url",
            url=url,
            study_uid=study_instance_uid,
            series_uid=series_instance_uid,
        )
        return url

    def build_config(self) -> dict[str, Any]:
        """Build OHIF v3 data source configuration.

        Returns a dict suitable for OHIF's ``appConfig.dataSources`` array.
        """
        config: dict[str, Any] = {
            "friendlyName": self._datasource_name,
            "namespace": "@ohif/extension-default.dataSourcesModule.dicomweb",
            "sourceName": "dicomweb",
            "configuration": {
                "name": "dicomweb",
                "wadoUriRoot": self._dicomweb_url,
                "qidoRoot": self._dicomweb_url,
                "wadoRoot": self._dicomweb_url,
                "qidoSupportsIncludeField": True,
                "imageRendering": "wadors",
                "thumbnailRendering": "wadors",
                "enableStudyLazyLoad": True,
                "supportsFuzzyMatching": True,
                "supportsWildcard": True,
                "bulkDataURI": {
                    "enabled": True,
                },
            },
        }
        logger.debug("ohif.config_built", datasource=self._datasource_name)
        return config

    def build_full_app_config(self) -> dict[str, Any]:
        """Build a complete OHIF app config with this data source as default.

        Useful for serving OHIF config dynamically from the RIS API.
        """
        return {
            "routerBasename": "/",
            "showStudyList": True,
            "dataSources": [self.build_config()],
            "defaultDataSourceName": "dicomweb",
        }
