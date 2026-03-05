"""FHIR resource builders for radiology data.

Builds valid FHIR resources from SautiRIS orders and reports using
the fhir.resources library (v8.x, FHIR R5) for spec validation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.codeablereference import CodeableReference
from fhir.resources.coding import Coding
from fhir.resources.diagnosticreport import DiagnosticReport
from fhir.resources.imagingstudy import ImagingStudy, ImagingStudySeries
from fhir.resources.servicerequest import ServiceRequest

logger = structlog.get_logger(__name__)


def build_imaging_study(
    order_id: str,
    patient_id: str,
    study_instance_uid: str | None = None,
    accession_number: str = "",
    modality: str = "",
    procedure_description: str = "",
    num_series: int = 0,
    num_instances: int = 0,
    started: str | None = None,
    status: str = "available",
) -> ImagingStudy:
    """Build a FHIR ImagingStudy resource from radiology order data.

    Args:
        order_id: Internal order ID (used as FHIR resource ID).
        patient_id: Patient UUID reference.
        study_instance_uid: DICOM Study Instance UID.
        accession_number: Accession number.
        modality: DICOM modality code (CR, CT, MR, etc.).
        procedure_description: Description of the procedure performed.
        num_series: Number of series in the study.
        num_instances: Number of instances in the study.
        started: ISO datetime when the study started.
        status: FHIR ImagingStudy status.

    Returns:
        Validated FHIR ImagingStudy resource.
    """
    identifiers = []
    if accession_number:
        identifiers.append(
            {
                "system": "urn:dicom:uid",
                "value": accession_number,
            }
        )
    if study_instance_uid:
        identifiers.append(
            {
                "system": "urn:dicom:uid",
                "value": f"urn:oid:{study_instance_uid}",
            }
        )

    series_list = []
    if modality:
        modality_cc = CodeableConcept(
            coding=[
                Coding(
                    system="http://dicom.nema.org/resources/ontology/DCM",
                    code=modality,
                )
            ]
        )
        series_list.append(
            ImagingStudySeries(
                uid=study_instance_uid or str(uuid.uuid4()),
                modality=modality_cc,
            )
        )

    resource = ImagingStudy(
        id=order_id,
        status=status,
        subject={"reference": f"Patient/{patient_id}"},
        identifier=identifiers or None,
        description=procedure_description or None,
        numberOfSeries=num_series if num_series else None,
        numberOfInstances=num_instances if num_instances else None,
        started=started,
        series=series_list or None,
    )

    logger.debug("fhir.built_imaging_study", order_id=order_id, modality=modality)
    return resource


def build_diagnostic_report(
    report_id: str,
    order_id: str,
    patient_id: str,
    accession_number: str = "",
    status: str = "final",
    findings: str = "",
    impression: str = "",
    conclusion: str = "",
    reported_by: str = "",
    reported_at: str | None = None,
    imaging_study_id: str | None = None,
) -> DiagnosticReport:
    """Build a FHIR DiagnosticReport resource from a radiology report.

    Args:
        report_id: Internal report ID.
        order_id: Internal order ID (ServiceRequest reference).
        patient_id: Patient UUID reference.
        accession_number: Accession number.
        status: FHIR report status (preliminary, final, amended, etc.).
        findings: Report findings text.
        impression: Report impression/conclusion.
        conclusion: Explicit conclusion (used if impression is empty).
        reported_by: Radiologist name or ID.
        reported_at: ISO datetime when report was finalized.
        imaging_study_id: ID of related ImagingStudy resource.

    Returns:
        Validated FHIR DiagnosticReport resource.
    """
    based_on = [{"reference": f"ServiceRequest/{order_id}"}]

    # R5: imagingStudy -> study
    study_refs = []
    if imaging_study_id:
        study_refs.append({"reference": f"ImagingStudy/{imaging_study_id}"})

    conclusion_text = impression or conclusion

    # R5: code is CodeableConcept (same as R4 for DiagnosticReport)
    code = CodeableConcept(
        coding=[
            Coding(
                system="http://loinc.org",
                code="18748-4",
                display="Diagnostic imaging study",
            )
        ]
    )

    resource = DiagnosticReport(
        id=report_id,
        status=status,
        code=code,
        subject={"reference": f"Patient/{patient_id}"},
        basedOn=based_on,
        study=study_refs or None,
        conclusion=conclusion_text or None,
        effectiveDateTime=reported_at or datetime.now(UTC).isoformat(),
    )

    logger.debug("fhir.built_diagnostic_report", report_id=report_id, status=status)
    return resource


def build_service_request(
    order_id: str,
    patient_id: str,
    accession_number: str = "",
    modality: str = "",
    procedure_code: str = "",
    procedure_description: str = "",
    urgency: str = "routine",
    clinical_indication: str = "",
    requesting_physician: str = "",
    status: str = "active",
) -> ServiceRequest:
    """Build a FHIR ServiceRequest resource from a radiology order.

    Args:
        order_id: Internal order ID.
        patient_id: Patient UUID reference.
        accession_number: Accession number.
        modality: DICOM modality code.
        procedure_code: Internal procedure code.
        procedure_description: Procedure description.
        urgency: Order urgency (routine, urgent, stat, asap).
        clinical_indication: Clinical reason for the exam.
        requesting_physician: Requesting physician name or ID.
        status: FHIR ServiceRequest status.

    Returns:
        Validated FHIR ServiceRequest resource.
    """
    priority_map: dict[str, str] = {
        "routine": "routine",
        "urgent": "urgent",
        "stat": "stat",
        "asap": "asap",
    }

    identifiers = []
    if accession_number:
        identifiers.append(
            {
                "system": "urn:sautiris:accession",
                "value": accession_number,
            }
        )

    # R5: code is CodeableReference, not CodeableConcept
    code_codings = []
    if procedure_code:
        code_codings.append(
            Coding(
                system="urn:sautiris:procedure",
                code=procedure_code,
                display=procedure_description or procedure_code,
            )
        )
    if modality:
        code_codings.append(
            Coding(
                system="http://dicom.nema.org/resources/ontology/DCM",
                code=modality,
                display=f"{modality} imaging",
            )
        )

    code_ref = None
    if code_codings:
        code_ref = CodeableReference(concept=CodeableConcept(coding=code_codings))

    # R5: reasonCode -> reason (list of CodeableReference)
    reason = []
    if clinical_indication:
        reason.append(CodeableReference(concept=CodeableConcept(text=clinical_indication)))

    requester = None
    if requesting_physician:
        requester = {"display": requesting_physician}

    resource = ServiceRequest(
        id=order_id,
        status=status,
        intent="order",
        subject={"reference": f"Patient/{patient_id}"},
        identifier=identifiers or None,
        code=code_ref,
        priority=priority_map.get(urgency.lower(), "routine"),
        reason=reason or None,
        requester=requester,
    )

    logger.debug("fhir.built_service_request", order_id=order_id, modality=modality)
    return resource
