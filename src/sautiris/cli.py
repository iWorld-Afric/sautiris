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
def mwl() -> None:
    """DICOM Modality Worklist commands."""


@mwl.command()
@click.option("--port", default=11112, type=int, help="MWL SCP port")
@click.option("--ae-title", default="SAUTIRIS_MWL", help="MWL AE Title")
def start(port: int, ae_title: str) -> None:
    """Start the DICOM MWL SCP server."""
    click.echo(f"Starting MWL SCP on port {port} with AE Title {ae_title}...")
    click.echo("MWL SCP not yet implemented.")
