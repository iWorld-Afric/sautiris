"""Encrypt existing PACS passwords and AI api_key/webhook_secret at rest (issue #6).

Revision ID: ris003
Revises: ris002
Create Date: 2026-03-06

NOTE: This migration encrypts existing plaintext values using the Fernet key from
``SAUTIRIS_ENCRYPTION_KEY``.  If the env var is unset, existing rows are left
unchanged (suitable for development).  Run with the env var set in staging/prod.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# #79: Import _FERNET_PREFIX from crypto module instead of redefining it
from sautiris.core.crypto import _FERNET_PREFIX  # noqa: PLC0415

logger = logging.getLogger(__name__)

revision: str = "ris003"
down_revision: str | None = "ris002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    raw_key = os.environ.get("SAUTIRIS_ENCRYPTION_KEY", "")
    if not raw_key:
        # No key configured — skip encryption of existing rows.
        # New rows will be stored as plaintext until the key is set.
        return

    from cryptography.fernet import Fernet  # noqa: PLC0415

    fernet = Fernet(raw_key.encode())
    conn = op.get_bind()
    # encrypted_count tracks the number of *rows* that were re-encrypted across
    # all tables.  We deliberately count rows (not individual column values)
    # because the log message and key-rotation CLI output report "credential
    # records" — the number of database rows touched, not the number of columns.
    encrypted_count = 0

    # --- Encrypt pacs_connections.password ---
    pacs_rows = conn.execute(
        text("SELECT id, password FROM pacs_connections WHERE password IS NOT NULL")
    ).fetchall()
    for row_id, password in pacs_rows:
        if password and not str(password).startswith(_FERNET_PREFIX):
            encrypted = fernet.encrypt(str(password).encode()).decode()
            conn.execute(
                text("UPDATE pacs_connections SET password = :p WHERE id = :id"),
                {"p": encrypted, "id": str(row_id)},
            )
            # Increment once per *row* encrypted (not per column).
            encrypted_count += 1

    # --- Encrypt ai_provider_configs.api_key and .webhook_secret ---
    ai_rows = conn.execute(
        text(
            "SELECT id, api_key, webhook_secret FROM ai_provider_configs "
            "WHERE api_key IS NOT NULL OR webhook_secret IS NOT NULL"
        )
    ).fetchall()
    for row_id, api_key, webhook_secret in ai_rows:
        updates: dict[str, str] = {}
        if api_key and not str(api_key).startswith(_FERNET_PREFIX):
            updates["api_key"] = fernet.encrypt(str(api_key).encode()).decode()
        if webhook_secret and not str(webhook_secret).startswith(_FERNET_PREFIX):
            updates["webhook_secret"] = fernet.encrypt(str(webhook_secret).encode()).decode()
        if updates:
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = str(row_id)
            conn.execute(
                text(
                    f"UPDATE ai_provider_configs SET {set_clause} WHERE id = :id"  # noqa: S608
                ),
                updates,
            )
            # Increment once per *row* — not once per column (api_key,
            # webhook_secret).  Using len(updates) would count encrypted
            # *columns* rather than encrypted *rows*, which is misleading.
            encrypted_count += 1

    logger.info("ris003: encrypted %d credential rows across all tables", encrypted_count)


def downgrade() -> None:
    # Decryption on downgrade is intentionally not implemented.
    # Reverting encryption requires the encryption key and would expose credentials.
    pass
