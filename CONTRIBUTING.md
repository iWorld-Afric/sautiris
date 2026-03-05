# Contributing to SautiRIS

Thank you for your interest in contributing to SautiRIS! This document provides guidelines and information for contributors.

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/sautiris.git
   cd sautiris
   ```
3. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. Create a feature branch:
   ```bash
   git checkout -b feat/your-feature-name
   ```

## Development Workflow

### Running Tests

```bash
# All tests (uses SQLite in-memory, no PostgreSQL needed)
pytest tests/ -v

# With coverage report
pytest tests/ --cov=sautiris --cov-report=term-missing

# Specific module
pytest tests/test_services/test_order_service.py -v
```

### Linting and Type Checking

All code must pass these checks before merging:

```bash
# Lint (ruff)
ruff check src/ tests/

# Auto-fix lint issues
ruff check src/ tests/ --fix

# Type check (mypy strict mode)
mypy src/sautiris/
```

### Quality Gates

Every PR must pass:

1. **ruff** -- Zero lint warnings
2. **mypy** -- Zero type errors (strict mode)
3. **pytest** -- All tests passing
4. **Coverage** -- No decrease in overall coverage

## Coding Standards

### Python Style

- **Python 3.12+** -- Use modern syntax: `X | Y` unions, `StrEnum`, `match/case` where appropriate
- **Type hints** -- Required on all function signatures. Avoid `Any` unless absolutely necessary
- **Async first** -- All database operations and HTTP calls must be async (`async def`, `await`)
- **Line length** -- 100 characters max

### Architecture Patterns

- **Repository Pattern** -- Database access goes through `TenantAwareRepository[T]`. Never write raw SQL in services or routes
- **Service Layer** -- Business logic lives in services (`src/sautiris/services/`). Routes are thin -- they validate input, call a service, and return the result
- **Domain Events** -- When a state change has side effects, emit a domain event rather than calling other services directly
- **Pluggable Adapters** -- External integrations (PACS, auth, AI) use ABC base classes in `base.py` with concrete implementations

### Pydantic

- Use **Pydantic v2** for all request/response schemas
- Use `model_config = {"from_attributes": True}` for ORM model serialization
- Use field validators for business rule enforcement
- Use `ConfigDict` not `class Config`

### SQLAlchemy

- Use **async sessions** (`AsyncSession`) everywhere
- Models inherit from `TenantAwareBase` (includes `id`, `tenant_id`, `created_at`, `updated_at`)
- Use `String(N)` columns for enums (not native PG ENUM) for SQLite test compatibility
- Add indexes on columns used in WHERE clauses and foreign keys

### Testing

- Write tests **before or alongside** implementation
- Use **Factory Boy** factories from `tests/factories.py` for test data
- Test both happy path and error cases
- API tests should test permission enforcement (both allowed and denied)
- Use `pytest.mark.asyncio` (auto mode enabled via `pyproject.toml`)

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add mammography BI-RADS workflow
fix: prevent duplicate accession numbers under concurrent load
docs: add DICOM scanner configuration examples
refactor: extract dose calculation into dedicated service
test: add edge case tests for report finalization
chore: update ruff to 0.9.0
perf: optimize worklist query with composite index
security: validate DICOM AE title format to prevent injection
```

## Pull Request Process

1. **Create an issue first** -- Discuss the change before implementing
2. **One PR per feature/fix** -- Keep changes focused and reviewable
3. **Write a clear PR description** including:
   - What the change does and why
   - Link to the related issue
   - Testing instructions
   - Screenshots (for API changes, show request/response examples)
4. **Include tests** -- PRs without tests for new functionality will be requested to add them
5. **Update documentation** -- If your change affects the API, configuration, or user-facing behavior
6. **Keep PRs small** -- Large PRs take longer to review. If a feature is big, break it into smaller PRs

## Project Structure

```
src/sautiris/
  api/v1/           # Route handlers -- one file per domain
  core/             # Cross-cutting: auth, permissions, tenancy, events, audit
  models/           # SQLAlchemy ORM models -- one file per table group
  repositories/     # Data access layer -- one file per domain
  services/         # Business logic -- one file per domain
  integrations/     # External system adapters (DICOM, FHIR, HL7v2, PACS, AI)
  migrations/       # Alembic migration scripts
  config.py         # Pydantic Settings
  app.py            # Application factory
  cli.py            # CLI entry points

tests/
  test_api/         # API endpoint tests
  test_core/        # Core module tests
  test_dicom/       # DICOM SCP tests
  test_integrations/ # Integration adapter tests
  test_repositories/ # Repository tests
  test_services/    # Service layer tests
  conftest.py       # Shared fixtures
  factories.py      # Factory Boy model factories
```

## Adding a New Feature

Here's the typical flow for adding a new domain feature:

1. **Model** -- Add SQLAlchemy model(s) in `src/sautiris/models/`
2. **Migration** -- Generate Alembic migration: `alembic revision --autogenerate -m "description"`
3. **Repository** -- Add repository in `src/sautiris/repositories/` extending `TenantAwareRepository`
4. **Service** -- Add business logic in `src/sautiris/services/`
5. **Schemas** -- Define Pydantic request/response schemas (inline in the router file or in a `schemas/` module)
6. **Router** -- Add API endpoints in `src/sautiris/api/v1/` with `require_permission()` on every endpoint
7. **Permissions** -- Add new permissions to `core/permissions.py` and update `ROLE_PERMISSIONS`
8. **Register router** -- Include the router in `src/sautiris/api/router.py`
9. **Factory** -- Add Factory Boy factory in `tests/factories.py`
10. **Tests** -- Write tests for repository, service, and API layers

## Need Help?

- Open a [Discussion](https://github.com/iWorld-Afric/sautiris/discussions) for questions
- Open an [Issue](https://github.com/iWorld-Afric/sautiris/issues) for bugs or feature requests
- Email dev@iworldafric.com for security concerns

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to abide by its terms.

## License

By contributing to SautiRIS, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
