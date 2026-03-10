"""Add mpps_instances table for DICOM MPPS state machine (Issue #14).

Revision ID: ris002
Revises: ris001
Create Date: 2026-03-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ris002"
down_revision: str | None = "ris001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mpps_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sop_instance_uid", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="IN PROGRESS"),
        sa.Column("performed_station_ae", sa.String(64), nullable=True),
        sa.Column("modality", sa.String(16), nullable=True),
        sa.Column("performed_procedure_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performed_procedure_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "worklist_item_id",
            sa.Uuid(),
            sa.ForeignKey("worklist_items.id"),
            nullable=True,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mpps_instances_tenant", "mpps_instances", ["tenant_id"])
    op.create_index("ix_mpps_instances_sop_uid", "mpps_instances", ["sop_instance_uid"])
    op.create_index("ix_mpps_instances_worklist", "mpps_instances", ["worklist_item_id"])


def downgrade() -> None:
    op.drop_table("mpps_instances")
