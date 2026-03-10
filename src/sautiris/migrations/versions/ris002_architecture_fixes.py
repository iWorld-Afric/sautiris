"""Architecture fixes: ReportVersion tenant isolation + accession counters.

Issue #27: Add tenant_id to report_versions table (was missing — bug).
Issue #53: Create accession_counters table for concurrent-safe generation.
Issue #22: Add correlation_id column to audit_logs table.

Revision ID: ris002
Revises: ris001
Create Date: 2026-03-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ris002"
down_revision: str | None = "ris001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # #27 — Fix ReportVersion tenant isolation
    # Add tenant_id + TenantAwareBase columns (created_at, updated_at)
    # -------------------------------------------------------------------------
    op.add_column("report_versions", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.add_column(
        "report_versions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "report_versions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )

    # Backfill tenant_id from the parent radiology_report row
    op.execute(
        """
        UPDATE report_versions rv
        SET tenant_id = rr.tenant_id
        FROM radiology_reports rr
        WHERE rv.report_id = rr.id
        """
    )

    # Once backfilled, set NOT NULL
    op.alter_column("report_versions", "tenant_id", nullable=False)
    op.alter_column("report_versions", "created_at", nullable=False)
    op.alter_column("report_versions", "updated_at", nullable=False)

    op.create_index(
        "ix_report_versions_tenant_id",
        "report_versions",
        ["tenant_id"],
    )

    # -------------------------------------------------------------------------
    # #53 — Concurrent-safe accession number generation
    # -------------------------------------------------------------------------
    op.create_table(
        "accession_counters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("counter_key", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("date_prefix", sa.String(8), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("counter_key", name="uq_accession_counters_key"),
    )
    op.create_index(
        "ix_accession_counters_counter_key",
        "accession_counters",
        ["counter_key"],
        unique=True,
    )
    op.create_index(
        "ix_accession_counters_tenant_id",
        "accession_counters",
        ["tenant_id"],
    )

    # -------------------------------------------------------------------------
    # #22 — Add correlation_id to audit_logs
    # -------------------------------------------------------------------------
    op.add_column(
        "audit_logs",
        sa.Column("correlation_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_audit_logs_correlation_id",
        "audit_logs",
        ["correlation_id"],
    )


def downgrade() -> None:
    # audit_logs
    op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    op.drop_column("audit_logs", "correlation_id")

    # accession_counters
    op.drop_index("ix_accession_counters_tenant_id", table_name="accession_counters")
    op.drop_index("ix_accession_counters_counter_key", table_name="accession_counters")
    op.drop_table("accession_counters")

    # report_versions
    op.drop_index("ix_report_versions_tenant_id", table_name="report_versions")
    op.drop_column("report_versions", "updated_at")
    op.drop_column("report_versions", "created_at")
    op.drop_column("report_versions", "tenant_id")
