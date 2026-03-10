"""SautiRIS CLI built with Click."""

from __future__ import annotations

import click


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
@click.option("--old-key", required=True, help="Current Fernet encryption key (base64)")
@click.option("--new-key", required=True, help="New Fernet encryption key (base64)")
@click.option("--database-url", envvar="SAUTIRIS_DATABASE_URL", required=True, help="Database URL")
def rotate_key(old_key: str, new_key: str, database_url: str) -> None:
    """Rotate the Fernet encryption key for all stored credentials.

    Decrypts all credential columns with OLD_KEY and re-encrypts with NEW_KEY
    in a single transaction. Rolls back on any failure.
    """
    from cryptography.fernet import Fernet  # noqa: PLC0415
    from sqlalchemy import create_engine  # noqa: PLC0415

    from sautiris.core.crypto import rotate_encryption_key  # noqa: PLC0415

    # Validate keys before touching the database
    for label, key in [("old-key", old_key), ("new-key", new_key)]:
        try:
            Fernet(key.encode())
        except Exception as exc:
            raise click.BadParameter(f"Invalid Fernet key for --{label}: {exc}") from exc

    engine = create_engine(database_url)
    with engine.begin() as conn:
        count = rotate_encryption_key(conn, old_key, new_key)
    engine.dispose()

    click.echo(f"Key rotation complete: {count} value(s) re-encrypted.")
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
