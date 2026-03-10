"""Billing code and order billing repositories."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.billing import BillingCode, OrderBilling
from sautiris.repositories.base import TenantAwareRepository


class BillingCodeRepository:
    """Reference table repository — not tenant-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search_codes(
        self,
        *,
        q: str | None = None,
        code_system: str | None = None,
        modality: str | None = None,
        body_part: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[BillingCode]:
        stmt = select(BillingCode).where(BillingCode.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(
                    BillingCode.code.ilike(pattern),
                    BillingCode.display.ilike(pattern),
                )
            )
        if code_system:
            stmt = stmt.where(BillingCode.code_system == code_system)
        if modality:
            stmt = stmt.where(BillingCode.modality == modality)
        if body_part:
            stmt = stmt.where(BillingCode.body_part == body_part)

        stmt = stmt.order_by(BillingCode.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, code_id: uuid.UUID) -> BillingCode | None:
        stmt = select(BillingCode).where(BillingCode.id == code_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class OrderBillingRepository(TenantAwareRepository[OrderBilling]):
    model = OrderBilling

    async def get_by_order(self, order_id: uuid.UUID) -> Sequence[OrderBilling]:
        stmt = select(OrderBilling).where(
            OrderBilling.tenant_id == self._tenant_id,
            OrderBilling.order_id == order_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def find_duplicate(
        self, order_id: uuid.UUID, billing_code_id: uuid.UUID
    ) -> OrderBilling | None:
        stmt = select(OrderBilling).where(
            OrderBilling.tenant_id == self._tenant_id,
            OrderBilling.order_id == order_id,
            OrderBilling.billing_code_id == billing_code_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_revenue_summary(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        group_by: Literal["month", "modality", "code_system"] = "code_system",
    ) -> list[dict[str, object]]:
        """Revenue grouped by code_system, modality, or month."""
        from typing import Any

        group_col: Any
        if group_by == "month":
            group_col = func.strftime("%Y-%m", OrderBilling.assigned_at)
            group_label = "month"
        elif group_by == "modality":
            group_col = BillingCode.modality
            group_label = "modality"
        else:
            group_col = BillingCode.code_system
            group_label = "code_system"

        stmt = (
            select(
                group_col.label(group_label),
                func.count().label("assignment_count"),
                func.sum(OrderBilling.quantity).label("total_quantity"),
            )
            .join(BillingCode, OrderBilling.billing_code_id == BillingCode.id)
            .where(OrderBilling.tenant_id == self._tenant_id)
        )
        if date_from:
            stmt = stmt.where(OrderBilling.assigned_at >= date_from)
        if date_to:
            stmt = stmt.where(OrderBilling.assigned_at <= date_to)

        stmt = stmt.group_by(group_col)
        result = await self.session.execute(stmt)
        return [
            {
                group_label: row[0],
                "assignment_count": row[1],
                "total_quantity": row[2],
            }
            for row in result.all()
        ]
