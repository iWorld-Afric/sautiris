"""FHIR resource server — serves radiology resources as FHIR JSON.

Provides read-only FHIR endpoints for ImagingStudy, DiagnosticReport,
and ServiceRequest resources derived from SautiRIS data.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = structlog.get_logger(__name__)

FHIR_JSON = "application/fhir+json"

router = APIRouter(prefix="/fhir", tags=["FHIR"])


def _fhir_response(resource: Any) -> JSONResponse:
    """Wrap a fhir.resources model in a JSONResponse with FHIR content type."""
    return JSONResponse(
        content=resource.model_dump(mode="json", exclude_none=True),
        media_type=FHIR_JSON,
    )


def _fhir_bundle(
    resources: list[Any],
    bundle_type: str = "searchset",
    total: int | None = None,
) -> JSONResponse:
    """Wrap multiple FHIR resources in a Bundle."""
    entries = []
    for r in resources:
        entry: dict[str, Any] = {
            "resource": r.model_dump(mode="json", exclude_none=True),
        }
        resource_id = r.id
        if resource_id:
            entry["fullUrl"] = f"urn:uuid:{resource_id}"
        entries.append(entry)

    bundle = {
        "resourceType": "Bundle",
        "type": bundle_type,
        "total": total if total is not None else len(resources),
        "entry": entries,
    }
    return JSONResponse(content=bundle, media_type=FHIR_JSON)


def _fhir_capability_statement() -> dict[str, Any]:
    """Build a minimal FHIR CapabilityStatement."""
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "kind": "instance",
        "fhirVersion": "5.0.0",
        "format": ["json"],
        "rest": [
            {
                "mode": "server",
                "resource": [
                    {
                        "type": "ImagingStudy",
                        "interaction": [{"code": "read"}, {"code": "search-type"}],
                        "searchParam": [
                            {"name": "patient", "type": "reference"},
                            {"name": "status", "type": "token"},
                        ],
                    },
                    {
                        "type": "DiagnosticReport",
                        "interaction": [{"code": "read"}, {"code": "search-type"}],
                        "searchParam": [
                            {"name": "patient", "type": "reference"},
                            {"name": "status", "type": "token"},
                        ],
                    },
                    {
                        "type": "ServiceRequest",
                        "interaction": [{"code": "read"}, {"code": "search-type"}],
                        "searchParam": [
                            {"name": "patient", "type": "reference"},
                            {"name": "status", "type": "token"},
                        ],
                    },
                ],
            }
        ],
    }


@router.get("/metadata")
async def capability_statement() -> JSONResponse:
    """FHIR CapabilityStatement (conformance endpoint)."""
    return JSONResponse(
        content=_fhir_capability_statement(),
        media_type=FHIR_JSON,
    )
