"""FHIR client for publishing resources to external FHIR servers.

Supports creating, updating, and searching resources on remote FHIR
servers via REST API (application/fhir+json).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

FHIR_JSON = "application/fhir+json"


class FHIRClient:
    """FHIR REST client for publishing and querying resources.

    Args:
        base_url: FHIR server base URL (e.g. ``http://localhost:8080/fhir``).
        auth_token: Bearer token for authentication.
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        auth_token: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the async HTTP client."""
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {
                "Content-Type": FHIR_JSON,
                "Accept": FHIR_JSON,
            }
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._client

    async def create(self, resource_type: str, resource: Any) -> dict[str, Any]:
        """Create a resource on the FHIR server (POST).

        Args:
            resource_type: FHIR resource type (e.g. "ImagingStudy").
            resource: fhir.resources model instance or dict.

        Returns:
            The server's response as a dict.
        """
        client = await self._ensure_client()
        body = (
            resource.model_dump(mode="json", exclude_none=True)
            if hasattr(resource, "model_dump")
            else resource
        )
        resp = await client.post(f"/{resource_type}", json=body)
        resp.raise_for_status()
        logger.info("fhir_client.created", resource_type=resource_type)
        return resp.json()  # type: ignore[no-any-return]

    async def update(self, resource_type: str, resource_id: str, resource: Any) -> dict[str, Any]:
        """Update a resource on the FHIR server (PUT).

        Args:
            resource_type: FHIR resource type.
            resource_id: Resource ID.
            resource: fhir.resources model instance or dict.

        Returns:
            The server's response as a dict.
        """
        client = await self._ensure_client()
        body = (
            resource.model_dump(mode="json", exclude_none=True)
            if hasattr(resource, "model_dump")
            else resource
        )
        resp = await client.put(f"/{resource_type}/{resource_id}", json=body)
        resp.raise_for_status()
        logger.info("fhir_client.updated", resource_type=resource_type, resource_id=resource_id)
        return resp.json()  # type: ignore[no-any-return]

    async def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        """Read a resource from the FHIR server (GET).

        Args:
            resource_type: FHIR resource type.
            resource_id: Resource ID.

        Returns:
            The resource as a dict.
        """
        client = await self._ensure_client()
        resp = await client.get(f"/{resource_type}/{resource_id}")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def search(
        self,
        resource_type: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Search for resources on the FHIR server (GET with query params).

        Args:
            resource_type: FHIR resource type.
            params: Search parameters.

        Returns:
            A FHIR Bundle as a dict.
        """
        client = await self._ensure_client()
        resp = await client.get(f"/{resource_type}", params=params)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
