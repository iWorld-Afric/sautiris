"""PACSConnection model."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from sautiris.models.base import TenantAwareBase


class PACSType(StrEnum):
    ORTHANC = "ORTHANC"
    DCM4CHEE = "DCM4CHEE"
    CUSTOM = "CUSTOM"


class PACSConnection(TenantAwareBase):
    __tablename__ = "pacs_connections"

    name: Mapped[str] = mapped_column(String(255))
    pacs_type: Mapped[str] = mapped_column(String(16), default=PACSType.ORTHANC)
    base_url: Mapped[str] = mapped_column(String(512))
    dicomweb_root: Mapped[str | None] = mapped_column(String(255), default=None)
    ae_title: Mapped[str | None] = mapped_column(String(64), default=None)
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    password: Mapped[str | None] = mapped_column(String(255), default=None)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
