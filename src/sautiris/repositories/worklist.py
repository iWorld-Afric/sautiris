"""Worklist repository."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select

from sautiris.models.worklist import WorklistItem, WorklistStatus
from sautiris.repositories.base import TenantAwareRepository


class WorklistRepository(TenantAwareRepository[WorklistItem]):
    model = WorklistItem

    async def get_by_accession(self, accession_number: str) -> WorklistItem | None:
        stmt = select(WorklistItem).where(
            WorklistItem.tenant_id == self._tenant_id,
            WorklistItem.accession_number == accession_number,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_with_filters(
        self,
        *,
        modality: str | None = None,
        status: WorklistStatus | None = None,
        scheduled_station_ae_title: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        patient_name_pattern: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[Sequence[WorklistItem], int]:
        """List worklist items with optional filters.

        Args:
            modality: Filter by modality code (exact match).
            status: Filter by worklist status.
            scheduled_station_ae_title: Filter by AE title (exact match).
            date_from: Filter items scheduled on or after this date.
            date_to: Filter items scheduled on or before this date.
            patient_name_pattern: SQL LIKE pattern for patient name matching.
                Already-escaped pattern produced by
                :func:`~sautiris.integrations.dicom.mwl_scp.extract_query_filters`
                (DICOM wildcards converted, SQL metacharacters pre-escaped).
                Issue #4: wires the DICOM patient name wildcard filter through to
                the database query.
            offset: Number of results to skip (pagination).
            limit: Maximum number of results to return.

        Returns:
            A tuple of (items sequence, total count).
        """
        base = select(WorklistItem).where(WorklistItem.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(WorklistItem)
            .where(WorklistItem.tenant_id == self._tenant_id)
        )

        if modality:
            base = base.where(WorklistItem.modality == modality)
            count_base = count_base.where(WorklistItem.modality == modality)
        if status:
            base = base.where(WorklistItem.status == status)
            count_base = count_base.where(WorklistItem.status == status)
        if scheduled_station_ae_title:
            base = base.where(WorklistItem.scheduled_station_ae_title == scheduled_station_ae_title)
            count_base = count_base.where(
                WorklistItem.scheduled_station_ae_title == scheduled_station_ae_title
            )
        if date_from:
            base = base.where(WorklistItem.scheduled_start >= date_from)
            count_base = count_base.where(WorklistItem.scheduled_start >= date_from)
        if date_to:
            base = base.where(WorklistItem.scheduled_start <= date_to)
            count_base = count_base.where(WorklistItem.scheduled_start <= date_to)
        if patient_name_pattern:
            # Pattern is already escaped + converted from DICOM wildcards in
            # extract_query_filters(); apply directly as a case-insensitive LIKE.
            # Issue #4: wire patient_name_pattern from DICOM MWL C-FIND queries.
            base = base.where(WorklistItem.patient_name.ilike(patient_name_pattern))
            count_base = count_base.where(WorklistItem.patient_name.ilike(patient_name_pattern))

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(WorklistItem.scheduled_start).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_stats(self) -> dict[str, int]:
        stmt = (
            select(WorklistItem.status, func.count())
            .where(WorklistItem.tenant_id == self._tenant_id)
            .group_by(WorklistItem.status)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
