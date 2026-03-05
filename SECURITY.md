# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report vulnerabilities by emailing **dev@iworldafric.com** with:

1. **Description** of the vulnerability
2. **Steps to reproduce** (minimal reproduction case)
3. **Impact assessment** (what could an attacker do?)
4. **Affected versions** (if known)
5. **Suggested fix** (if any)

### What to Expect

- **Acknowledgment** within 48 hours
- **Assessment** and severity rating within 5 business days
- **Fix timeline** communicated based on severity:
  - CRITICAL: Patch within 48 hours
  - HIGH: Patch within 7 days
  - MEDIUM: Patch in next release
  - LOW: Tracked for future release

### Disclosure Policy

- We follow **coordinated disclosure** -- we will work with you to understand and fix the issue before any public disclosure
- Credit will be given to reporters in the security advisory (unless you prefer to remain anonymous)
- We will publish a GitHub Security Advisory for all confirmed vulnerabilities

## Security Features

SautiRIS includes the following security measures:

### Authentication & Authorization
- Pluggable auth providers (Keycloak OIDC, OAuth2, API Key)
- JWT verification with JWKS key rotation support
- Fine-grained RBAC with 20 permissions enforced on every API endpoint
- Role-based access: radiologist, technologist, referring_physician, clerk, admin

### Data Protection
- Multi-tenant isolation at the repository layer (all queries scoped by `tenant_id`)
- Input validation via Pydantic on all request schemas
- No raw SQL -- all queries through SQLAlchemy ORM with parameterized queries
- Audit logging of all state-changing operations

### Integration Security
- HMAC-SHA256 verification on AI provider webhooks
- DICOM AE title validation
- PACS credentials stored encrypted (not in plaintext)
- FHIR resource validation before serving

### Operational Security
- No hardcoded secrets -- all credentials via environment variables
- Health check endpoints exclude sensitive configuration
- Structured logging with PII scrubbing
- Session-scoped database connections with automatic rollback on errors

## Best Practices for Deployers

1. **Always use HTTPS** in production
2. **Rotate JWT signing keys** regularly
3. **Use dedicated database credentials** per service (principle of least privilege)
4. **Enable PostgreSQL SSL** (`?sslmode=require` in connection string)
5. **Set `SAUTIRIS_AUTH_PROVIDER=keycloak`** in production (never `apikey` for user-facing deployments)
6. **Monitor audit logs** for unusual access patterns
7. **Keep dependencies updated** -- run `pip audit` regularly
