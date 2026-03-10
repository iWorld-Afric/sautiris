"""AccessionCounter model for concurrent-safe accession number generation.

Issue #53: This table replaces the COUNT()-based approach with an atomic
row-level counter that is safe under concurrent load.
"""

from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import Base


class AccessionCounter(Base):
    """Row-level counter used by core/accession.py to generate unique accession numbers.

    One row per (tenant_id, prefix, date).  The ``seq`` column is incremented
    atomically via INSERT … ON CONFLICT DO UPDATE or SELECT … FOR UPDATE.
    """

    __tablename__ = "accession_counters"
    __table_args__ = (UniqueConstraint("counter_key", name="uq_accession_counters_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # MEDIUM-10: unique=True removed — uniqueness enforced by named UniqueConstraint above
    counter_key: Mapped[str] = mapped_column(String(128), index=True)
    # Stored as String(36) for SQLite compatibility in tests; represents a UUID value.
    # core/accession.py converts uuid.UUID → str before raw SQL inserts.
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    date_prefix: Mapped[str] = mapped_column(String(8))
    seq: Mapped[int] = mapped_column(default=0)
