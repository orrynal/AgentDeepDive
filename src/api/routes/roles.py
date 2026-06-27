from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.role import RoleCreate, RoleResponse, RoleUpdate
from src.core.role.service import RoleService
from src.database import get_db
from src.core.auth.security import get_current_user, RoleRequired
from src.core.auth.models import UserModel

router = APIRouter()


def _get_service(
    session: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> RoleService:
    return RoleService(session, tenant_id=user.tenant_id)


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    role: RoleCreate,
    svc: RoleService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Register a new Role."""
    existing = await svc.get_by_id(role.role_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Role '{role.role_id}' already exists")
    return await svc.create(role.model_dump())


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    active_only: bool = True,
    svc: RoleService = Depends(_get_service),
):
    """List all registered Roles."""
    return await svc.list_all(active_only=active_only)


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: str,
    svc: RoleService = Depends(_get_service),
):
    """Get a specific Role by ID."""
    role = await svc.get_by_id(role_id)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")
    return role


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    body: RoleUpdate,
    svc: RoleService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Update an existing Role."""
    result = await svc.update(role_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")
    return result


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    svc: RoleService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin"])),
):
    """Deactivate a Role (soft delete)."""
    success = await svc.deactivate(role_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Role '{role_id}' not found")
