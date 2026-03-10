"""Billing service for CPT/ICD code assignment."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.billing import BillingCode, OrderBilling
from sautiris.repositories.billing import BillingCodeRepository, OrderBillingRepository

logger = structlog.get_logger(__name__)


class BillingCodeNotFoundError(Exception):
    pass


class BillingCodeInactiveError(Exception):
    pass


class DuplicateBillingAssignmentError(Exception):
    pass


class BillingAssignmentNotFoundError(Exception):
    pass


class BillingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.code_repo = BillingCodeRepository(session)
        self.billing_repo = OrderBillingRepository(session)

    async def assign_code(
        self,
        *,
        order_id: uuid.UUID,
        billing_code_id: uuid.UUID,
        quantity: int = 1,
        assigned_by: uuid.UUID | None = None,
    ) -> OrderBilling:
        code = await self.code_repo.get_by_id(billing_code_id)
        if code is None:
            raise BillingCodeNotFoundError(f"Billing code {billing_code_id} not found")
        if not code.is_active:
            raise BillingCodeInactiveError(f"Billing code {code.code} is inactive")

        duplicate = await self.billing_repo.find_duplicate(order_id, billing_code_id)
        if duplicate is not None:
            raise DuplicateBillingAssignmentError(
                f"Code {code.code} already assigned to order {order_id}"
            )

        billing = OrderBilling(
            order_id=order_id,
            billing_code_id=billing_code_id,
            quantity=quantity,
            assigned_by=assigned_by,
            assigned_at=datetime.now(UTC),
        )
        created = await self.billing_repo.create(billing)
        logger.info(
            "billing_assigned",
            order_id=str(order_id),
            code=code.code,
        )
        return created

    async def get_order_billing(self, order_id: uuid.UUID) -> Sequence[OrderBilling]:
        return await self.billing_repo.get_by_order(order_id)

    async def search_codes(
        self,
        *,
        q: str | None = None,
        code_system: str | None = None,
        modality: str | None = None,
        body_part: str | None = None,
    ) -> list[BillingCode]:
        items = await self.code_repo.search_codes(
            q=q,
            code_system=code_system,
            modality=modality,
            body_part=body_part,
        )
        return list(items)

    async def get_revenue_summary(
        self,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        group_by: Literal["month", "modality", "code_system"] = "code_system",
    ) -> list[dict[str, object]]:
        return await self.billing_repo.get_revenue_summary(
            date_from=date_from, date_to=date_to, group_by=group_by
        )

    async def remove_assignment(self, billing_id: uuid.UUID) -> None:
        item = await self.billing_repo.get_by_id(billing_id)
        if item is None:
            raise BillingAssignmentNotFoundError(f"Billing assignment {billing_id} not found")
        await self.billing_repo.delete(item)
        logger.info("billing_removed", billing_id=str(billing_id))
