"""Add study_instance_uid column to worklist_items table.

Revision ID: ris004
Revises: ris003
Create Date: 2026-03-10

Persists a stable StudyInstanceUID per worklist item so that repeated
MWL C-FIND queries return the same UID, enabling correct modality-study
linking (PATIENT SAFETY fix).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ris004"
down_revision: str | None = "ris003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "worklist_items",
        sa.Column("study_instance_uid", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worklist_items", "study_instance_uid")
