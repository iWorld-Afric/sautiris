"""Repository for DoseRecord entities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from sautiris.models.dose import DoseRecord, DoseSource
from sautiris.repositories.base import TenantAwareRepository


class DoseRepository(TenantAwareRepository[DoseRecord]):
    model = DoseRecord

    async def list_with_filters(
        self,
        *,
        order_id: uuid.UUID | None = None,
        source: DoseSource | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[DoseRecord], int]:
        base = select(self.model).where(self.model.tenant_id == self._tenant_id)
        count_base = (
            select(func.count())
            .select_from(DoseRecord)
            .where(self.model.tenant_id == self._tenant_id)
        )

        if order_id:
            base = base.where(self.model.order_id == order_id)
            count_base = count_base.where(self.model.order_id == order_id)
        if source:
            base = base.where(self.model.source == source)
            count_base = count_base.where(self.model.source == source)

        total_result = await self.session.execute(count_base)
        total = total_result.scalar_one()

        stmt = base.order_by(self.model.recorded_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def get_for_order(self, order_id: uuid.UUID) -> Sequence[DoseRecord]:
        stmt = (
            select(self.model)
            .where(
                self.model.tenant_id == self._tenant_id,
                self.model.order_id == order_id,
            )
            .order_by(self.model.recorded_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_for_patient(
        self, patient_id: uuid.UUID, *, offset: int = 0, limit: int = 200
    ) -> Sequence[DoseRecord]:
        """Get dose history for a patient by joining through radiology_orders."""
        from sautiris.models.order import RadiologyOrder

        stmt = (
            select(self.model)
            .join(RadiologyOrder, RadiologyOrder.id == self.model.order_id)
            .where(
                self.model.tenant_id == self._tenant_id,
                RadiologyOrder.patient_id == patient_id,
            )
            .order_by(self.model.recorded_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def stats_by_modality(self) -> list[dict[str, object]]:
        """Compute dose statistics grouped by modality."""
        stmt = (
            select(
                self.model.modality,
                func.count(self.model.id).label("count"),
                func.avg(self.model.ctdi_vol).label("avg_ctdi_vol"),
                func.avg(self.model.dlp).label("avg_dlp"),
                func.avg(self.model.dap).label("avg_dap"),
                func.avg(self.model.effective_dose).label("avg_effective_dose"),
            )
            .where(self.model.tenant_id == self._tenant_id)
            .group_by(self.model.modality)
        )
        result = await self.session.execute(stmt)
        return [
            {
                "modality": row.modality,
                "count": row.count,
                "avg_ctdi_vol": float(row.avg_ctdi_vol) if row.avg_ctdi_vol else None,
                "avg_dlp": float(row.avg_dlp) if row.avg_dlp else None,
                "avg_dap": float(row.avg_dap) if row.avg_dap else None,
                "avg_effective_dose": (
                    float(row.avg_effective_dose) if row.avg_effective_dose else None
                ),
            }
            for row in result.all()
        ]

    async def drl_compliance_stats(self) -> dict[str, object]:
        """DRL compliance statistics."""
        total_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.exceeds_drl.isnot(None),
        )
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar() or 0

        exceed_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.exceeds_drl.is_(True),
        )
        exceed_result = await self.session.execute(exceed_stmt)
        exceeding = exceed_result.scalar() or 0

        exceed_by_mod_stmt = (
            select(
                self.model.modality,
                func.count(self.model.id).label("total"),
            )
            .where(
                self.model.tenant_id == self._tenant_id,
                self.model.exceeds_drl.is_(True),
            )
            .group_by(self.model.modality)
        )
        exceed_by_mod_result = await self.session.execute(exceed_by_mod_stmt)
        exceedances_by_modality = {row.modality: row.total for row in exceed_by_mod_result.all()}

        compliance_rate = ((total - exceeding) / total * 100.0) if total > 0 else 100.0

        return {
            "total_records": total,
            "exceeding_drl": exceeding,
            "compliance_rate": round(compliance_rate, 2),
            "exceedances_by_modality": exceedances_by_modality,
        }
