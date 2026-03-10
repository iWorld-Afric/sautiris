"""API key management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sautiris.api.deps import get_db, get_tenant_id, require_permission
from sautiris.core.auth.base import AuthUser
from sautiris.core.permissions import Permission
from sautiris.repositories.apikey_repo import ApiKeyRepository

router = APIRouter(prefix="/apikeys", tags=["api-keys"])


# --- Schemas ---


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human-readable name for this key")
    permissions: list[Permission] = Field(
        default=[], description="Permission strings granted to this key"
    )
    scopes: list[str] = Field(default=[], description="OAuth scopes granted to this key")
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    key_prefix: str
    user_id: uuid.UUID
    permissions: list[str]
    scopes: list[str]
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    """Includes raw_key — returned only once at creation time."""

    raw_key: str


# --- Endpoints ---


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiKeyCreateResponse,
)
async def create_api_key(
    body: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user: AuthUser = Depends(require_permission("admin:full")),
) -> object:
    """Create a new API key.  The ``raw_key`` is shown exactly once."""
    repo = ApiKeyRepository(db, tenant_id)
    raw_key, api_key = await repo.create(
        name=body.name,
        user_id=user.user_id,
        permissions=[str(p) for p in body.permissions],
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    return {
        **{c.key: getattr(api_key, c.key) for c in api_key.__table__.columns},
        "raw_key": raw_key,
    }


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user: AuthUser = Depends(require_permission("admin:full")),
) -> object:
    repo = ApiKeyRepository(db, tenant_id)
    return await repo.list_all()


@router.get("/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user: AuthUser = Depends(require_permission("admin:full")),
) -> object:
    repo = ApiKeyRepository(db, tenant_id)
    api_key = await repo.get_by_id(key_id)
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return api_key


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    user: AuthUser = Depends(require_permission("admin:full")),
) -> None:
    repo = ApiKeyRepository(db, tenant_id)
    found = await repo.revoke(key_id)
    if not found:
        raise HTTPException(status_code=404, detail="API key not found")
