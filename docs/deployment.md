# Deployment

## Requirements

- Python 3.12+
- PostgreSQL 15+ (with asyncpg)
- (Optional) Redis for caching
- (Optional) Keycloak for OIDC authentication

## Docker

### Dockerfile

```dockerfile
FROM python:3.13-slim

WORKDIR /app

RUN pip install --no-cache-dir sautiris

ENV SAUTIRIS_HOST=0.0.0.0
ENV SAUTIRIS_PORT=8080
ENV SAUTIRIS_WORKERS=4

EXPOSE 8080

CMD ["sautiris", "serve"]
```

### Docker Compose

```yaml
services:
  sautiris:
    build: .
    ports:
      - "8080:8080"
    environment:
      SAUTIRIS_DATABASE_URL: postgresql+asyncpg://sautiris:secret@db:5432/sautiris
      SAUTIRIS_AUTH_PROVIDER: keycloak
      SAUTIRIS_KEYCLOAK_SERVER_URL: http://keycloak:8080
      SAUTIRIS_KEYCLOAK_REALM: hospital
      SAUTIRIS_KEYCLOAK_CLIENT_ID: ris-backend
      SAUTIRIS_KEYCLOAK_JWKS_URL: http://keycloak:8080/realms/hospital/protocol/openid-connect/certs
    depends_on:
      - db

  db:
    image: postgres:16
    environment:
      POSTGRES_USER: sautiris
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: sautiris
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

## Google Cloud Run

```yaml
# cloud-run-service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: sautiris
spec:
  template:
    spec:
      containers:
        - image: gcr.io/PROJECT/sautiris:latest
          ports:
            - containerPort: 8080
          env:
            - name: SAUTIRIS_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: db-url
                  key: latest
          resources:
            limits:
              cpu: "2"
              memory: 1Gi
```

## Database Migrations

Always run migrations before starting a new version:

```bash
sautiris db upgrade
```

For production, include this in your CI/CD pipeline or as an init container.

## Health Checks

Configure your load balancer or orchestrator to probe:

```
GET /api/v1/health
```

Returns `200 OK` with system status.

## Scaling

- **Horizontal**: Increase worker count or replica count. SautiRIS is stateless.
- **Database**: Use connection pooling (PgBouncer) for high concurrency.
- **DICOM**: Run DICOM SCP services (MWL, MPPS) on dedicated instances with fixed ports.

## Monitoring

SautiRIS uses `structlog` for structured JSON logging. Key log events:

- `order_created`, `order_status_changed` -- Order lifecycle
- `report_finalized`, `report_amended` -- Report workflow
- `critical_alert_created`, `alert_escalated` -- Alert events
- `drl_exceeded` -- Radiation dose alerts
- `peer_review_submitted` -- QA events

Integrate with your log aggregator (ELK, Cloud Logging, Datadog) for dashboards and alerts.

## Security Checklist

- [ ] Set `SAUTIRIS_CORS_ORIGINS` to specific domains (not `*`)
- [ ] Use Keycloak or OAuth2 auth (not API key) in production
- [ ] Enable TLS termination at the load balancer
- [ ] Restrict database access to the application network
- [ ] Rotate API keys and secrets regularly
- [ ] Enable audit logging for PHI access
