"""Tests for FHIR resource builders.

Validates that built resources conform to FHIR spec via fhir.resources
library validation (v8.x, FHIR R5).
"""

from __future__ import annotations

from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.imagingstudy import ImagingStudy
from fhir.resources.servicerequest import ServiceRequest

from sautiris.integrations.fhir.resources import (
    build_diagnostic_report,
    build_imaging_study,
    build_service_request,
)


class TestBuildImagingStudy:
    """Tests for build_imaging_study."""

    def test_basic_imaging_study(self) -> None:
        study = build_imaging_study(
            order_id="order-001",
            patient_id="patient-001",
            modality="CT",
            accession_number="ACC-001",
        )
        assert isinstance(study, ImagingStudy)
        assert study.id == "order-001"
        assert study.status == "available"
        assert study.subject.reference == "Patient/patient-001"

    def test_with_study_instance_uid(self) -> None:
        study = build_imaging_study(
            order_id="order-002",
            patient_id="patient-002",
            study_instance_uid="1.2.3.4.5",
            modality="CR",
        )
        # Should have identifier with urn:oid
        assert study.identifier is not None
        uids = [i.value for i in study.identifier]
        assert any("1.2.3.4.5" in uid for uid in uids)

    def test_with_series_count(self) -> None:
        study = build_imaging_study(
            order_id="order-003",
            patient_id="patient-003",
            num_series=3,
            num_instances=45,
        )
        assert study.numberOfSeries == 3
        assert study.numberOfInstances == 45

    def test_with_modality_creates_series(self) -> None:
        study = build_imaging_study(
            order_id="order-004",
            patient_id="patient-004",
            modality="MR",
        )
        assert study.series is not None
        assert len(study.series) == 1
        assert study.series[0].modality.coding[0].code == "MR"

    def test_without_modality_no_series(self) -> None:
        study = build_imaging_study(
            order_id="order-005",
            patient_id="patient-005",
        )
        assert study.series is None

    def test_resource_validates(self) -> None:
        """Ensure the resource passes FHIR validation."""
        study = build_imaging_study(
            order_id="order-006",
            patient_id="patient-006",
            modality="US",
            accession_number="ACC-006",
        )
        # fhir.resources validates on construction; model_dump_json also validates
        json_str = study.model_dump_json()
        assert "ImagingStudy" in json_str


class TestBuildDiagnosticReport:
    """Tests for build_diagnostic_report."""

    def test_basic_report(self) -> None:
        report = build_diagnostic_report(
            report_id="report-001",
            order_id="order-001",
            patient_id="patient-001",
            status="final",
        )
        assert isinstance(report, DiagnosticReport)
        assert report.id == "report-001"
        assert report.status == "final"

    def test_with_conclusion(self) -> None:
        report = build_diagnostic_report(
            report_id="report-002",
            order_id="order-002",
            patient_id="patient-002",
            impression="No acute findings",
        )
        assert report.conclusion == "No acute findings"

    def test_based_on_service_request(self) -> None:
        report = build_diagnostic_report(
            report_id="report-003",
            order_id="order-003",
            patient_id="patient-003",
        )
        assert report.basedOn is not None
        assert report.basedOn[0].reference == "ServiceRequest/order-003"

    def test_with_imaging_study_ref(self) -> None:
        report = build_diagnostic_report(
            report_id="report-004",
            order_id="order-004",
            patient_id="patient-004",
            imaging_study_id="study-004",
        )
        # R5: imagingStudy -> study
        assert report.study is not None
        assert report.study[0].reference == "ImagingStudy/study-004"

    def test_code_is_diagnostic_imaging(self) -> None:
        report = build_diagnostic_report(
            report_id="report-005",
            order_id="order-005",
            patient_id="patient-005",
        )
        assert report.code.coding[0].code == "18748-4"

    def test_resource_validates(self) -> None:
        report = build_diagnostic_report(
            report_id="report-006",
            order_id="order-006",
            patient_id="patient-006",
        )
        json_str = report.model_dump_json()
        assert "DiagnosticReport" in json_str


class TestBuildServiceRequest:
    """Tests for build_service_request."""

    def test_basic_service_request(self) -> None:
        sr = build_service_request(
            order_id="order-001",
            patient_id="patient-001",
            modality="CT",
        )
        assert isinstance(sr, ServiceRequest)
        assert sr.id == "order-001"
        assert sr.status == "active"
        assert sr.intent == "order"

    def test_priority_mapping(self) -> None:
        sr = build_service_request(
            order_id="order-002",
            patient_id="patient-002",
            urgency="STAT",
        )
        assert sr.priority == "stat"

    def test_with_accession_identifier(self) -> None:
        sr = build_service_request(
            order_id="order-003",
            patient_id="patient-003",
            accession_number="ACC-003",
        )
        assert sr.identifier is not None
        assert sr.identifier[0].value == "ACC-003"

    def test_with_procedure_code(self) -> None:
        sr = build_service_request(
            order_id="order-004",
            patient_id="patient-004",
            procedure_code="71020",
            procedure_description="Chest X-Ray",
        )
        # R5: code is CodeableReference with concept
        assert sr.code is not None
        assert sr.code.concept.coding[0].code == "71020"

    def test_with_clinical_indication(self) -> None:
        sr = build_service_request(
            order_id="order-005",
            patient_id="patient-005",
            clinical_indication="Persistent cough",
        )
        # R5: reasonCode -> reason (list of CodeableReference)
        assert sr.reason is not None
        assert sr.reason[0].concept.text == "Persistent cough"

    def test_with_requester(self) -> None:
        sr = build_service_request(
            order_id="order-006",
            patient_id="patient-006",
            requesting_physician="Dr. Smith",
        )
        assert sr.requester is not None
        assert sr.requester.display == "Dr. Smith"

    def test_resource_validates(self) -> None:
        sr = build_service_request(
            order_id="order-007",
            patient_id="patient-007",
            modality="MR",
            accession_number="ACC-007",
        )
        json_str = sr.model_dump_json()
        assert "ServiceRequest" in json_str
