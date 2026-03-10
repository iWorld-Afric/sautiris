"""SautiRIS CLI built with Click."""

from __future__ import annotations

import csv
import json
import sys
import uuid as _uuid_mod
from datetime import UTC, datetime
from typing import IO

import click
import structlog

logger = structlog.get_logger(__name__)


@click.group()
def main() -> None:
    """SautiRIS — Open-source Radiology Information System."""


@main.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8080, type=int, help="Bind port")
@click.option("--workers", default=1, type=int, help="Worker count")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(host: str, port: int, workers: int, reload: bool) -> None:
    """Start the SautiRIS server."""
    import uvicorn

    uvicorn.run(
        "sautiris.app:create_ris_app",
        host=host,
        port=port,
        workers=workers,
        reload=reload,
        factory=True,
    )


@main.group()
def db() -> None:
    """Database management commands."""


@db.command()
def upgrade() -> None:
    """Run alembic upgrade head."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    click.echo("Database upgraded to head.")


@db.command()
def seed() -> None:
    """Seed reference data (CPT codes, report templates)."""
    click.echo("Seeding reference data... (not yet implemented)")


@main.group()
def security() -> None:
    """Security management commands."""


@security.command("rotate-key")
@click.option(
    "--old-key",
    required=False,
    default=None,
    envvar="SAUTIRIS_OLD_ENCRYPTION_KEY",
    help="Current Fernet encryption key (base64). Reads from env var or interactive prompt.",
    prompt="Old encryption key",
    hide_input=True,
)
@click.option(
    "--new-key",
    required=False,
    default=None,
    envvar="SAUTIRIS_NEW_ENCRYPTION_KEY",
    help="New Fernet encryption key (base64). Reads from env var or interactive prompt.",
    prompt="New encryption key",
    hide_input=True,
)
@click.option("--database-url", envvar="SAUTIRIS_DATABASE_URL", required=True, help="Database URL")
@click.pass_context
def rotate_key(ctx: click.Context, old_key: str, new_key: str, database_url: str) -> None:
    """Rotate the Fernet encryption key for all stored credentials.

    Decrypts all credential columns with OLD_KEY and re-encrypts with NEW_KEY
    in a single transaction. Rolls back on any failure.

    SECURITY: Pass keys via environment variables (SAUTIRIS_OLD_ENCRYPTION_KEY,
    SAUTIRIS_NEW_ENCRYPTION_KEY) or the interactive prompt — NOT as CLI arguments,
    which would expose them in the process list.
    """
    from cryptography.fernet import Fernet  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    from sautiris.core.crypto import rotate_encryption_key_detailed  # noqa: PLC0415

    # Warn if either key flag was passed directly on the command line (visible
    # in /proc/*/cmdline on Linux).
    if any(arg in sys.argv[1:] for arg in ("--old-key", "--new-key")):
        logger.warning(
            "security.rotate_key.arg_exposure",
            msg=(
                "Encryption keys passed as CLI arguments are visible in the OS process list "
                "(/proc/*/cmdline). Use environment variables or the interactive prompt instead."
            ),
        )
        click.echo(
            "WARNING: Passing keys as CLI arguments exposes them in the process list. "
            "Use SAUTIRIS_OLD_ENCRYPTION_KEY / SAUTIRIS_NEW_ENCRYPTION_KEY env vars instead.",
            err=True,
        )

    # Validate keys before touching the database.
    for label, key in [("old-key", old_key), ("new-key", new_key)]:
        try:
            Fernet(key.encode())
        except Exception as exc:
            raise click.BadParameter(f"Invalid Fernet key for --{label}: {exc}") from exc

    engine = create_engine(database_url)
    with engine.begin() as conn:
        result = rotate_encryption_key_detailed(conn, old_key, new_key)
    engine.dispose()

    click.echo(f"Key rotation complete: {result.rotated_count} value(s) re-encrypted.")
    if result.skipped_count:
        click.echo(f"Warning: {result.skipped_count} plaintext value(s) skipped (not encrypted).")
    click.echo("Update SAUTIRIS_ENCRYPTION_KEY to the new key before restarting the app.")


@main.group()
def mwl() -> None:
    """DICOM Modality Worklist commands."""


@mwl.command()
@click.option("--port", default=11112, type=int, help="MWL SCP port")
@click.option("--ae-title", default="SAUTIRIS_MWL", help="MWL AE Title")
def start(port: int, ae_title: str) -> None:
    """Start the DICOM MWL SCP server."""
    click.echo(f"Starting MWL SCP on port {port} with AE Title {ae_title}...")
    click.echo("MWL SCP not yet implemented.")


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------


@main.group()
def apikey() -> None:
    """Manage API keys."""


@apikey.command("create")
@click.option("--name", required=True, help="Human-readable name for the key")
@click.option("--user-id", "user_id", required=True, type=click.UUID, help="User UUID to associate")
@click.option("--tenant-id", "tenant_id", required=True, type=click.UUID, help="Tenant UUID")
@click.option(
    "--scopes",
    required=True,
    help="Comma-separated permission scopes (e.g. orders:read,reports:write)",
)
@click.option(
    "--expires-in-days",
    "expires_in_days",
    default=365,
    type=int,
    help="Days until key expires",
)
@click.option(
    "--database-url",
    envvar="SAUTIRIS_DATABASE_URL",
    required=True,
    help="Database URL (sync driver, e.g. postgresql+psycopg2://...)",
)
def create_apikey(
    name: str,
    user_id: _uuid_mod.UUID,
    tenant_id: _uuid_mod.UUID,
    scopes: str,
    expires_in_days: int,
    database_url: str,
) -> None:
    """Create a new API key.

    The raw key is printed ONCE to stdout. Store it immediately — it cannot be
    retrieved again. The database only holds the SHA-256 hash.
    """
    from datetime import timedelta  # noqa: PLC0415

    from sqlalchemy import create_engine, text  # noqa: PLC0415

    from sautiris.repositories.apikey_repo import generate_api_key  # noqa: PLC0415

    # Generate the raw key, hash, and prefix using the canonical function.
    raw_key, key_hash, key_prefix = generate_api_key()

    now = datetime.now(UTC)
    expires_at = now + timedelta(days=expires_in_days)
    key_id = _uuid_mod.uuid4()

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]

    # Use a sync engine for CLI context (avoids asyncio event loop complexity).
    # Convert async URL scheme to sync if needed.
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    engine = create_engine(sync_url)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO api_keys "
                "(id, tenant_id, user_id, name, key_hash, key_prefix, "
                "scopes, permissions, expires_at, created_at, is_active) "
                "VALUES (:id, :tenant_id, :user_id, :name, :key_hash, :key_prefix, "
                ":scopes, :permissions, :expires_at, :created_at, :is_active)"
            ),
            {
                "id": str(key_id),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "name": name,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "scopes": json.dumps(scope_list),
                "permissions": json.dumps([]),
                "expires_at": expires_at,
                "created_at": now,
                "is_active": True,
            },
        )
    engine.dispose()

    click.echo("\nAPI key created successfully.")
    click.echo(f"  ID         : {key_id}")
    click.echo(f"  Name       : {name}")
    click.echo(f"  User       : {user_id}")
    click.echo(f"  Tenant     : {tenant_id}")
    click.echo(f"  Scopes     : {', '.join(scope_list)}")
    click.echo(f"  Expires at : {expires_at.isoformat()}")
    click.echo("\n  Raw key (save this — it will NOT be shown again):")
    click.echo(f"  {raw_key}\n")


# ---------------------------------------------------------------------------
# Audit log management
# ---------------------------------------------------------------------------


@main.group()
def audit() -> None:
    """Audit log management."""


@audit.command("export")
@click.option(
    "--from",
    "from_dt",
    type=click.DateTime(formats=["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]),
    default=None,
    help="Start datetime (ISO format, e.g. 2026-01-01 or 2026-01-01T00:00:00)",
)
@click.option(
    "--to",
    "to_dt",
    type=click.DateTime(formats=["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]),
    default=None,
    help="End datetime (ISO format, e.g. 2026-12-31 or 2026-12-31T23:59:59)",
)
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "csv"]),
    default="json",
    show_default=True,
    help="Output format",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output file path. Defaults to stdout if not specified.",
)
@click.option(
    "--database-url",
    envvar="SAUTIRIS_DATABASE_URL",
    required=True,
    help="Database URL (sync driver, e.g. postgresql+psycopg2://...)",
)
def export_audit(
    from_dt: datetime | None,
    to_dt: datetime | None,
    fmt: str,
    output: str | None,
    database_url: str,
) -> None:
    """Export audit logs to JSON or CSV.

    Streams results to stdout or writes to a file. Useful for compliance
    reporting and forensic analysis.

    Examples:

        sautiris audit export --format csv -o /tmp/audit.csv

        sautiris audit export --from 2026-01-01 --to 2026-03-31 --format json -o report.json
    """
    from sqlalchemy import create_engine, text  # noqa: PLC0415

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

    # Build parameterised query with optional date filters.
    conditions: list[str] = []
    params: dict[str, object] = {}

    if from_dt is not None:
        if from_dt.tzinfo is None:
            from_dt = from_dt.replace(tzinfo=UTC)
        conditions.append("created_at >= :from_dt")
        params["from_dt"] = from_dt

    if to_dt is not None:
        if to_dt.tzinfo is None:
            to_dt = to_dt.replace(tzinfo=UTC)
        conditions.append("created_at <= :to_dt")
        params["to_dt"] = to_dt

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = text(
        f"SELECT id, tenant_id, user_id, user_name, action, resource_type, "  # noqa: S608
        f"resource_id, patient_id, ip_address, user_agent, correlation_id, "
        f"details, created_at "
        f"FROM audit_logs {where_clause} ORDER BY created_at ASC"
    )

    engine = create_engine(sync_url)
    with engine.connect() as conn:
        result = conn.execute(query, params)
        columns = list(result.keys())
        rows = result.fetchall()
    engine.dispose()

    def _serialize_row(row: object) -> dict[str, object]:
        record: dict[str, object] = {}
        for col, val in zip(columns, row, strict=False):  # type: ignore[call-overload]
            if isinstance(val, datetime):
                record[col] = val.isoformat()
            elif not isinstance(val, (str, int, float, bool, type(None))):
                record[col] = str(val)
            else:
                record[col] = val
        return record

    out: IO[str]
    if output:
        newline = "" if fmt == "csv" else None
        out = open(output, "w", encoding="utf-8", newline=newline)  # noqa: SIM115
    else:
        out = sys.stdout

    try:
        if fmt == "json":
            for row in rows:
                out.write(json.dumps(_serialize_row(row), default=str) + "\n")
        else:
            writer = csv.DictWriter(out, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow(_serialize_row(row))
    finally:
        if output and out is not sys.stdout:
            out.close()

    count = len(rows)
    click.echo(
        f"Exported {count} audit record(s) as {fmt.upper()}"
        + (f" to {output}" if output else " to stdout"),
        err=True,
    )
