# Configuration

SautiRIS uses Pydantic Settings with environment variable support. All settings use the `SAUTIRIS_` prefix.

## Environment Variables

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_DATABASE_URL` | `postgresql+asyncpg://localhost:5432/sautiris` | Async database connection URL |
| `SAUTIRIS_DB_ECHO` | `false` | Enable SQL query logging |
| `SAUTIRIS_DB_POOL_SIZE` | `10` | Connection pool size |
| `SAUTIRIS_DB_MAX_OVERFLOW` | `20` | Maximum pool overflow connections |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_AUTH_PROVIDER` | `keycloak` | Auth mode: `keycloak`, `oauth2`, or `apikey` |
| `SAUTIRIS_KEYCLOAK_SERVER_URL` | `""` | Keycloak server base URL |
| `SAUTIRIS_KEYCLOAK_REALM` | `""` | Keycloak realm name |
| `SAUTIRIS_KEYCLOAK_CLIENT_ID` | `""` | Keycloak client ID |
| `SAUTIRIS_KEYCLOAK_JWKS_URL` | `""` | Keycloak JWKS endpoint |
| `SAUTIRIS_OAUTH2_JWKS_URL` | `""` | Generic OAuth2 JWKS endpoint |
| `SAUTIRIS_OAUTH2_ISSUER` | `""` | OAuth2 token issuer |
| `SAUTIRIS_OAUTH2_AUDIENCE` | `""` | Expected JWT audience |
| `SAUTIRIS_API_KEY_HEADER` | `X-API-Key` | API key header name |

### PACS

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_PACS_TYPE` | `orthanc` | PACS type: `orthanc`, `dcm4chee`, or `custom` |
| `SAUTIRIS_ORTHANC_BASE_URL` | `http://localhost:8042` | Orthanc REST API URL |
| `SAUTIRIS_ORTHANC_DICOMWEB_ROOT` | `/dicom-web` | DICOMweb endpoint root |
| `SAUTIRIS_ORTHANC_USERNAME` | `""` | Orthanc basic auth username |
| `SAUTIRIS_ORTHANC_PASSWORD` | `""` | Orthanc basic auth password |

### DICOM

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_DICOM_MWL_PORT` | `11112` | Modality Worklist SCP port |
| `SAUTIRIS_DICOM_MWL_AE_TITLE` | `SAUTIRIS_MWL` | MWL AE Title |
| `SAUTIRIS_DICOM_MPPS_PORT` | `11113` | MPPS SCP port |
| `SAUTIRIS_DICOM_MPPS_AE_TITLE` | `SAUTIRIS_MPPS` | MPPS AE Title |
| `SAUTIRIS_DICOM_STORE_PORT` | `11114` | C-STORE SCP port |
| `SAUTIRIS_DICOM_STORE_AE_TITLE` | `SAUTIRIS_STORE` | C-STORE AE Title |

### FHIR

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_FHIR_BASE_URL` | `""` | FHIR server base URL |
| `SAUTIRIS_FHIR_AUTH_TOKEN` | `""` | Bearer token for FHIR server |

### Viewer

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_VIEWER_TYPE` | `ohif` | Viewer type: `ohif` or `custom` |
| `SAUTIRIS_OHIF_BASE_URL` | `http://localhost:3000` | OHIF viewer URL |
| `SAUTIRIS_OHIF_DICOMWEB_DATASOURCE` | `""` | OHIF DICOMweb data source name |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_ENABLE_DICOM_MWL` | `true` | Enable DICOM Modality Worklist |
| `SAUTIRIS_ENABLE_DICOM_MPPS` | `true` | Enable DICOM MPPS |
| `SAUTIRIS_ENABLE_FHIR` | `true` | Enable FHIR resource generation |
| `SAUTIRIS_ENABLE_HL7V2` | `false` | Enable HL7v2 messaging |
| `SAUTIRIS_ENABLE_AI` | `false` | Enable AI integration hooks |
| `SAUTIRIS_ENABLE_VIEWER` | `true` | Enable viewer integration |
| `SAUTIRIS_ENABLE_DOSE_TRACKING` | `true` | Enable radiation dose tracking |
| `SAUTIRIS_ENABLE_PEER_REVIEW` | `true` | Enable peer review QA |
| `SAUTIRIS_ENABLE_BILLING` | `true` | Enable billing module |

### Multi-Tenancy

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_DEFAULT_TENANT_ID` | `00000000-0000-0000-0000-000000000001` | Default tenant UUID |
| `SAUTIRIS_TENANT_HEADER` | `X-Tenant-ID` | HTTP header for tenant ID |
| `SAUTIRIS_TENANT_JWT_CLAIM` | `tenant_id` | JWT claim containing tenant ID |

### Server

| Variable | Default | Description |
|----------|---------|-------------|
| `SAUTIRIS_HOST` | `0.0.0.0` | Server bind host |
| `SAUTIRIS_PORT` | `8080` | Server bind port |
| `SAUTIRIS_WORKERS` | `1` | Uvicorn worker count |
| `SAUTIRIS_LOG_LEVEL` | `info` | Log level |
| `SAUTIRIS_CORS_ORIGINS` | `["*"]` | CORS allowed origins |

## .env File

Settings can also be loaded from a `.env` file in the working directory:

```env
SAUTIRIS_DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/sautiris
SAUTIRIS_AUTH_PROVIDER=keycloak
SAUTIRIS_KEYCLOAK_SERVER_URL=http://keycloak:8080
SAUTIRIS_KEYCLOAK_REALM=hospital
SAUTIRIS_KEYCLOAK_CLIENT_ID=ris-backend
SAUTIRIS_KEYCLOAK_JWKS_URL=http://keycloak:8080/realms/hospital/protocol/openid-connect/certs
```

## Programmatic Configuration

```python
from sautiris.config import SautiRISSettings
from sautiris import create_ris_app

settings = SautiRISSettings(
    database_url="postgresql+asyncpg://localhost/sautiris",
    auth_provider="oauth2",
    oauth2_jwks_url="https://auth.example.com/.well-known/jwks.json",
    enable_ai=True,
    enable_hl7v2=True,
)
app = create_ris_app(settings=settings)
```
