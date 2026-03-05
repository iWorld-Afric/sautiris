# API Reference

SautiRIS exposes a RESTful API under `/api/v1/`. All endpoints require authentication and operate within the current tenant context.

## OpenAPI Documentation

When running, interactive API docs are available at:

- **Swagger UI**: `http://localhost:8080/docs`
- **ReDoc**: `http://localhost:8080/redoc`
- **OpenAPI JSON**: `http://localhost:8080/openapi.json`

## Endpoint Summary

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | System health check |

### Orders (`/api/v1/orders`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/orders` | Create a new radiology order |
| GET | `/orders` | List orders with filtering |
| GET | `/orders/stats` | Order statistics by status/modality |
| GET | `/orders/next-accession` | Get next accession number |
| GET | `/orders/{id}` | Get order by ID |
| PUT | `/orders/{id}` | Update order |
| POST | `/orders/{id}/cancel` | Cancel order |
| POST | `/orders/{id}/schedule` | Schedule order |
| POST | `/orders/{id}/start-exam` | Start exam |
| POST | `/orders/{id}/complete-exam` | Complete exam |

### Schedule (`/api/v1/schedule`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/schedule/slots` | Create a scheduling slot |
| GET | `/schedule/slots` | List slots with date/room filtering |
| GET | `/schedule/rooms` | List available rooms |
| GET | `/schedule/slots/{id}` | Get slot details |
| PUT | `/schedule/slots/{id}` | Update slot |
| DELETE | `/schedule/slots/{id}` | Delete available slot |
| POST | `/schedule/slots/{id}/book` | Book a slot for an order |

### Reports (`/api/v1/reports`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/reports` | Create a draft report |
| GET | `/reports` | List reports |
| GET | `/reports/templates` | List report templates |
| POST | `/reports/templates` | Create report template |
| GET | `/reports/{id}` | Get report with versions |
| PUT | `/reports/{id}` | Update draft report |
| POST | `/reports/{id}/finalize` | Finalize report |
| POST | `/reports/{id}/amend` | Amend finalized report |
| POST | `/reports/{id}/addendum` | Add addendum |
| GET | `/reports/{id}/versions` | Get report version history |

### Worklist (`/api/v1/worklist`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/worklist` | Create worklist item |
| GET | `/worklist` | List worklist items |
| GET | `/worklist/stats` | Worklist statistics |
| GET | `/worklist/{id}` | Get worklist item |
| PUT | `/worklist/{id}/status` | Update procedure step status |
| POST | `/worklist/{id}/mpps` | Receive MPPS notification |

### Billing (`/api/v1/billing`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/billing/assign` | Assign billing code to order |
| GET | `/billing/order/{id}` | Get billing for order |
| DELETE | `/billing/{id}` | Remove billing assignment |
| GET | `/billing/codes` | Search billing codes |
| POST | `/billing/codes` | Create billing code |

### Analytics (`/api/v1/analytics`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/analytics/tat` | Record turnaround time event |
| GET | `/analytics/tat` | Get TAT metrics |
| GET | `/analytics/workload` | Get workload by radiologist |
| GET | `/analytics/volume` | Get volume statistics |
| GET | `/analytics/dashboard` | Get operational dashboard |

### Alerts (`/api/v1/alerts`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/alerts` | Create critical alert |
| GET | `/alerts` | List alerts |
| GET | `/alerts/stats` | Alert statistics |
| POST | `/alerts/{id}/acknowledge` | Acknowledge alert |
| POST | `/alerts/{id}/escalate` | Escalate alert |

### Peer Review (`/api/v1/peer-review`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/peer-review` | Create peer review |
| GET | `/peer-review` | List peer reviews |
| GET | `/peer-review/stats` | QA statistics |
| GET | `/peer-review/scorecard/{id}` | Radiologist scorecard |
| GET | `/peer-review/{id}` | Get review details |
| POST | `/peer-review/{id}/discrepancy` | Report discrepancy |

### Dose Tracking (`/api/v1/dose`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/dose` | Record dose |
| GET | `/dose/order/{id}` | Get dose for order |
| GET | `/dose/patient/{id}` | Patient dose history |
| GET | `/dose/stats` | Dose statistics by modality |
| GET | `/dose/drl-compliance` | DRL compliance report |

## Authentication

Include an authentication header based on your configured auth provider:

```bash
# Keycloak / OAuth2
curl -H "Authorization: Bearer <jwt_token>" http://localhost:8080/api/v1/orders

# API Key
curl -H "X-API-Key: <your_key>" http://localhost:8080/api/v1/orders
```

## Multi-Tenancy

Include the tenant header if not using JWT-based tenancy:

```bash
curl -H "X-Tenant-ID: <tenant_uuid>" http://localhost:8080/api/v1/orders
```

## Error Responses

All errors return JSON with `detail`:

```json
{
  "detail": "Order not found"
}
```

Standard HTTP status codes: 400 (bad request), 401 (unauthorized), 404 (not found), 409 (conflict), 500 (server error).
