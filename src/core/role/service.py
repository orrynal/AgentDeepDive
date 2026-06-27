import uuid
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.role.models import RoleModel

logger = structlog.get_logger()


class RoleService:
    """Service layer for Agent Role CRUD operations against PostgreSQL."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | str = '00000000-0000-0000-0000-000000000000'):
        self.session = session
        self.tenant_id = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))

    async def create(self, data: dict) -> dict:
        """Create a new Role in the database."""
        data = {k: v for k, v in data.items() if k != "id"}
        data["tenant_id"] = self.tenant_id
        role = RoleModel(**data)
        self.session.add(role)
        await self.session.flush()
        await self.session.refresh(role)
        logger.info("Created new agent role", role_id=role.role_id, name=role.name, tenant_id=str(self.tenant_id))
        return role.to_dict()

    async def get_by_id(self, role_id: str) -> dict | None:
        """Get a single Role by its role_id."""
        stmt = select(RoleModel).where(RoleModel.tenant_id == self.tenant_id).where(RoleModel.role_id == role_id)
        result = await self.session.execute(stmt)
        role = result.scalar_one_or_none()
        return role.to_dict() if role else None

    async def list_all(self, active_only: bool = True) -> list[dict]:
        """List all Roles, optionally filtering active-only."""
        stmt = select(RoleModel).where(RoleModel.tenant_id == self.tenant_id).order_by(RoleModel.created_at.desc())
        if active_only:
            stmt = stmt.where(RoleModel.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return [r.to_dict() for r in result.scalars().all()]

    async def update(self, role_id: str, data: dict) -> dict | None:
        """Update an existing Role."""
        update_data = {k: v for k, v in data.items() if v is not None and k != "id"}
        if not update_data:
            return await self.get_by_id(role_id)
        stmt = (
            update(RoleModel)
            .where(RoleModel.tenant_id == self.tenant_id)
            .where(RoleModel.role_id == role_id)
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        logger.info("Updated agent role", role_id=role_id, tenant_id=str(self.tenant_id))
        return await self.get_by_id(role_id)

    async def deactivate(self, role_id: str) -> bool:
        """Soft-delete a Role by setting is_active=False."""
        stmt = (
            update(RoleModel)
            .where(RoleModel.tenant_id == self.tenant_id)
            .where(RoleModel.role_id == role_id)
            .values(is_active=False)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        success = result.rowcount > 0
        if success:
            logger.info("Deactivated agent role", role_id=role_id, tenant_id=str(self.tenant_id))
        return success
