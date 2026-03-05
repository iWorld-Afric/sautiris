"""Tests for FHIR server endpoints and helpers."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sautiris.integrations.fhir.server import (
    FHIR_JSON,
    _fhir_bundle,
    _fhir_capability_statement,
    _fhir_response,
    router,
)


@pytest.fixture
def fhir_app() -> FastAPI:
    """Create a test app with the FHIR router mounted."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(fhir_app: FastAPI) -> TestClient:
    return TestClient(fhir_app)


class TestFHIRResponse:
    """Tests for _fhir_response helper."""

    def test_content_type_is_fhir_json(self) -> None:
        from fhir.resources.imagingstudy import ImagingStudy

        study = ImagingStudy(
            id="test",
            status="available",
            subject={"reference": "Patient/p1"},
        )
        response = _fhir_response(study)
        assert response.media_type == FHIR_JSON

    def test_body_contains_resource(self) -> None:
        from fhir.resources.imagingstudy import ImagingStudy

        study = ImagingStudy(
            id="test",
            status="available",
            subject={"reference": "Patient/p1"},
        )
        response = _fhir_response(study)
        assert response.body is not None
        assert b"ImagingStudy" in response.body


class TestFHIRBundle:
    """Tests for _fhir_bundle helper."""

    def test_bundle_type(self) -> None:
        response = _fhir_bundle([], bundle_type="searchset")
        import json

        body = json.loads(response.body)
        assert body["resourceType"] == "Bundle"
        assert body["type"] == "searchset"

    def test_bundle_total(self) -> None:
        import json

        response = _fhir_bundle([], total=42)
        body = json.loads(response.body)
        assert body["total"] == 42

    def test_bundle_with_resources(self) -> None:
        import json

        from fhir.resources.imagingstudy import ImagingStudy

        study = ImagingStudy(
            id="s1",
            status="available",
            subject={"reference": "Patient/p1"},
        )
        response = _fhir_bundle([study])
        body = json.loads(response.body)
        assert body["total"] == 1
        assert len(body["entry"]) == 1
        assert body["entry"][0]["resource"]["resourceType"] == "ImagingStudy"

    def test_bundle_content_type(self) -> None:
        response = _fhir_bundle([])
        assert response.media_type == FHIR_JSON


class TestCapabilityStatement:
    """Tests for capability statement."""

    def test_resource_type(self) -> None:
        cs = _fhir_capability_statement()
        assert cs["resourceType"] == "CapabilityStatement"

    def test_fhir_version(self) -> None:
        cs = _fhir_capability_statement()
        assert cs["fhirVersion"] == "5.0.0"

    def test_supported_resources(self) -> None:
        cs = _fhir_capability_statement()
        resource_types = [r["type"] for r in cs["rest"][0]["resource"]]
        assert "ImagingStudy" in resource_types
        assert "DiagnosticReport" in resource_types
        assert "ServiceRequest" in resource_types

    def test_metadata_endpoint(self, client: TestClient) -> None:
        response = client.get("/fhir/metadata")
        assert response.status_code == 200
        body = response.json()
        assert body["resourceType"] == "CapabilityStatement"
        assert response.headers["content-type"].startswith(FHIR_JSON)
