"""PeerReview and Discrepancy models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sautiris.models.base import TenantAwareBase


class ReviewType(StrEnum):
    RANDOM = "RANDOM"
    TARGETED = "TARGETED"
    DISCREPANCY = "DISCREPANCY"
    EDUCATIONAL = "EDUCATIONAL"


class AgreementScore(StrEnum):
    AGREE = "AGREE"
    MINOR_DISCREPANCY = "MINOR_DISCREPANCY"
    MAJOR_DISCREPANCY = "MAJOR_DISCREPANCY"
    MISS = "MISS"


class DiscrepancySeverity(StrEnum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DiscrepancyCategory(StrEnum):
    PERCEPTUAL = "PERCEPTUAL"
    INTERPRETIVE = "INTERPRETIVE"
    COMMUNICATION = "COMMUNICATION"
    PROCEDURAL = "PROCEDURAL"


class PeerReview(TenantAwareBase):
    __tablename__ = "peer_reviews"

    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_reports.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("radiology_orders.id"), index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column()
    reviewer_name: Mapped[str | None] = mapped_column(String(255), default=None)
    original_reporter_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    review_type: Mapped[str] = mapped_column(String(32), default=ReviewType.RANDOM)
    agreement_score: Mapped[str | None] = mapped_column(String(32), default=None)
    comments: Mapped[str | None] = mapped_column(Text, default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    discrepancies: Mapped[list[Discrepancy]] = relationship(
        back_populates="peer_review", lazy="selectin"
    )


class Discrepancy(TenantAwareBase):
    __tablename__ = "discrepancies"

    peer_review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("peer_reviews.id"), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    clinical_impact: Mapped[str | None] = mapped_column(Text, default=None)
    resolution: Mapped[str | None] = mapped_column(Text, default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    peer_review: Mapped[PeerReview] = relationship(back_populates="discrepancies")
