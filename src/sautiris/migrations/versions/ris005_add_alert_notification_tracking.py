"""Add notification_failed and notification_error columns to critical_alerts.

Revision ID: ris005
Revises: ris004
Create Date: 2026-03-10

Adds two columns to track notification dispatch failures so the
auto-escalation worker can retry failed notifications (#42, #43, #44).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ris005"
down_revision: str | None = "ris004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "critical_alerts",
        sa.Column(
            "notification_failed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "critical_alerts",
        sa.Column("notification_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("critical_alerts", "notification_error")
    op.drop_column("critical_alerts", "notification_failed")
