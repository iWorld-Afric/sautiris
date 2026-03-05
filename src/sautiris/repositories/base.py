"""Tenant-aware generic repository base."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.core.tenancy import get_current_tenant_id
from sautiris.models.base import TenantAwareBase

T = TypeVar("T", bound=TenantAwareBase)


class TenantAwareRepository(Generic[T]):
    """Base repository that auto-filters by tenant_id."""

    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @property
    def _tenant_id(self) -> uuid.UUID:
        return get_current_tenant_id()

    async def get_by_id(self, entity_id: uuid.UUID) -> T | None:
        stmt = select(self.model).where(
            self.model.id == entity_id,
            self.model.tenant_id == self._tenant_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, *, offset: int = 0, limit: int = 100) -> Sequence[T]:
        stmt = (
            select(self.model)
            .where(self.model.tenant_id == self._tenant_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, entity: T) -> T:
        entity.tenant_id = self._tenant_id
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: T) -> T:
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()
