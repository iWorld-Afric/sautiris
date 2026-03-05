"""Peer review / QA API endpoints."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.services.peer_review_service import PeerReviewService

router = APIRouter(prefix="/peer-review", tags=["peer-review"])


# --- Pydantic schemas ---


class PeerReviewCreateRequest(BaseModel):
    report_id: uuid.UUID
    order_id: uuid.UUID
    reviewer_id: uuid.UUID
    reviewer_name: str | None = None
    original_reporter_id: uuid.UUID | None = None
    review_type: str = "RANDOM"


class DiscrepancyCreateRequest(BaseModel):
    severity: str
    category: str
    description: str | None = None
    clinical_impact: str | None = None


class DiscrepancyResponse(BaseModel):
    id: uuid.UUID
    peer_review_id: uuid.UUID
    severity: str
    category: str
    description: str | None
    clinical_impact: str | None
    resolution: str | None
    resolved_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class PeerReviewResponse(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    order_id: uuid.UUID
    reviewer_id: uuid.UUID
    reviewer_name: str | None
    original_reporter_id: uuid.UUID | None
    review_type: str
    agreement_score: str | None
    comments: str | None
    reviewed_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class PeerReviewDetailResponse(PeerReviewResponse):
    discrepancies: list[DiscrepancyResponse] = []


class PeerReviewStatsResponse(BaseModel):
    total_reviews: int
    agreement_counts: dict[str, int]
    agreement_rate: float
    discrepancy_by_category: dict[str, int]
    discrepancy_by_severity: dict[str, int]


class ScorecardResponse(BaseModel):
    radiologist_id: str
    total_reviews: int
    agreement_counts: dict[str, int]
    agreement_rate: float
    discrepancy_breakdown: dict[str, int]
    trending: str


# --- Endpoints ---


@router.post("", response_model=PeerReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review(
    body: PeerReviewCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:create")),
) -> Any:
    """Create a new peer review assignment."""
    svc = PeerReviewService(db)
    return await svc.create_review(
        report_id=body.report_id,
        order_id=body.order_id,
        reviewer_id=body.reviewer_id,
        reviewer_name=body.reviewer_name,
        original_reporter_id=body.original_reporter_id,
        review_type=body.review_type,
    )


@router.get("", response_model=list[PeerReviewResponse])
async def list_reviews(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:read")),
    review_type: str | None = Query(default=None),
    agreement_score: str | None = Query(default=None),
    reviewer_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    """List peer reviews with filtering."""
    svc = PeerReviewService(db)
    return await svc.list_reviews(
        review_type=review_type,
        agreement_score=agreement_score,
        reviewer_id=reviewer_id,
        offset=offset,
        limit=limit,
    )


@router.get("/stats", response_model=PeerReviewStatsResponse)
async def review_stats(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:read")),
) -> Any:
    """Get peer review QA statistics."""
    svc = PeerReviewService(db)
    return await svc.get_stats()


@router.get("/scorecard/{radiologist_id}", response_model=ScorecardResponse)
async def radiologist_scorecard(
    radiologist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:read")),
) -> Any:
    """Get performance scorecard for a radiologist."""
    svc = PeerReviewService(db)
    return await svc.get_scorecard(radiologist_id)


@router.get("/{review_id}", response_model=PeerReviewDetailResponse)
async def get_review(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:read")),
) -> Any:
    """Get a single peer review with discrepancies."""
    svc = PeerReviewService(db)
    review = await svc.get_review(review_id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Peer review {review_id} not found",
        )
    return review


@router.post(
    "/{review_id}/discrepancy",
    response_model=DiscrepancyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def report_discrepancy(
    review_id: uuid.UUID,
    body: DiscrepancyCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(require_permission("peer_review:create")),
) -> Any:
    """Report a discrepancy for a peer review."""
    svc = PeerReviewService(db)
    try:
        return await svc.report_discrepancy(
            review_id,
            severity=body.severity,
            category=body.category,
            description=body.description,
            clinical_impact=body.clinical_impact,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
