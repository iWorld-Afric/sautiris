# SautiRIS

[![PyPI version](https://img.shields.io/pypi/v/sautiris)](https://pypi.org/project/sautiris/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-306%20passed-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-82%25-brightgreen)]()

**Open-source Radiology Information System (RIS)** built with FastAPI, SQLAlchemy async, and Python 3.12+.

SautiRIS provides a complete, production-ready RIS backend with order management, DICOM Modality Worklist, structured reporting, peer review QA, radiation dose tracking, FHIR R4/R5 interoperability, HL7v2 messaging, and AI integration hooks. Designed for healthcare facilities in Kenya and across Africa.

## Features

- **Order Management** -- Full radiology order lifecycle (request, schedule, exam, complete, cancel) with accession number generation
- **DICOM Integration** -- Modality Worklist SCP, MPPS SCP, C-STORE SCP for seamless scanner connectivity
- **Structured Reporting** -- Draft, finalize, amend, addendum workflow with versioning and templates
- **Peer Review & QA** -- Radiology peer review with agreement scoring, discrepancy tracking, and radiologist scorecards with trend analysis
- **Radiation Dose Tracking** -- Dose recording with Kenya NHIF DRL compliance checking and automated alerts
- **Critical Alerts** -- Critical finding alerting with notification dispatch, auto-escalation, and acknowledgment tracking
- **FHIR R4/R5** -- Build and validate ImagingStudy, DiagnosticReport, and ServiceRequest resources
- **HL7v2** -- Parse and build ORM^O01 (orders) and ORU^R01 (results) messages with round-trip fidelity
- **PACS Connectivity** -- Orthanc and DCM4CHEE adapter stubs with DICOMweb query/retrieve
- **Viewer Integration** -- OHIF viewer URL generation with study-level deep linking
- **AI Integration** -- CAD overlay hooks, webhook handler for async AI providers, HMAC-SHA256 validation
- **Billing** -- CPT/procedure code management with order-level billing assignment
- **Analytics** -- Turnaround time metrics, workload analysis, volume statistics, operational dashboard
- **Multi-Tenancy** -- Tenant-aware repositories with context-based isolation
- **Pluggable Auth** -- Keycloak, OAuth2/OIDC, or API key authentication providers
- **RBAC** -- Fine-grained permission system with role-to-permission mappings

## Quickstart

```bash
pip install sautiris
```

### Standalone Server

```bash
# Set database URL
export SAUTIRIS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sautiris

# Run migrations
sautiris db upgrade

# Start the server
sautiris serve --host 0.0.0.0 --port 8080
```

### Mount in an Existing FastAPI App

```python
from fastapi import FastAPI
from sautiris import create_ris_app

app = FastAPI(title="My Hospital App")

# Mount SautiRIS at /ris
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

### SautiCare Integration

SautiRIS is designed to integrate with [SautiCare](https://github.com/iworldafric/sauticare), passing through auth and tenant context:

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

## API Endpoints

| Module | Endpoints | Description |
|--------|-----------|-------------|
| Orders | 10 | Full order lifecycle management |
| Schedule | 7 | Room/slot scheduling with conflict detection |
| Reports | 10 | Structured reporting with templates |
| Worklist | 6 | DICOM worklist management with MPPS |
| Billing | 5 | CPT code management and assignment |
| Analytics | 5 | TAT, workload, volume statistics |
| Alerts | 5 | Critical finding alerting and escalation |
| Peer Review | 6 | QA workflow with scorecards |
| Dose | 5 | Radiation dose tracking and DRL compliance |
| Health | 1 | System health check |
| **Total** | **60** | |

## Development

```bash
# Clone and install
git clone https://github.com/iworldafric/sautiris.git
cd sautiris
pip install -e ".[dev]"

# Run tests
pytest tests/ -v --cov=sautiris

# Lint and type check
ruff check src/ tests/
mypy src/sautiris/

# Build
python -m build
```

## Documentation

- [Getting Started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [API Reference](docs/api-reference.md)
- [Deployment](docs/deployment.md)
- [DICOM Setup](docs/dicom-setup.md)
- [FHIR Interoperability](docs/fhir-interop.md)
- [SautiCare Integration](docs/integration-guide.md)

## Architecture

```
sautiris/
  api/v1/         # FastAPI route handlers
  core/           # Auth, tenancy, permissions, events
  models/         # SQLAlchemy ORM models
  repositories/   # Tenant-aware data access layer
  services/       # Business logic layer
  integrations/   # DICOM, FHIR, HL7v2, PACS, Viewer, AI
  migrations/     # Alembic database migrations
```

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome. Please open an issue first to discuss proposed changes.
