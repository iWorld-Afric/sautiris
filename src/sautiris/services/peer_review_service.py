"""PeerReviewService — QA workflow, discrepancy tracking, scorecards."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.peer_review import (
    AgreementScore,
    Discrepancy,
    DiscrepancySeverity,
    PeerReview,
    ReviewType,
)
from sautiris.repositories.peer_review import DiscrepancyRepository, PeerReviewRepository

logger = structlog.get_logger(__name__)


class PeerReviewService:
    """Service for radiology peer review and QA workflow."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.review_repo = PeerReviewRepository(session)
        self.discrepancy_repo = DiscrepancyRepository(session)

    async def create_review(
        self,
        *,
        report_id: uuid.UUID,
        order_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        reviewer_name: str | None = None,
        original_reporter_id: uuid.UUID | None = None,
        review_type: str = ReviewType.RANDOM,
    ) -> PeerReview:
        """Create a new peer review assignment."""
        review = PeerReview(
            tenant_id=get_current_tenant_id(),
            report_id=report_id,
            order_id=order_id,
            reviewer_id=reviewer_id,
            reviewer_name=reviewer_name,
            original_reporter_id=original_reporter_id,
            review_type=review_type,
        )
        created = await self.review_repo.create(review)
        await self.session.commit()

        logger.info(
            "peer_review_created",
            review_id=str(created.id),
            report_id=str(report_id),
            reviewer_id=str(reviewer_id),
            review_type=review_type,
        )
        return created

    async def list_reviews(
        self,
        *,
        review_type: str | None = None,
        agreement_score: str | None = None,
        reviewer_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[PeerReview]:
        """List peer reviews with filtering."""
        results = await self.review_repo.list_filtered(
            review_type=review_type,
            agreement_score=agreement_score,
            reviewer_id=reviewer_id,
            offset=offset,
            limit=limit,
        )
        return list(results)

    async def get_review(self, review_id: uuid.UUID) -> PeerReview | None:
        """Get a single peer review with discrepancies."""
        return await self.review_repo.get_by_id(review_id)

    async def submit_review(
        self,
        review_id: uuid.UUID,
        *,
        agreement_score: str,
        comments: str | None = None,
    ) -> PeerReview:
        """Submit agreement score and comments for an existing review."""
        review = await self.review_repo.get_by_id(review_id)
        if review is None:
            raise ValueError(f"Peer review {review_id} not found")

        review.agreement_score = agreement_score
        review.comments = comments
        review.reviewed_at = datetime.now(UTC)
        updated = await self.review_repo.update(review)
        await self.session.commit()

        logger.info(
            "peer_review_submitted",
            review_id=str(review_id),
            agreement_score=agreement_score,
        )
        return updated

    async def report_discrepancy(
        self,
        review_id: uuid.UUID,
        *,
        severity: str,
        category: str,
        description: str | None = None,
        clinical_impact: str | None = None,
    ) -> Discrepancy:
        """Report a discrepancy for a peer review."""
        review = await self.review_repo.get_by_id(review_id)
        if review is None:
            raise ValueError(f"Peer review {review_id} not found")

        discrepancy = Discrepancy(
            tenant_id=get_current_tenant_id(),
            peer_review_id=review_id,
            severity=severity,
            category=category,
            description=description,
            clinical_impact=clinical_impact,
        )
        created = await self.discrepancy_repo.create(discrepancy)

        # Auto-update agreement score based on discrepancy severity
        if severity in (DiscrepancySeverity.MAJOR, DiscrepancySeverity.CRITICAL):
            review.agreement_score = AgreementScore.MAJOR_DISCREPANCY
        elif severity == DiscrepancySeverity.MODERATE:
            if review.agreement_score != AgreementScore.MAJOR_DISCREPANCY:
                review.agreement_score = AgreementScore.MINOR_DISCREPANCY
        elif severity == DiscrepancySeverity.MINOR and review.agreement_score is None:
            review.agreement_score = AgreementScore.MINOR_DISCREPANCY

        await self.session.commit()

        logger.info(
            "discrepancy_reported",
            discrepancy_id=str(created.id),
            review_id=str(review_id),
            severity=severity,
            category=category,
        )
        return created

    async def get_stats(self) -> dict[str, Any]:
        """Get QA statistics: agreement rates, discrepancy patterns."""
        agreement_counts = await self.review_repo.count_by_agreement()
        total_reviewed = await self.review_repo.total_with_agreement()
        discrepancy_by_category = await self.discrepancy_repo.count_by_category()
        discrepancy_by_severity = await self.discrepancy_repo.count_by_severity()

        agree_count = agreement_counts.get(AgreementScore.AGREE, 0)
        agreement_rate = (agree_count / total_reviewed * 100.0) if total_reviewed > 0 else 0.0

        return {
            "total_reviews": total_reviewed,
            "agreement_counts": agreement_counts,
            "agreement_rate": round(agreement_rate, 2),
            "discrepancy_by_category": discrepancy_by_category,
            "discrepancy_by_severity": discrepancy_by_severity,
        }

    async def get_scorecard(
        self,
        radiologist_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Get performance scorecard for a radiologist, including trend."""
        reviews = await self.review_repo.get_reviews_for_radiologist(radiologist_id)
        total_reviews = len(reviews)

        agreement_counts: dict[str, int] = {}
        for review in reviews:
            if review.agreement_score:
                agreement_counts[review.agreement_score] = (
                    agreement_counts.get(review.agreement_score, 0) + 1
                )

        agree_count = agreement_counts.get(AgreementScore.AGREE, 0)
        reviewed_count = sum(agreement_counts.values())
        agreement_rate = (agree_count / reviewed_count * 100.0) if reviewed_count > 0 else 0.0

        discrepancy_breakdown = await self.discrepancy_repo.count_for_radiologist(radiologist_id)

        # Compute trending: compare last 3 months vs prior 3 months
        trending = await self._compute_trending(radiologist_id)

        return {
            "radiologist_id": str(radiologist_id),
            "total_reviews": total_reviews,
            "agreement_counts": agreement_counts,
            "agreement_rate": round(agreement_rate, 2),
            "discrepancy_breakdown": discrepancy_breakdown,
            "trending": trending,
        }

    async def _compute_trending(
        self,
        radiologist_id: uuid.UUID,
    ) -> Literal["improving", "stable", "declining"]:
        """Compare agreement rate last 3 months vs prior 3 months."""
        now = datetime.now(UTC)

        # Recent period: last 3 months
        recent_end = now.isoformat()
        recent_start = (now - timedelta(days=90)).isoformat()

        # Prior period: 3-6 months ago
        prior_end = recent_start
        prior_start = (now - timedelta(days=180)).isoformat()

        recent_rate = await self.review_repo.agreement_rate_in_period(
            radiologist_id, start=recent_start, end=recent_end
        )
        prior_rate = await self.review_repo.agreement_rate_in_period(
            radiologist_id, start=prior_start, end=prior_end
        )

        if recent_rate is None or prior_rate is None:
            return "stable"

        diff = recent_rate - prior_rate
        if diff > 0.05:
            return "improving"
        elif diff < -0.05:
            return "declining"
        return "stable"
