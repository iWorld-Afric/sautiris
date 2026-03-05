"""Repository for PeerReview and Discrepancy entities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from sautiris.models.peer_review import Discrepancy, PeerReview
from sautiris.repositories.base import TenantAwareRepository


class PeerReviewRepository(TenantAwareRepository[PeerReview]):
    model = PeerReview

    async def list_filtered(
        self,
        *,
        review_type: str | None = None,
        agreement_score: str | None = None,
        reviewer_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> Sequence[PeerReview]:
        stmt = select(self.model).where(self.model.tenant_id == self._tenant_id)

        if review_type:
            stmt = stmt.where(self.model.review_type == review_type)
        if agreement_score:
            stmt = stmt.where(self.model.agreement_score == agreement_score)
        if reviewer_id:
            stmt = stmt.where(self.model.reviewer_id == reviewer_id)

        stmt = stmt.order_by(self.model.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_agreement(self) -> dict[str, int]:
        """Count reviews by agreement score."""
        stmt = (
            select(self.model.agreement_score, func.count(self.model.id))
            .where(
                self.model.tenant_id == self._tenant_id,
                self.model.agreement_score.isnot(None),
            )
            .group_by(self.model.agreement_score)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def count_reviews_by_radiologist(self, radiologist_id: uuid.UUID) -> int:
        stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.reviewer_id == radiologist_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_reviews_for_radiologist(
        self,
        radiologist_id: uuid.UUID,
        *,
        as_reviewer: bool = True,
        offset: int = 0,
        limit: int = 200,
    ) -> Sequence[PeerReview]:
        stmt = select(self.model).where(self.model.tenant_id == self._tenant_id)
        if as_reviewer:
            stmt = stmt.where(self.model.reviewer_id == radiologist_id)
        else:
            stmt = stmt.where(self.model.original_reporter_id == radiologist_id)
        stmt = stmt.order_by(self.model.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def agreement_rate_in_period(
        self,
        radiologist_id: uuid.UUID,
        *,
        start: str,
        end: str,
    ) -> float | None:
        """Compute agreement rate for a radiologist in a date range.

        Returns None if no reviews exist in the period.
        """
        total_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.reviewer_id == radiologist_id,
            self.model.agreement_score.isnot(None),
            self.model.reviewed_at >= start,
            self.model.reviewed_at < end,
        )
        total_result = await self.session.execute(total_stmt)
        total = total_result.scalar() or 0
        if total == 0:
            return None

        agree_stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.reviewer_id == radiologist_id,
            self.model.agreement_score == "AGREE",
            self.model.reviewed_at >= start,
            self.model.reviewed_at < end,
        )
        agree_result = await self.session.execute(agree_stmt)
        agreed = agree_result.scalar() or 0
        return agreed / total

    async def total_with_agreement(self) -> int:
        stmt = select(func.count(self.model.id)).where(
            self.model.tenant_id == self._tenant_id,
            self.model.agreement_score.isnot(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0


class DiscrepancyRepository(TenantAwareRepository[Discrepancy]):
    model = Discrepancy

    async def list_for_review(self, peer_review_id: uuid.UUID) -> Sequence[Discrepancy]:
        stmt = (
            select(self.model)
            .where(
                self.model.tenant_id == self._tenant_id,
                self.model.peer_review_id == peer_review_id,
            )
            .order_by(self.model.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def count_by_category(self) -> dict[str, int]:
        stmt = (
            select(self.model.category, func.count(self.model.id))
            .where(self.model.tenant_id == self._tenant_id)
            .group_by(self.model.category)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def count_by_severity(self) -> dict[str, int]:
        stmt = (
            select(self.model.severity, func.count(self.model.id))
            .where(self.model.tenant_id == self._tenant_id)
            .group_by(self.model.severity)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def count_for_radiologist(self, radiologist_id: uuid.UUID) -> dict[str, int]:
        """Count discrepancies where the radiologist was the original reporter."""
        stmt = (
            select(self.model.category, func.count(self.model.id))
            .join(PeerReview, PeerReview.id == self.model.peer_review_id)
            .where(
                self.model.tenant_id == self._tenant_id,
                PeerReview.original_reporter_id == radiologist_id,
            )
            .group_by(self.model.category)
        )
        result = await self.session.execute(stmt)
        return {row[0]: row[1] for row in result.all()}
