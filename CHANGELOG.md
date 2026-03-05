# Changelog

All notable changes to SautiRIS will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0a1] - 2026-03-05

### Added

#### Clinical Workflow
- Order management with 8-state machine (REQUESTED -> SCHEDULED -> IN_PROGRESS -> COMPLETED -> REPORTED -> VERIFIED -> DISTRIBUTED -> CANCELLED)
- Accession number generation with tenant-scoped uniqueness and collision retry
- Structured reporting with Draft -> Preliminary -> Final -> Amended lifecycle
- Report versioning -- every save creates a new version
- Report templates (JSONB-based, assignable by modality)
- Addendum support for finalized reports
- Critical alert system with notification dispatch and auto-escalation
- Peer review workflow with weighted random/targeted assignment
- Radiologist scorecards with agreement rate trending (improving/stable/declining)
- Discrepancy tracking by severity and category

#### Imaging Integration
- DICOM Modality Worklist SCP (C-FIND) via pynetdicom
- DICOM MPPS SCP (N-CREATE/N-SET) for exam status tracking
- DICOM C-STORE SCP accepting 8 SOP classes
- Orthanc PACS DICOMweb adapter (QIDO-RS, WADO-RS, STOW-RS)
- dcm4chee PACS adapter stub
- OHIF Viewer URL builder with study-level deep linking

#### Interoperability
- FHIR R5 resource builders (ImagingStudy, DiagnosticReport, ServiceRequest)
- Read-only FHIR server with CapabilityStatement, Bundle wrapper
- Async FHIR client for external server communication
- HL7v2 ORM^O01 parser (radiology orders)
- HL7v2 ORU^R01 parser (radiology results)
- HL7v2 message builder with round-trip fidelity

#### Operations
- Radiation dose tracking (CTDIvol, DLP, DAP, effective dose)
- Kenya NHIF DRL compliance checking with automated DRLExceeded alerts
- Billing code management (CPT/ICD) with order-level assignment
- Revenue analytics by modality, code system, and month
- Turnaround time metrics (5 intervals: order-to-schedule, schedule-to-exam, exam-to-report, report-to-verify, total)
- Workload analysis and volume statistics
- Room/technologist scheduling with conflict detection

#### Platform
- Multi-tenancy with `TenantAwareRepository[T]` and context-based isolation
- Pluggable authentication: Keycloak OIDC, OAuth2/JWKS, API Key
- RBAC with 20 permissions across 5 roles, enforced on all 60 core endpoints
- Domain event bus (OrderCreated, ReportFinalized, DRLExceeded, etc.)
- Audit logging with user, action, resource tracking
- AI provider adapter with async study submission
- AI webhook handler with HMAC-SHA256 verification
- CAD finding overlay support
- CLI: `sautiris serve`, `sautiris db upgrade`, `sautiris db seed`, `sautiris mwl start`
- `create_ris_app()` factory for mounting in existing FastAPI apps
- 325 tests (81% coverage)
- Full documentation (7 guides + API reference)

### Technical Details
- 88 source files, 20 database models, 69+ REST endpoints
- Python 3.12+, FastAPI, SQLAlchemy async, Pydantic v2
- pynetdicom for DICOM services
- fhir.resources v8 (FHIR R5) for FHIR resource building
- hl7apy for HL7v2 message parsing/building
- Hatchling build system, published on PyPI

[1.0.0a1]: https://github.com/iWorld-Afric/sautiris/releases/tag/v1.0.0a1
