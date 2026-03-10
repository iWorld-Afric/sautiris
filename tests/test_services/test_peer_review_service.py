"""Tests for PeerReviewService."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.models.peer_review import (
    AgreementScore,
    DiscrepancyCategory,
    DiscrepancySeverity,
    ReviewType,
)
from sautiris.services.peer_review_service import PeerReviewService
from tests.conftest import TEST_USER_ID, make_order, make_report


@pytest.fixture
async def order_and_report(db_session: AsyncSession) -> tuple[object, object]:
    """Create a test order and finalized report."""
    order = make_order(db_session, status="REPORTED")
    db_session.add(order)
    await db_session.flush()
    await db_session.refresh(order)

    report = make_report(
        order_id=order.id,
        report_status="FINAL",
        accession_number=order.accession_number,
    )
    db_session.add(report)
    await db_session.flush()
    await db_session.refresh(report)
    return order, report


@pytest.fixture
def review_service(db_session: AsyncSession) -> PeerReviewService:
    return PeerReviewService(db_session)


class TestCreateReview:
    async def test_create_review(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        reviewer_id = uuid.uuid4()
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=reviewer_id,
            reviewer_name="Dr. Ochieng",
            original_reporter_id=TEST_USER_ID,
            review_type=ReviewType.RANDOM,
        )
        assert review.id is not None
        assert review.reviewer_id == reviewer_id
        assert review.review_type == ReviewType.RANDOM
        assert review.agreement_score is None
        assert review.reviewed_at is None


class TestSubmitReview:
    async def test_submit_agree(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
        )
        submitted = await review_service.submit_review(
            review.id,
            agreement_score=AgreementScore.AGREE,
            comments="Findings consistent with original report",
        )
        assert submitted.agreement_score == AgreementScore.AGREE
        assert submitted.comments is not None
        assert submitted.reviewed_at is not None


class TestReportDiscrepancy:
    async def test_report_discrepancy(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
            original_reporter_id=TEST_USER_ID,
        )
        discrepancy = await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MAJOR,
            category=DiscrepancyCategory.PERCEPTUAL,
            description="Missed nodule in right lower lobe",
            clinical_impact="Delayed treatment",
        )
        assert discrepancy.id is not None
        assert discrepancy.severity == DiscrepancySeverity.MAJOR
        assert discrepancy.category == DiscrepancyCategory.PERCEPTUAL

    async def test_discrepancy_auto_updates_agreement(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
        )
        await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MAJOR,
            category=DiscrepancyCategory.INTERPRETIVE,
        )
        updated = await review_service.get_review(review.id)
        assert updated is not None
        assert updated.agreement_score == AgreementScore.MAJOR_DISCREPANCY

    async def test_minor_discrepancy_sets_minor(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
        )
        await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MINOR,
            category=DiscrepancyCategory.COMMUNICATION,
        )
        updated = await review_service.get_review(review.id)
        assert updated is not None
        assert updated.agreement_score == AgreementScore.MINOR_DISCREPANCY

    async def test_discrepancy_nonexistent_review(self, review_service: PeerReviewService) -> None:
        with pytest.raises(ValueError, match="not found"):
            await review_service.report_discrepancy(
                uuid.uuid4(),
                severity=DiscrepancySeverity.MINOR,
                category=DiscrepancyCategory.PROCEDURAL,
            )


class TestListReviews:
    async def test_list_all(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        r1 = uuid.uuid4()
        r2 = uuid.uuid4()
        await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=r1,
            review_type=ReviewType.RANDOM,
        )
        await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=r2,
            review_type=ReviewType.TARGETED,
        )
        reviews = await review_service.list_reviews()
        assert len(reviews) == 2

    async def test_list_by_type(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
            review_type=ReviewType.RANDOM,
        )
        await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
            review_type=ReviewType.TARGETED,
        )
        random_reviews = await review_service.list_reviews(review_type=ReviewType.RANDOM)
        assert len(random_reviews) == 1


class TestStats:
    async def test_stats_empty(self, review_service: PeerReviewService) -> None:
        stats = await review_service.get_stats()
        assert stats["total_reviews"] == 0
        assert stats["agreement_rate"] == 0.0

    async def test_stats_with_data(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=uuid.uuid4(),
        )
        await review_service.submit_review(review.id, agreement_score=AgreementScore.AGREE)
        stats = await review_service.get_stats()
        assert stats["total_reviews"] == 1
        assert stats["agreement_rate"] == 100.0


class TestScorecard:
    async def test_scorecard(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        order, report = order_and_report
        reviewer_id = uuid.uuid4()
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[union-attr]
            order_id=order.id,  # type: ignore[union-attr]
            reviewer_id=reviewer_id,
            original_reporter_id=TEST_USER_ID,
        )
        await review_service.submit_review(review.id, agreement_score=AgreementScore.AGREE)
        scorecard = await review_service.get_scorecard(reviewer_id)
        assert scorecard["radiologist_id"] == str(reviewer_id)
        assert scorecard["total_reviews"] == 1
        assert scorecard["agreement_rate"] == 100.0
        assert scorecard["trending"] in ("improving", "stable", "declining")


# ---------------------------------------------------------------------------
# GAP-C4: submit_review — nonexistent review raises ValueError
# ---------------------------------------------------------------------------


class TestSubmitReviewGaps:
    async def test_submit_nonexistent_review_raises_value_error(
        self, review_service: PeerReviewService
    ) -> None:
        """GAP-C4: submit_review() raises ValueError for a non-existent review ID."""
        with pytest.raises(ValueError, match="not found"):
            await review_service.submit_review(
                uuid.uuid4(),
                agreement_score=AgreementScore.AGREE,
            )


# ---------------------------------------------------------------------------
# GAP-H1: report_discrepancy() — MODERATE severity auto-update logic
# ---------------------------------------------------------------------------


class TestDiscrepancyAutoUpdateLogic:
    async def test_moderate_after_major_does_not_downgrade(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        """GAP-H1a: MODERATE discrepancy must NOT downgrade an existing MAJOR_DISCREPANCY."""
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[attr-defined]
            order_id=order.id,  # type: ignore[attr-defined]
            reviewer_id=uuid.uuid4(),
        )
        await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MAJOR,
            category=DiscrepancyCategory.INTERPRETIVE,
        )
        # Now report MODERATE — must NOT downgrade to MINOR_DISCREPANCY
        await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MODERATE,
            category=DiscrepancyCategory.COMMUNICATION,
        )
        updated = await review_service.get_review(review.id)
        assert updated is not None
        assert updated.agreement_score == AgreementScore.MAJOR_DISCREPANCY

    async def test_minor_after_agree_does_not_change_score(
        self, review_service: PeerReviewService, order_and_report: tuple[object, object]
    ) -> None:
        """GAP-H1b: MINOR discrepancy after score is already set to AGREE leaves it unchanged."""
        order, report = order_and_report
        review = await review_service.create_review(
            report_id=report.id,  # type: ignore[attr-defined]
            order_id=order.id,  # type: ignore[attr-defined]
            reviewer_id=uuid.uuid4(),
        )
        # Set score to AGREE explicitly
        await review_service.submit_review(review.id, agreement_score=AgreementScore.AGREE)
        # MINOR discrepancy with non-None agreement_score → must not overwrite
        await review_service.report_discrepancy(
            review.id,
            severity=DiscrepancySeverity.MINOR,
            category=DiscrepancyCategory.PROCEDURAL,
        )
        updated = await review_service.get_review(review.id)
        assert updated is not None
        assert updated.agreement_score == AgreementScore.AGREE


# ---------------------------------------------------------------------------
# GAP-M8: _compute_trending() — improving / declining / stable
# ---------------------------------------------------------------------------


class TestComputeTrending:
    async def test_improving_trend(self, review_service: PeerReviewService) -> None:
        """GAP-M8a: recent > prior by >5 pp → 'improving'."""
        from unittest.mock import AsyncMock, patch

        reviewer_id = uuid.uuid4()
        with patch.object(
            review_service.review_repo,
            "agreement_rate_in_period",
            new=AsyncMock(side_effect=[0.9, 0.8]),  # recent=0.9, prior=0.8 → +0.1
        ):
            result = await review_service._compute_trending(reviewer_id)
        assert result == "improving"

    async def test_declining_trend(self, review_service: PeerReviewService) -> None:
        """GAP-M8b: recent < prior by >5 pp → 'declining'."""
        from unittest.mock import AsyncMock, patch

        reviewer_id = uuid.uuid4()
        with patch.object(
            review_service.review_repo,
            "agreement_rate_in_period",
            new=AsyncMock(side_effect=[0.7, 0.85]),  # recent=0.7, prior=0.85 → -0.15
        ):
            result = await review_service._compute_trending(reviewer_id)
        assert result == "declining"

    async def test_stable_trend(self, review_service: PeerReviewService) -> None:
        """GAP-M8c: |recent - prior| ≤ 5 pp → 'stable'."""
        from unittest.mock import AsyncMock, patch

        reviewer_id = uuid.uuid4()
        with patch.object(
            review_service.review_repo,
            "agreement_rate_in_period",
            new=AsyncMock(side_effect=[0.82, 0.8]),  # diff = +0.02
        ):
            result = await review_service._compute_trending(reviewer_id)
        assert result == "stable"

    async def test_none_recent_rate_returns_stable(
        self, review_service: PeerReviewService
    ) -> None:
        """GAP-M8d: None recent_rate → 'stable' (insufficient data)."""
        from unittest.mock import AsyncMock, patch

        reviewer_id = uuid.uuid4()
        with patch.object(
            review_service.review_repo,
            "agreement_rate_in_period",
            new=AsyncMock(side_effect=[None, 0.8]),
        ):
            result = await review_service._compute_trending(reviewer_id)
        assert result == "stable"
