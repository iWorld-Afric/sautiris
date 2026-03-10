"""Concurrent-safe accession number generation.

SQLite note: asyncio.gather() with a shared session interleaves coroutines on the
same event loop thread.  For SQLite (test-only), we use per-key asyncio.Lock objects
to serialize the read-modify-write sequence.  PostgreSQL uses its native atomicity
via INSERT … ON CONFLICT DO UPDATE … RETURNING so no lock is needed there.

Issue #53: Replace COUNT()-based generation with a locked counter table that
guarantees unique accession numbers even under concurrent load.

Format: {tenant_prefix}-{YYYYMMDD}-{SEQ:05d}
  e.g.: RIS-20260306-00001

PostgreSQL: uses SELECT ... FOR UPDATE on the accession_counters table.
SQLite (tests): relies on SQLite's write serialization + UPDATE ... RETURNING
               to achieve the same effect within a transaction.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator
from datetime import date

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Per-key asyncio locks for SQLite serialization (test-only path).
# A regular dict is safe here because SQLite is only used in tests (single process).
_sqlite_locks: dict[str, asyncio.Lock] = {}
_sqlite_registry_lock: asyncio.Lock | None = None


def _get_registry_lock() -> asyncio.Lock:
    """Return the registry lock, creating it lazily on the current event loop.

    This avoids binding the lock at import time to a loop that may not exist yet
    (or to a loop that is replaced in test suites).
    """
    global _sqlite_registry_lock  # noqa: PLW0603
    if _sqlite_registry_lock is None:
        _sqlite_registry_lock = asyncio.Lock()
    return _sqlite_registry_lock


def reset_sqlite_locks() -> None:
    """Clear module-level locks. Called between test sessions to avoid cross-loop binding."""
    global _sqlite_registry_lock  # noqa: PLW0603
    _sqlite_locks.clear()
    _sqlite_registry_lock = None


@contextlib.asynccontextmanager
async def _sqlite_key_lock(key: str) -> AsyncGenerator[None, None]:
    """Acquire a per-key asyncio.Lock to serialize SQLite accession increments."""
    async with _get_registry_lock():
        if key not in _sqlite_locks:
            _sqlite_locks[key] = asyncio.Lock()
        lock = _sqlite_locks[key]
    async with lock:
        yield


async def generate_accession_number(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_prefix: str,
) -> str:
    """Generate the next accession number for a tenant, safe under concurrent load.

    Uses an advisory row-lock (PostgreSQL INSERT ON CONFLICT DO UPDATE RETURNING /
    SQLite serialized via asyncio.Lock) on the ``accession_counters`` table to
    prevent duplicate sequence numbers.

    Args:
        session: Active SQLAlchemy async session (must be inside a transaction).
        tenant_id: UUID of the current tenant.
        tenant_prefix: Short prefix used in the accession string (e.g. modality).

    Returns:
        Accession number string in the form ``{prefix}-{YYYYMMDD}-{seq:05d}``.
    """
    today = date.today().strftime("%Y%m%d")
    counter_key = f"{tenant_id}:{tenant_prefix}:{today}"

    bind = session.get_bind()
    dialect_name: str = getattr(getattr(bind, "dialect", None), "name", "sqlite")
    if dialect_name not in ("postgresql", "sqlite"):
        raise RuntimeError(
            f"Unsupported database dialect '{dialect_name}' for accession number generation. "
            "Only 'postgresql' and 'sqlite' (tests) are supported."
        )

    if dialect_name == "postgresql":
        # PostgreSQL: single atomic upsert with RETURNING — concurrency-safe
        result = await session.execute(
            text(
                """
                INSERT INTO accession_counters (counter_key, tenant_id, date_prefix, seq)
                VALUES (:key, :tenant_id, :date, 1)
                ON CONFLICT (counter_key) DO UPDATE
                    SET seq = accession_counters.seq + 1
                RETURNING seq
                """
            ),
            {"key": counter_key, "tenant_id": str(tenant_id), "date": today},
        )
        seq: int = result.scalar_one()
    else:
        # SQLite: serialize concurrent calls with a per-key asyncio lock
        async with _sqlite_key_lock(counter_key):
            await session.execute(
                text(
                    """
                    INSERT INTO accession_counters (counter_key, tenant_id, date_prefix, seq)
                    VALUES (:key, :tenant_id, :date, 0)
                    ON CONFLICT (counter_key) DO NOTHING
                    """
                ),
                {"key": counter_key, "tenant_id": str(tenant_id), "date": today},
            )
            await session.execute(
                text("UPDATE accession_counters SET seq = seq + 1 WHERE counter_key = :key"),
                {"key": counter_key},
            )
            result = await session.execute(
                text("SELECT seq FROM accession_counters WHERE counter_key = :key"),
                {"key": counter_key},
            )
            seq = result.scalar_one()

    accession = f"{tenant_prefix}-{today}-{seq:05d}"
    logger.debug("accession_generated", accession=accession, tenant_id=str(tenant_id))
    return accession


async def peek_next_accession_number(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    tenant_prefix: str,
) -> str:
    """Return what the next accession number *would* be without incrementing the counter.

    This is a read-only estimate for display purposes (e.g. pre-filling a UI
    field).  Because it does not hold a lock, a concurrent call to
    ``generate_accession_number`` may claim the same sequence number before the
    caller acts on this value — consumers MUST NOT use this to reserve a number.

    Args:
        session: Active SQLAlchemy async session.
        tenant_id: UUID of the current tenant.
        tenant_prefix: Short prefix used in the accession string (e.g. modality).

    Returns:
        Accession number string in the form ``{prefix}-{YYYYMMDD}-{seq:05d}``
        reflecting current counter + 1.
    """
    today = date.today().strftime("%Y%m%d")
    counter_key = f"{tenant_id}:{tenant_prefix}:{today}"

    result = await session.execute(
        text("SELECT seq FROM accession_counters WHERE counter_key = :key"),
        {"key": counter_key},
    )
    current_seq = result.scalar_one_or_none()
    next_seq = (current_seq or 0) + 1

    accession = f"{tenant_prefix}-{today}-{next_seq:05d}"
    logger.debug("accession_peeked", accession=accession, tenant_id=str(tenant_id))
    return accession
