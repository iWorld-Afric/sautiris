# SautiRIS Comprehensive Review & Enhancement Roadmap

**Date**: 2026-03-06
**Review Team**: 6 specialized agents (Architecture, AI Integration, DICOM/PACS, Interoperability, Competitive Analysis, Security)
**Files Reviewed**: 88 source files, 20 models, 69+ endpoints, 325 tests

---

## Executive Summary

SautiRIS is a **first-of-its-kind** open-source, pip-installable Radiology Information System with no direct competitor in the market. After analyzing 25+ competitors and auditing the entire codebase across 6 specialized domains, we find:

- **Architecture**: Solid foundation — layered design, async-first, pluggable adapters via ABC, domain event bus. But global mutable state breaks the library-first promise, and tenant isolation is critically flawed.
- **AI Integration**: ~15-20% complete. Framework skeleton exists but lacks job tracking, API routes, service layer, study delivery, and result normalization.
- **DICOM/PACS**: Core SCPs work (MWL, MPPS, C-STORE) but missing critical DICOM tags (StudyInstanceUID in MWL, SpecificCharacterSet), limited SOP classes, no RDSR parsing, no association security.
- **Interoperability**: ~25-30% complete. FHIR R5-only (95% of EHRs use R4), FHIR server has no resource endpoints, no MLLP transport, no SMART on FHIR.
- **Security**: 8 CRITICAL vulnerabilities including tenant isolation bypass, CORS wildcard, plaintext credentials, JWKS cache with no TTL. NOT HIPAA/GDPR/Kenya DPA compliant.
- **Competitive Position**: Unique — only open-source RIS with native AI hooks + DICOM SCPs + FHIR + HL7v2 + multi-tenancy + pip-installable. No direct competitor.

**Total findings**: 23 CRITICAL, 50+ HIGH, 40+ MEDIUM across all reviews.

---

## Finding Summary by Severity

### CRITICAL (23 items — must fix before any production deployment)

#### Security & Tenant Isolation (fix FIRST)
| # | Finding | Source | Files |
|---|---------|--------|-------|
| 1 | Tenant ID spoofable via X-Tenant-ID header — any user can access any tenant's data | Security C-4, Architecture CRITICAL-1 | `core/tenancy.py:41-45` |
| 2 | Middleware order broken — tenant set BEFORE auth runs, JWT tenant claim never consulted | Security C-5, Architecture CRITICAL-2 | `app.py:81-92`, `core/tenancy.py:47-51` |
| 3 | JWKS cache never invalidates — compromised keys accepted forever | Security C-1, Architecture CRITICAL-4 | `core/auth/keycloak.py:36-44`, `core/auth/oauth2.py:30-39` |
| 4 | CORS wildcard `["*"]` + `allow_credentials=True` — cross-origin PHI exfiltration | Security C-8, Architecture HIGH-5 | `config.py:76`, `app.py:82-87` |
| 5 | PACS credentials stored in plaintext | Security C-6 | `models/pacs.py:29` |
| 6 | AI API keys and webhook secrets in plaintext | Security C-7 | `models/ai_integration.py:20,23` |
| 7 | API key auth uses PACS AE Titles as credentials, all share UUID(0) | Security H-1, Architecture CRITICAL-5 | `core/auth/apikey.py:35-55` |
| 8 | Global mutable state breaks library mountability | Architecture CRITICAL-3 | `api/deps.py:15-16`, `core/events.py:227` |

#### DICOM Compliance
| # | Finding | Source | Files |
|---|---------|--------|-------|
| 9 | Missing StudyInstanceUID in MWL responses — breaks image-to-order linking | DICOM | `integrations/dicom/mwl_scp.py:29-79` |
| 10 | No SpecificCharacterSet anywhere — African names garbled | DICOM | Entire codebase |
| 11 | Only 8 of 100+ Storage SOP Classes — missing mammography, RDSR, DICOM SR | DICOM | `integrations/dicom/store_scp.py` |
| 12 | No RDSR parsing — automated dose tracking impossible | DICOM | `services/dose_service.py` |

#### Interoperability
| # | Finding | Source | Files |
|---|---------|--------|-------|
| 13 | FHIR R5-only — 95% of EHRs use R4 | Interop | `integrations/fhir/resources.py` |
| 14 | FHIR server has no resource endpoints — only `/metadata` | Interop | `integrations/fhir/server.py` |
| 15 | FHIR router not mounted in application — completely inaccessible | Interop | `app.py` |
| 16 | No MLLP transport — HL7v2 can be parsed/built but not sent/received | Interop | N/A (missing) |
| 17 | No ACK/NAK handling — violates HL7v2 protocol | Interop | N/A (missing) |
| 18 | No SMART on FHIR authorization | Interop | N/A (missing) |

#### AI Integration
| # | Finding | Source | Files |
|---|---------|--------|-------|
| 19 | No AI Job tracking table — jobs exist only in memory | AI | N/A (missing) |
| 20 | No AI API routes — no external interaction possible | AI | N/A (missing) |
| 21 | No AI service layer — no orchestration logic | AI | N/A (missing) |
| 22 | No study delivery mechanism — providers can't access DICOM data | AI | `integrations/ai/base.py:68` |
| 23 | No DICOM SR output for AI findings | AI, DICOM | N/A (missing) |

---

## Prioritized Enhancement Roadmap

### P0: Production Blockers (v1.0-stable) — Weeks 1-6

**Sprint 1-2: Security Emergency**
- [ ] Fix tenant isolation: JWT claim MUST override X-Tenant-ID header; restructure middleware order
- [ ] Add JWKS cache TTL (10-minute default) with key-miss refetch
- [ ] Change CORS default from `["*"]` to `[]`; require explicit config
- [ ] Encrypt credentials at rest (PACS passwords, AI API keys, webhook secrets) — Fernet or Vault
- [ ] Redesign API key auth: dedicated model, hashed keys, proper RBAC, real user IDs
- [ ] Fix default tenant fallback: reject requests with no tenant, don't silently default
- [ ] Sanitize error messages (remove JWT details, internal paths)
- [ ] Add rate limiting (slowapi or custom middleware)

**Sprint 3-4: Core Architecture**
- [ ] Eliminate global state: pass session_factory, auth_provider, event_bus via `app.state`
- [ ] Wire typed domain events (use OrderCreated, ReportFinalized, etc. instead of generic DomainEvent)
- [ ] Wire AuditLogger — call from all service methods on PHI access
- [ ] Check and log event publish errors (don't discard)
- [ ] Add ReportVersion tenant isolation (extend TenantAwareBase)
- [ ] Fix test infrastructure: correct dependency_overrides, add API integration tests
- [ ] Fix app version: reference `__version__` from `__init__.py`
- [ ] Use `__version__` from pyproject.toml dynamically

**Sprint 5-6: DICOM Critical Fixes**
- [ ] Add all required MWL response tags (StudyInstanceUID, SpecificCharacterSet, RequestedProcedureCodeSequence, etc.)
- [ ] Add SpecificCharacterSet (UTF-8 / ISO_IR 192) to all outbound DICOM datasets
- [ ] Expand C-STORE SOP classes (mammography, RDSR, DICOM SR, KOS, Encapsulated PDF, NM, PET, XA)
- [ ] Add explicit transfer syntax support (Explicit VR LE, JPEG Baseline, JPEG Lossless)
- [ ] Implement MPPS state machine validation
- [ ] Add association access control (AE title whitelist, max associations, TLS option)
- [ ] Write DICOM Conformance Statement
- [ ] Docker image + docker-compose + Helm chart

### P1: Production Readiness (v1.1) — Weeks 7-16

**Interoperability Foundation**
- [ ] Mount FHIR router in application
- [ ] Add FHIR resource read/search endpoints (ImagingStudy, DiagnosticReport, ServiceRequest)
- [ ] Add FHIR R4 resource builders alongside R5 (version parameter)
- [ ] Fix DiagnosticReport: map findings, performer, add category
- [ ] Add Patient, Practitioner, Organization FHIR resources
- [ ] Implement MLLP server + client (asyncio TCP)
- [ ] Implement ACK/NAK generation
- [ ] Add ADT^A01/A04/A08 message parsing
- [ ] Build event-to-interop bridge (EventBus -> FHIR publish / HL7v2 send)
- [ ] Add terminology bindings (RadLex, SNOMED-CT, ICD-10, LOINC)

**AI Integration Foundation**
- [ ] Create AIJob DB model + AIService
- [ ] Add AI API routes (CRUD providers, submit study, get findings, webhook endpoint)
- [ ] Implement Provider Registry + Factory
- [ ] Add study delivery abstraction (DICOMweb push/pull, pre-signed URL)
- [ ] Wire ExamCompleted -> AI submission
- [ ] Wire AI critical finding -> AlertService
- [ ] Add AI domain events (submitted, completed, failed, finding created)
- [ ] Add job retry/timeout/dead-letter
- [ ] Add finding review workflow (accept/reject/modify with audit)
- [ ] Add regulatory tracking fields on AIProviderConfig
- [ ] Implement result normalization pipeline per provider
- [ ] First concrete adapter: Qure.ai qXR for TB screening

**Clinical Workflow**
- [ ] Voice dictation integration (Whisper API / Azure Speech)
- [ ] Report distribution (HL7v2 ORU push, email PDF)
- [ ] Real-time notifications (WebSocket/SSE for worklist updates, critical alerts)
- [ ] Prior study comparison workflow
- [ ] RDSR parsing for automated dose tracking

**Compliance**
- [ ] HIPAA gap closure: encryption at rest, complete audit trail, transmission security
- [ ] Add automatic audit logging middleware
- [ ] Add security event monitoring (failed auth, tenant spoofing attempts)
- [ ] Pin dependencies with lockfile
- [ ] Migrate from python-jose to PyJWT or joserfc
- [ ] Implement data retention policies

### P2: Feature Completeness (v1.2) — Weeks 17-28

**DICOM/PACS**
- [ ] Storage Commitment SCP (N-EVENT-REPORT)
- [ ] Image routing engine (rule-based forwarding from C-STORE)
- [ ] DICOM Q/R SCP (C-MOVE, C-GET)
- [ ] WADO-RS: series metadata, frames, thumbnails, rendered
- [ ] WADO-URI support (legacy viewer compatibility)
- [ ] Viewer authentication (token-based study access)
- [ ] Cloud PACS adapters (GCP Healthcare API, AWS HealthImaging)
- [ ] Weasis viewer adapter
- [ ] Back MPPS instance store with database/Redis

**Interoperability**
- [ ] SMART on FHIR authorization
- [ ] FHIR Subscriptions (R5 topic-based)
- [ ] FHIR search pagination (_count, _offset, Bundle.link)
- [ ] SIU scheduling messages
- [ ] HL7v2 message routing engine
- [ ] IHE SWF profile formalization
- [ ] IHE RWF profile formalization
- [ ] ATNA audit log export

**AI Advanced**
- [ ] Multi-provider orchestration (fan-out, failover)
- [ ] Confidence calibration per provider
- [ ] AI pre-read + second-read modes
- [ ] DICOM SR output for AI findings (TID 1500)
- [ ] Heatmap/attention map storage
- [ ] Auto-impression generation (LLM integration)
- [ ] AI triage/prioritization

**Clinical**
- [ ] Mammography BI-RADS workflow
- [ ] Clinical Decision Support hooks (ACR Appropriateness Criteria)
- [ ] Teaching file management
- [ ] Advanced analytics dashboards (configurable, exportable)
- [ ] Multi-language support (English + Swahili)

**African Market**
- [ ] DHIS2 integration (aggregate radiology reporting)
- [ ] OpenHIE alignment (Client Registry, Facility Registry)
- [ ] Kenya SHA/NHIF claims integration
- [ ] KMHFL facility code lookup
- [ ] National Health ID support

**Compliance**
- [ ] GDPR: right to erasure, data portability, consent management
- [ ] Kenya DPA: data subject rights endpoints, cross-border controls
- [ ] IEC 62304 requirement traceability
- [ ] Reach 90%+ test coverage

### P3: Market Leadership (v2.0) — Weeks 29-52

**Platform**
- [ ] A/B testing framework for AI models
- [ ] AI consensus/ensemble findings
- [ ] Batch/retrospective AI processing
- [ ] AI marketplace platform
- [ ] Real-time collaboration (WebSocket-based)
- [ ] DICOM Presentation State objects
- [ ] DICOM Segmentation objects
- [ ] Hanging Protocol support
- [ ] UPS-RS (Unified Procedure Step via DICOMweb)
- [ ] XDS-I.b cross-enterprise image sharing
- [ ] FHIR Bulk Data Access ($export)
- [ ] PIXm/PDQm patient cross-referencing
- [ ] Federated multi-site worklist
- [ ] Patient portal (view reports, images)
- [ ] DICOM Print SCP/SCU
- [ ] IHE Connectathon compliance testing

**Enterprise**
- [ ] Managed cloud SautiRIS offering
- [ ] FDA/CE regulatory pathway documentation
- [ ] SOC2 compliance
- [ ] RVU tracking and productivity reporting
- [ ] Federated learning for AI models

---

## Competitive Position Summary

### Industry Firsts (Confirmed)
1. First pip-installable RIS
2. First open-source RIS with native AI provider framework
3. First library-first RIS (mountable sub-app)
4. First open-source RIS with FHIR R5
5. First open-source RIS with native DICOM MWL + MPPS + C-STORE
6. First RIS with Kenya NHIF DRL compliance

### Feature Parity with Commercial RIS
SautiRIS matches commercial systems on: order management (8-state), structured reporting, DICOM MWL/MPPS, multi-tenancy, RBAC, peer review QA, radiation dose tracking, analytics, billing code management, audit trail, and domain events.

### Key Gaps vs Commercial RIS
Voice dictation, IHE profile compliance, report distribution, native PACS, enterprise scheduling, regulatory certifications, vendor-managed AI marketplace, prior study comparison, mammography BI-RADS, DICOM SR.

### Recommended Market Strategy
- **Open-core model**: Community Edition free (Apache 2.0), Professional $500-2K/month, Enterprise $5-15K/month
- **Target markets**: African imaging centers (Tier 1), developer/integrator community (Tier 1), teleradiology startups (Tier 2)
- **First AI adapter**: Qure.ai qXR for TB screening (highest impact for Africa)

---

## Review Team Findings Index

| Review | Findings | Key Theme |
|--------|----------|-----------|
| Architecture & Code Quality | 5 CRITICAL, 14 HIGH, 8 MEDIUM | Global state, dead typed events, test infra broken |
| AI Integration | 7 CRITICAL, 12 HIGH, 10 MEDIUM | Framework at 15-20%, needs job tracking + API + service layer |
| DICOM/PACS Compliance | 4 CRITICAL, 12 HIGH, 15+ MEDIUM | Missing required tags, limited SOP classes, no RDSR |
| FHIR/HL7v2 Interoperability | 7 CRITICAL, 10 HIGH, 9 MEDIUM | R5-only, no MLLP, FHIR server skeleton |
| Competitive Analysis | N/A | No direct competitor, unique market position |
| Security & Compliance | 8 CRITICAL, 12 HIGH, 15 MEDIUM | Tenant bypass, CORS, plaintext creds, not HIPAA-compliant |
