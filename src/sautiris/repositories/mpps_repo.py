"""MPPS repository (Issue #14)."""

from __future__ import annotations

from sqlalchemy import select

from sautiris.models.mpps import MPPSInstance
from sautiris.repositories.base import TenantAwareRepository


class MPPSRepository(TenantAwareRepository[MPPSInstance]):
    """Tenant-aware repository for MPPSInstance records."""

    model = MPPSInstance

    async def get_by_sop_uid(self, sop_instance_uid: str) -> MPPSInstance | None:
        """Retrieve an MPPS instance by SOP Instance UID within the current tenant."""
        stmt = select(MPPSInstance).where(
            MPPSInstance.tenant_id == self._tenant_id,
            MPPSInstance.sop_instance_uid == sop_instance_uid,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
