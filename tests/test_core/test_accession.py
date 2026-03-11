"""Tests for concurrent-safe accession number generation.

Issue #53: Replace COUNT()-based accession generation with a counter table
that is safe under concurrent load (no duplicate accession numbers).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_TENANT_ID


@pytest.mark.asyncio
async def test_accession_format(db_session: AsyncSession) -> None:
    """Generated accession must match {TENANT_PREFIX}-{YYYYMMDD}-{SEQ:05d}."""
    from sautiris.core.accession import generate_accession_number

    acc = await generate_accession_number(db_session, TEST_TENANT_ID, "RIS")
    today = date.today().strftime("%Y%m%d")
    assert re.match(rf"^RIS-{today}-\d{{5}}$", acc), f"Bad format: {acc}"


@pytest.mark.asyncio
async def test_accession_sequential(db_session: AsyncSession) -> None:
    """Successive calls yield increasing sequence numbers."""
    from sautiris.core.accession import generate_accession_number

    acc1 = await generate_accession_number(db_session, TEST_TENANT_ID, "RIS")
    acc2 = await generate_accession_number(db_session, TEST_TENANT_ID, "RIS")
    seq1 = int(acc1.rsplit("-", 1)[-1])
    seq2 = int(acc2.rsplit("-", 1)[-1])
    assert seq2 == seq1 + 1


@pytest.mark.asyncio
async def test_different_tenants_independent_sequences(db_session: AsyncSession) -> None:
    """Two different tenants each start at sequence 1 independently."""
    from sautiris.core.accession import generate_accession_number

    tenant_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
    acc_a = await generate_accession_number(db_session, TEST_TENANT_ID, "A")
    acc_b = await generate_accession_number(db_session, tenant_b, "B")

    seq_a = int(acc_a.rsplit("-", 1)[-1])
    seq_b = int(acc_b.rsplit("-", 1)[-1])
    assert seq_a == 1
    assert seq_b == 1


@pytest.mark.asyncio
async def test_concurrent_accession_unique(db_session: AsyncSession) -> None:
    """10 concurrent calls within same session must all produce unique accession numbers.

    This is the core safety guarantee: no two concurrent requests can get the same number.
    """
    from sautiris.core.accession import generate_accession_number

    results = await asyncio.gather(
        *[generate_accession_number(db_session, TEST_TENANT_ID, "CONCURRENT") for _ in range(10)]
    )

    assert len(set(results)) == 10, f"Duplicates found: {sorted(results)}"


# ---------------------------------------------------------------------------
# GAP-10: peek_next_accession_number — read-only check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accession_number_resets_on_date_rollover(db_session: AsyncSession) -> None:
    """#62: Accession counter resets to 00001 for a new date.

    The counter key includes the date component, so when midnight rolls over
    (a different date), the counter for the new date starts at 1, independent
    of however many numbers were generated on the previous date.
    """
    from datetime import date
    from unittest.mock import patch

    from sautiris.core.accession import generate_accession_number

    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    prefix = "ROLLOVER"

    day_1 = date(2026, 3, 10)
    day_2 = date(2026, 3, 11)

    # Generate 3 accessions on day 1
    with patch("sautiris.core.accession.date") as mock_date:
        mock_date.today.return_value = day_1
        acc_d1_1 = await generate_accession_number(db_session, tenant_id, prefix)
        acc_d1_2 = await generate_accession_number(db_session, tenant_id, prefix)
        acc_d1_3 = await generate_accession_number(db_session, tenant_id, prefix)

    seq_d1 = [int(a.rsplit("-", 1)[-1]) for a in [acc_d1_1, acc_d1_2, acc_d1_3]]
    assert seq_d1 == [1, 2, 3], f"Day 1 sequences should be 1,2,3 — got {seq_d1}"

    # Roll over to day 2 — counter must reset to 1
    with patch("sautiris.core.accession.date") as mock_date:
        mock_date.today.return_value = day_2
        acc_d2_1 = await generate_accession_number(db_session, tenant_id, prefix)
        acc_d2_2 = await generate_accession_number(db_session, tenant_id, prefix)

    seq_d2 = [int(a.rsplit("-", 1)[-1]) for a in [acc_d2_1, acc_d2_2]]
    assert seq_d2 == [1, 2], f"After date rollover, counter must reset to 1 — got {seq_d2}"

    # Verify the date component in the accession number matches the mocked date
    assert acc_d2_1.startswith(f"{prefix}-20260311-"), (
        f"Accession on day 2 should have date 20260311: {acc_d2_1}"
    )


@pytest.mark.asyncio
async def test_peek_next_accession_number_readonly(db_session: AsyncSession) -> None:
    """peek_next_accession_number must NOT increment the counter.

    Calling peek twice must return the same predicted value, and calling
    generate after peek must produce the same number that peek predicted.
    """
    from sautiris.core.accession import generate_accession_number, peek_next_accession_number

    # Peek once — get the predicted next number
    peeked_first = await peek_next_accession_number(db_session, TEST_TENANT_ID, "PEEK")
    # Peek again — must return the same value (counter not incremented)
    peeked_second = await peek_next_accession_number(db_session, TEST_TENANT_ID, "PEEK")
    assert peeked_first == peeked_second, "peek must be idempotent — counter must not change"

    # Now generate — must produce the number that peek predicted
    generated = await generate_accession_number(db_session, TEST_TENANT_ID, "PEEK")
    assert generated == peeked_first, (
        f"generate() produced {generated!r} but peek() predicted {peeked_first!r}"
    )

    # Another peek after generate must show the NEXT value (counter advanced by 1)
    peeked_after = await peek_next_accession_number(db_session, TEST_TENANT_ID, "PEEK")
    seq_before = int(generated.rsplit("-", 1)[-1])
    seq_after = int(peeked_after.rsplit("-", 1)[-1])
    assert seq_after == seq_before + 1
