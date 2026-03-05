# Getting Started

## Prerequisites

- Python 3.12 or 3.13
- PostgreSQL 15+ with asyncpg support
- (Optional) Keycloak for OIDC authentication
- (Optional) Orthanc or DCM4CHEE for PACS connectivity

## Installation

### From PyPI

```bash
pip install sautiris
```

### From Source

```bash
git clone https://github.com/iworldafric/sautiris.git
cd sautiris
pip install -e ".[dev]"
```

## Database Setup

SautiRIS requires a PostgreSQL database. Create one and set the connection URL:

```bash
createdb sautiris
export SAUTIRIS_DATABASE_URL=postgresql+asyncpg://localhost:5432/sautiris
```

Run migrations:

```bash
sautiris db upgrade
```

## Starting the Server

### CLI

```bash
sautiris serve --host 0.0.0.0 --port 8080
```

Options:
- `--host` -- Bind address (default: `0.0.0.0`)
- `--port` -- Port number (default: `8080`)
- `--workers` -- Number of Uvicorn workers (default: `1`)
- `--reload` -- Enable auto-reload for development

### Programmatic

```python
from sautiris import create_ris_app

app = create_ris_app(
    database_url="postgresql+asyncpg://localhost/sautiris",
    auth_provider="apikey",
)
```

## First Steps

1. **Health check**: `GET /api/v1/health`
2. **Create an order**: `POST /api/v1/orders`
3. **Schedule a slot**: `POST /api/v1/schedule/slots`
4. **Create a report**: `POST /api/v1/reports`

See the [API Reference](api-reference.md) for full endpoint documentation.

## Authentication

SautiRIS supports three authentication modes:

| Mode | Use Case | Config |
|------|----------|--------|
| `keycloak` | Production with Keycloak OIDC | Set `SAUTIRIS_AUTH_PROVIDER=keycloak` |
| `oauth2` | Generic OAuth2/OIDC provider | Set `SAUTIRIS_AUTH_PROVIDER=oauth2` |
| `apikey` | Development or service-to-service | Set `SAUTIRIS_AUTH_PROVIDER=apikey` |

See [Configuration](configuration.md) for all authentication settings.

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v --cov=sautiris
```

Tests use SQLite in-memory for fast execution (no PostgreSQL required for testing).
