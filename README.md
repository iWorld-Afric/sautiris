<p align="center">
  <h1 align="center">SautiRIS</h1>
  <p align="center">
    <strong>Open-source Radiology Information System built on FastAPI</strong>
  </p>
  <p align="center">
    <a href="https://pypi.org/project/sautiris/"><img src="https://img.shields.io/pypi/v/sautiris" alt="PyPI version"></a>
    <a href="https://pypi.org/project/sautiris/"><img src="https://img.shields.io/pypi/pyversions/sautiris" alt="Python versions"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License"></a>
    <a href="https://github.com/iWorld-Afric/sautiris/actions"><img src="https://img.shields.io/badge/tests-325%20passed-brightgreen" alt="Tests"></a>
    <a href="https://github.com/iWorld-Afric/sautiris/actions"><img src="https://img.shields.io/badge/coverage-81%25-brightgreen" alt="Coverage"></a>
    <a href="https://pypi.org/project/sautiris/"><img src="https://img.shields.io/pypi/dm/sautiris" alt="Downloads"></a>
  </p>
</p>

---

SautiRIS is a **complete, production-ready Radiology Information System** backend with order management, DICOM Modality Worklist, structured reporting, peer review QA, radiation dose tracking, FHIR R5 interoperability, HL7v2 messaging, and AI integration hooks.

Built for healthcare facilities in **Kenya and across Africa**, SautiRIS can run standalone or be mounted into any existing FastAPI application. It ships as a single `pip install` with pluggable authentication, multi-tenancy, and fine-grained RBAC out of the box.

## Table of Contents

- [Features](#features)
- [Quickstart](#quickstart)
- [Installation](#installation)
- [Usage](#usage)
- [API Endpoints](#api-endpoints)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [Roadmap](#roadmap)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Features

### Clinical Workflow
- **Order Management** -- Full radiology order lifecycle with 8-state machine (REQUESTED -> SCHEDULED -> IN_PROGRESS -> COMPLETED -> REPORTED -> VERIFIED -> DISTRIBUTED -> CANCELLED), accession number generation, and audit trail
- **Structured Reporting** -- Draft -> Preliminary -> Final -> Amended workflow with version history, report templates (JSONB), and addendum support
- **Critical Alerts** -- Critical finding notification dispatch with configurable escalation timeouts, acknowledgment tracking, and multi-channel delivery
- **Peer Review & QA** -- Radiology peer review with weighted random/targeted assignment, agreement scoring, discrepancy tracking, and radiologist scorecards with trend analysis

### Imaging Integration
- **DICOM Modality Worklist (MWL)** -- C-FIND SCP that serves scheduled procedures directly to scanners via pynetdicom
- **DICOM MPPS** -- Modality Performed Procedure Step (N-CREATE/N-SET) for real-time exam status tracking
- **DICOM C-STORE** -- Storage SCP accepting images from 8 SOP classes
- **PACS Connectivity** -- Orthanc DICOMweb adapter (QIDO-RS, WADO-RS, STOW-RS) with dcm4chee stub
- **OHIF Viewer** -- Study-level deep linking URL builder and OHIF config generator

### Interoperability
- **FHIR R5** -- Build and serve ImagingStudy, DiagnosticReport, ServiceRequest resources with full CapabilityStatement
- **HL7v2** -- Parse and build ORM^O01 (orders) and ORU^R01 (results) messages with round-trip fidelity
- **AI Integration** -- CAD overlay hooks, async study submission, HMAC-SHA256 webhook verification

### Operations
- **Radiation Dose Tracking** -- CTDIvol, DLP, DAP recording with Kenya NHIF DRL compliance checking and automated DRLExceeded alerts
- **Billing** -- CPT/ICD code management with order-level assignment and revenue analytics by modality/month
- **Analytics** -- Turnaround time metrics (5 intervals), workload analysis, volume statistics, operational dashboard
- **Scheduling** -- Room and technologist scheduling with conflict detection and availability queries

### Platform
- **Multi-Tenancy** -- Every table is tenant-scoped with context-based isolation via `TenantAwareRepository`
- **Pluggable Auth** -- Keycloak OIDC, generic OAuth2/JWKS, or API key authentication -- swap with one config change
- **RBAC** -- 20 fine-grained permissions across 5 roles (radiologist, technologist, referring_physician, clerk, admin), enforced on every endpoint
- **Domain Events** -- Async pub/sub event bus (OrderCreated, ReportFinalized, DRLExceeded, etc.) for extensibility
- **Audit Logging** -- Full audit trail with user, action, resource, and before/after state

## Quickstart

```bash
pip install sautiris
```

```bash
# Set your database URL
export SAUTIRIS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sautiris

# Run migrations
sautiris db upgrade

# Start the server
sautiris serve --host 0.0.0.0 --port 8080
```

Open http://localhost:8080/docs for the interactive API documentation.

## Installation

### From PyPI (Recommended)

```bash
pip install sautiris
```

### From Source

```bash
git clone https://github.com/iWorld-Afric/sautiris.git
cd sautiris
pip install -e ".[dev]"
```

### Requirements

- **Python 3.12+**
- **PostgreSQL 14+** (with asyncpg driver)
- Optional: Keycloak (for OIDC auth), Orthanc (for PACS), OHIF Viewer

## Usage

### Standalone Server

```bash
# Minimal setup
export SAUTIRIS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sautiris
export SAUTIRIS_AUTH_PROVIDER=apikey  # simplest auth for testing

sautiris db upgrade
sautiris serve
```

### Mount in an Existing FastAPI App

```python
from fastapi import FastAPI
from sautiris import create_ris_app

app = FastAPI(title="My Hospital System")

ris = create_ris_app(
    database_url="postgresql+asyncpg://localhost/hospital",
    auth_provider="keycloak",
    keycloak_server_url="http://keycloak:8080",
    keycloak_realm="hospital",
    keycloak_client_id="ris-backend",
    keycloak_jwks_url="http://keycloak:8080/realms/hospital/protocol/openid-connect/certs",
)
app.mount("/ris", ris)
```

### Mount in SautiCare

SautiRIS is designed to integrate seamlessly with [SautiCare](https://github.com/iWorld-Afric/sauticare-backend):

```python
from sautiris import create_ris_app
from sautiris.config import SautiRISSettings

settings = SautiRISSettings(
    database_url=os.getenv("DATABASE_URL"),
    auth_provider="keycloak",
    keycloak_server_url=os.getenv("KEYCLOAK_URL"),
    keycloak_realm="sauticare",
    keycloak_client_id="sauticare-backend",
    keycloak_jwks_url=os.getenv("KEYCLOAK_JWKS_URL"),
)
ris_app = create_ris_app(settings=settings)
main_app.mount("/api/v1/ris", ris_app)
```

### CLI Reference

```bash
sautiris serve          # Start the HTTP server
sautiris db upgrade     # Run database migrations
sautiris db seed        # Seed reference data
sautiris mwl start      # Start DICOM Modality Worklist SCP
sautiris --help         # Show all commands
```

## API Endpoints

| Module | Endpoints | Description |
|--------|:---------:|-------------|
| **Orders** | 11 | Full order lifecycle -- create, list, get, update, cancel, schedule, start, complete, history, stats, accession |
| **Schedule** | 8 | Room/slot scheduling with conflict detection and availability queries |
| **Reports** | 10 | Structured reporting -- create, save, finalize, amend, addendum, templates, versions |
| **Worklist** | 5 | DICOM worklist management with MPPS status updates |
| **Billing** | 5 | CPT/ICD code management, order assignment, revenue analytics |
| **Analytics** | 5 | TAT metrics, workload analysis, volume stats, quality metrics, dashboard |
| **Alerts** | 5 | Critical finding alerting, acknowledgment, escalation, stats |
| **Peer Review** | 6 | QA assignment, scoring, discrepancy reporting, scorecards |
| **Dose** | 5 | Radiation dose recording, patient history, DRL compliance |
| **FHIR** | 6+ | Read-only FHIR server -- ImagingStudy, DiagnosticReport, ServiceRequest, CapabilityStatement |
| **Health** | 3 | Liveness, readiness, and detailed system health |
| **Total** | **69+** | Plus 3 DICOM SCP services (MWL, MPPS, C-STORE) |

Full API documentation is auto-generated at `/docs` (Swagger UI) and `/redoc` (ReDoc) when the server is running.

## Architecture

```
sautiris/
  api/
    v1/              # FastAPI route handlers (69+ endpoints)
    deps.py          # Shared dependencies (auth, DB, RBAC)
  core/
    auth/            # Pluggable auth providers (Keycloak, OAuth2, API Key)
    permissions.py   # RBAC: 20 permissions x 5 roles
    tenancy.py       # Multi-tenant context + middleware
    events.py        # Domain event bus (async pub/sub)
    audit.py         # Audit logging
  models/            # 20 SQLAlchemy ORM models with multi-tenancy
  repositories/      # Tenant-aware data access layer (generic CRUD)
  services/          # Business logic with state machines + domain events
  integrations/
    dicom/           # MWL SCP, MPPS SCP, C-STORE SCP (pynetdicom)
    fhir/            # FHIR R5 resource builders + read-only server
    hl7v2/           # ORM/ORU parser and builder
    pacs/            # Orthanc DICOMweb adapter + dcm4chee stub
    viewer/          # OHIF viewer URL builder + config
    ai/              # AI provider adapter + webhook handler
  migrations/        # Alembic database migrations
  config.py          # Pydantic Settings (40+ env vars)
  app.py             # create_ris_app() factory
  cli.py             # Click-based CLI
```

### Key Design Decisions

- **Repository Pattern** -- All database access goes through `TenantAwareRepository[T]`, which auto-filters by `tenant_id`
- **Domain Events** -- Services emit events (OrderCreated, ReportFinalized, etc.) via an async event bus, enabling loose coupling
- **State Machines** -- Order and report status transitions are validated against a `VALID_TRANSITIONS` mapping; invalid transitions raise exceptions
- **Pluggable Adapters** -- PACS, Viewer, AI, and Auth all use ABC base classes, making it trivial to swap implementations
- **String Enums in DB** -- All enums use `String(N)` columns (not native PG ENUM) for SQLite test compatibility and easier migrations

## Configuration

SautiRIS is configured via environment variables prefixed with `SAUTIRIS_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_DATABASE_URL` | required | PostgreSQL async connection string |
| `SAUTIRIS_AUTH_PROVIDER` | `keycloak` | Auth backend: `keycloak`, `oauth2`, `apikey` |
| `SAUTIRIS_KEYCLOAK_SERVER_URL` | -- | Keycloak base URL |
| `SAUTIRIS_KEYCLOAK_REALM` | -- | Keycloak realm name |
| `SAUTIRIS_KEYCLOAK_CLIENT_ID` | -- | OIDC client ID |
| `SAUTIRIS_PACS_TYPE` | `orthanc` | PACS backend: `orthanc`, `dcm4chee` |
| `SAUTIRIS_ORTHANC_URL` | -- | Orthanc DICOMweb base URL |
| `SAUTIRIS_MWL_AE_TITLE` | `SAUTIRIS_MWL` | DICOM MWL SCP AE Title |
| `SAUTIRIS_MWL_PORT` | `11112` | DICOM MWL SCP port |

See [docs/configuration.md](docs/configuration.md) for the complete list of 40+ configuration options.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, database setup, first steps |
| [Configuration](docs/configuration.md) | Complete environment variable reference |
| [API Reference](docs/api-reference.md) | All 69+ endpoints with request/response schemas |
| [Deployment](docs/deployment.md) | Docker, Cloud Run, scaling, monitoring |
| [DICOM Setup](docs/dicom-setup.md) | MWL/MPPS/C-STORE configuration, scanner integration |
| [FHIR Interoperability](docs/fhir-interop.md) | FHIR R5 resources, HL7v2 messaging |
| [SautiCare Integration](docs/integration-guide.md) | Mounting in SautiCare, auth pass-through, E2E workflow |

## Development

### Setup

```bash
git clone https://github.com/iWorld-Afric/sautiris.git
cd sautiris
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=sautiris --cov-report=term-missing

# Run a specific test module
pytest tests/test_services/test_order_service.py -v
```

Tests use **SQLite in-memory** -- no PostgreSQL required for development.

### Linting and Type Checking

```bash
# Lint
ruff check src/ tests/

# Auto-fix
ruff check src/ tests/ --fix

# Type check
mypy src/sautiris/
```

### Building

```bash
# Build wheel + sdist
python -m build

# Verify package
twine check dist/*
```

### Project Structure for Contributors

```
tests/
  test_api/          # API endpoint tests
  test_core/         # Auth, permissions, events, tenancy tests
  test_dicom/        # DICOM SCP tests
  test_integrations/ # FHIR, HL7v2, PACS, Viewer, AI tests
  test_repositories/ # Data access layer tests
  test_services/     # Business logic tests
  conftest.py        # Shared fixtures (SQLite, mock auth, factories)
  factories.py       # Factory Boy factories for all 15+ models
```

## Contributing

We welcome contributions from the community! Whether it's a bug report, feature request, documentation improvement, or code contribution -- every bit helps.

### How to Contribute

1. **Fork the repository** on GitHub
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
3. **Make your changes** following our coding standards (see below)
4. **Write or update tests** -- we require tests for all new functionality
5. **Ensure all quality gates pass**:
   ```bash
   ruff check src/ tests/
   mypy src/sautiris/
   pytest tests/ -v
   ```
6. **Commit with a clear message**:
   ```bash
   git commit -m "feat: add support for XYZ"
   ```
7. **Push your branch** and open a Pull Request against `main`

### Coding Standards

- **Python 3.12+** -- Use modern syntax (type unions with `|`, StrEnum, etc.)
- **Type hints on ALL functions** -- No `Any` unless absolutely necessary
- **Async by default** -- All DB operations and HTTP calls must be async
- **Repository pattern** -- Database access goes through repositories, never raw queries in services
- **Pydantic v2** -- Request/response schemas, settings, and validation
- **ruff** -- Line length 100, select rules: E, F, I, N, UP, B, SIM
- **mypy strict** -- Full strict mode with Pydantic plugin

### Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use Case |
|--------|----------|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `refactor:` | Code change that neither fixes nor adds |
| `test:` | Adding or updating tests |
| `chore:` | Build, CI, tooling changes |
| `perf:` | Performance improvement |
| `security:` | Security fix |

### Pull Request Guidelines

- **One PR per feature/fix** -- Keep PRs focused and reviewable
- **Link to an issue** -- Reference the GitHub issue number in your PR description
- **Include tests** -- PRs without tests for new functionality will be requested to add them
- **Update docs** -- If your change affects the API or configuration, update the relevant docs
- **No breaking changes** without discussion -- Open an issue first if you need to change the public API

### Reporting Bugs

Open a [GitHub Issue](https://github.com/iWorld-Afric/sautiris/issues/new) with:

1. **Description** of the bug
2. **Steps to reproduce**
3. **Expected vs actual behavior**
4. **Environment** (Python version, OS, database version)
5. **Error logs** (with PHI/PII redacted)

### Requesting Features

Open a [GitHub Issue](https://github.com/iWorld-Afric/sautiris/issues/new) with:

1. **Use case** -- What problem does this solve?
2. **Proposed solution** -- How should it work?
3. **Alternatives considered** -- What other approaches did you evaluate?

### Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code. Please report unacceptable behavior to dev@iworldafric.com.

## Security

### Reporting Vulnerabilities

**Do NOT open a public issue for security vulnerabilities.**

Instead, email **dev@iworldafric.com** with:

1. Description of the vulnerability
2. Steps to reproduce
3. Potential impact assessment
4. Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a timeline for a fix. Security fixes are released as patch versions.

### Security Features

- RBAC with 20 permissions enforced on every endpoint
- Pluggable auth with JWT verification (JWKS rotation supported)
- Multi-tenant data isolation at the repository layer
- Input validation via Pydantic on all request schemas
- HMAC-SHA256 verification on AI webhook payloads
- Audit logging of all state-changing operations
- No hardcoded secrets -- all credentials via environment variables

## Roadmap

### v1.0.0 (Stable Release)
- [ ] GitHub Actions CI/CD pipeline
- [ ] 90%+ test coverage
- [ ] Docker image on GHCR
- [ ] Helm chart for Kubernetes
- [ ] Integration tests against real PostgreSQL

### v1.1.0
- [ ] Teaching file management
- [ ] Speech-to-text dictation integration
- [ ] Report distribution (HL7v2 ORU, FHIR messaging, email PDF)
- [ ] Multi-language report templates (English, Swahili)

### v1.2.0
- [ ] Mammography-specific workflow (BI-RADS)
- [ ] Prior study comparison workflow
- [ ] Advanced analytics with configurable dashboards
- [ ] Audit log export (ATNA/Syslog)

### v2.0.0
- [ ] Real-time collaboration (WebSocket-based)
- [ ] DICOM SR (Structured Report) native support
- [ ] IHE profile compliance (SWF, RWF, KIN)
- [ ] Federated learning integration for AI models

## License

Licensed under the [Apache License 2.0](LICENSE).

```
Copyright 2026 iWorldAfric

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

## Acknowledgments

- Built by [iWorldAfric](https://github.com/iWorld-Afric) for the African healthcare community
- Part of the [SautiCare](https://github.com/iWorld-Afric/sauticare-backend) healthcare platform
- Powered by [FastAPI](https://fastapi.tiangolo.com/), [SQLAlchemy](https://www.sqlalchemy.org/), [pynetdicom](https://pydicom.github.io/pynetdicom/), [HAPI FHIR](https://hapifhir.io/)
- DICOM standards by [NEMA](https://www.dicomstandard.org/)
- FHIR standard by [HL7 International](https://www.hl7.org/fhir/)

---

<p align="center">
  <sub>Built with care for healthcare in Africa</sub>
</p>
