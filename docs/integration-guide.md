# SautiCare Integration Guide

This guide covers integrating SautiRIS into the SautiCare healthcare platform.

## Overview

SautiRIS is designed as a standalone Python package that can be mounted into SautiCare's FastAPI backend. When integrated:

- **Auth passes through** -- SautiCare's Keycloak tokens are validated by SautiRIS
- **Tenant context propagates** -- Multi-tenancy flows from SautiCare to SautiRIS
- **Database shared** -- SautiRIS tables live in the same PostgreSQL database
- **PACS connects** -- SautiRIS manages DICOM connectivity to Orthanc

## Installation

Add to SautiCare's requirements:

```
sautiris>=1.0.0a1
```

Or install from PyPI:

```bash
pip install sautiris
```

## Mounting in SautiCare

In `sauticare-backend/app/main.py`:

```python
import os
from sautiris import create_ris_app
from sautiris.config import SautiRISSettings

# Configure SautiRIS with SautiCare's shared settings
ris_settings = SautiRISSettings(
    database_url=os.getenv("DATABASE_URL"),
    auth_provider="keycloak",
    keycloak_server_url=os.getenv("KEYCLOAK_URL"),
    keycloak_realm="sauticare",
    keycloak_client_id=os.getenv("KEYCLOAK_CLIENT_ID"),
    keycloak_jwks_url=os.getenv("KEYCLOAK_JWKS_URL"),
    pacs_type="orthanc",
    orthanc_base_url=os.getenv("ORTHANC_URL", "http://localhost:8042"),
    orthanc_username=os.getenv("ORTHANC_USER", ""),
    orthanc_password=os.getenv("ORTHANC_PASSWORD", ""),
)

ris_app = create_ris_app(settings=ris_settings)
app.mount("/api/v1/ris", ris_app)
```

## Auth Pass-Through

SautiRIS uses the same Keycloak realm and client as SautiCare. Configure it with the same JWKS URL so JWT tokens are validated consistently.

Required Keycloak roles for SautiRIS features:

| Role | Permissions |
|------|------------|
| `radiologist` | Full report access, peer review, dose tracking |
| `radiology_tech` | Order management, worklist, schedule |
| `referring_physician` | Order creation, report viewing |
| `admin` | All permissions including billing and analytics |

## Database Migrations

SautiRIS uses Alembic for migrations. Run them after mounting:

```bash
cd sautiris
sautiris db upgrade
```

Or run programmatically in SautiCare's startup:

```python
from alembic import command
from alembic.config import Config

alembic_cfg = Config("sautiris/alembic.ini")
command.upgrade(alembic_cfg, "head")
```

SautiRIS tables are prefixed (e.g., `radiology_orders`, `radiology_reports`) to avoid conflicts with SautiCare's existing tables.

## PACS Connectivity

### Orthanc Setup

1. Deploy Orthanc alongside SautiCare
2. Configure DICOMweb plugin in Orthanc
3. Set environment variables:

```env
SAUTIRIS_ORTHANC_BASE_URL=http://orthanc:8042
SAUTIRIS_ORTHANC_USERNAME=orthanc
SAUTIRIS_ORTHANC_PASSWORD=orthanc
```

### Verify Connectivity

```bash
curl http://localhost:8080/api/v1/ris/api/v1/health
```

## E2E Workflow

A complete radiology workflow through SautiCare + SautiRIS:

1. **Doctor creates order** -- `POST /api/v1/ris/api/v1/orders`
2. **Receptionist schedules** -- `POST /api/v1/ris/api/v1/orders/{id}/schedule`
3. **Scanner queries MWL** -- DICOM C-FIND to MWL SCP
4. **Tech starts exam** -- DICOM MPPS N-CREATE
5. **Tech completes exam** -- DICOM MPPS N-SET (COMPLETED)
6. **Images stored** -- DICOM C-STORE to Orthanc
7. **Radiologist reports** -- `POST /api/v1/ris/api/v1/reports`
8. **Report finalized** -- `POST /api/v1/ris/api/v1/reports/{id}/finalize`
9. **Critical alert** -- Auto-created if report marked critical
10. **Peer review** -- Random selection for QA

## Event Integration

SautiRIS emits domain events that SautiCare can subscribe to:

```python
from sautiris.core.events import event_bus

@event_bus.subscribe("DRLExceeded")
async def handle_drl_exceeded(event):
    # Create SautiCare notification
    await notification_service.send(
        user_id=event.payload["order_id"],
        message=f"Radiation dose exceeded DRL for {event.payload['modality']}",
    )

@event_bus.subscribe("OrderCreated")
async def handle_order_created(event):
    # Sync to DHIS2 or national registry
    pass
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 on RIS endpoints | Verify JWKS URL matches between SautiCare and SautiRIS |
| Missing tenant context | Ensure `X-Tenant-ID` header or JWT `tenant_id` claim is present |
| DICOM MWL empty | Check that orders are scheduled and MWL SCP is running |
| PACS connection refused | Verify Orthanc URL and credentials |
| Migration conflicts | SautiRIS uses its own Alembic branch; run both migration chains |
