import uuid
import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.skill.models import SkillModel

logger = structlog.get_logger()


class SkillService:
    """Service layer for Skill CRUD operations against PostgreSQL."""

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID | str | None = '00000000-0000-0000-0000-000000000000'):
        self.session = session
        if tenant_id is None or str(tenant_id) == "None":
            tenant_id = '00000000-0000-0000-0000-000000000000'
        self.tenant_id = tenant_id if isinstance(tenant_id, uuid.UUID) else uuid.UUID(str(tenant_id))

    async def create(self, data: dict) -> dict:
        """Create a new Skill in the database."""
        data = {k: v for k, v in data.items() if k != "id"}
        data["tenant_id"] = self.tenant_id
        skill = SkillModel(**data)
        self.session.add(skill)
        await self.session.flush()
        await self.session.refresh(skill)

        # Sync to Milvus/RAGManager
        try:
            from src.core.memory.rag_manager import rag_manager
            rag_manager.upsert_skill(
                skill_id=skill.skill_id,
                name=skill.name,
                description=skill.description or "",
            )
        except Exception as e:
            logger.error("Failed to sync new skill embedding to Milvus", skill_id=skill.skill_id, error=str(e))

        return skill.to_dict()

    async def get_by_id(self, skill_id: str) -> dict | None:
        """Get a single Skill by its skill_id."""
        stmt = select(SkillModel).where(SkillModel.tenant_id == self.tenant_id).where(SkillModel.skill_id == skill_id)
        result = await self.session.execute(stmt)
        skill = result.scalar_one_or_none()
        return skill.to_dict() if skill else None

    async def list_all(self, active_only: bool = True, workspace_path: str | None = None) -> list[dict]:
        """List all Skills, optionally filtering active-only and workspace path."""
        stmt = select(SkillModel).where(SkillModel.tenant_id == self.tenant_id).order_by(SkillModel.created_at.desc())
        if active_only:
            stmt = stmt.where(SkillModel.is_active == True)  # noqa: E712
        if workspace_path is not None:
            stmt = stmt.where(
                (SkillModel.workspace_path == None) | (SkillModel.workspace_path == "") | (SkillModel.workspace_path == workspace_path)
            )
        result = await self.session.execute(stmt)
        return [s.to_dict() for s in result.scalars().all()]

    async def update(self, skill_id: str, data: dict) -> dict | None:
        """Update an existing Skill."""
        update_data = {k: v for k, v in data.items() if k != "id"}
        if not update_data:
            return await self.get_by_id(skill_id)
        stmt = (
            update(SkillModel)
            .where(SkillModel.tenant_id == self.tenant_id)
            .where(SkillModel.skill_id == skill_id)
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        # Sync to Milvus/RAGManager
        updated_skill = await self.get_by_id(skill_id)
        if updated_skill:
            try:
                from src.core.memory.rag_manager import rag_manager
                rag_manager.upsert_skill(
                    skill_id=updated_skill["skill_id"],
                    name=updated_skill["name"],
                    description=updated_skill["description"] or "",
                )
            except Exception as e:
                logger.error("Failed to sync updated skill embedding to Milvus", skill_id=skill_id, error=str(e))

        return updated_skill

    async def deactivate(self, skill_id: str) -> bool:
        """Soft-delete a Skill by setting is_active=False."""
        stmt = (
            update(SkillModel)
            .where(SkillModel.tenant_id == self.tenant_id)
            .where(SkillModel.skill_id == skill_id)
            .values(is_active=False)
        )
        result = await self.session.execute(stmt)

        # Sync to Milvus (delete embedding)
        try:
            from src.core.memory.rag_manager import rag_manager
            from src.core.memory.rag_manager import MockMilvusClient
            if rag_manager.connected and rag_manager.client and not isinstance(rag_manager.client, MockMilvusClient):
                rag_manager.client.delete(
                    collection_name="skill_embeddings",
                    filter=f"skill_id == '{skill_id}'"
                )
            # Also clean from local fallback
            rag_manager.local_skills = [s for s in rag_manager.local_skills if s["skill_id"] != skill_id]
        except Exception as e:
            logger.error("Failed to delete skill embedding from Milvus on deactivation", skill_id=skill_id, error=str(e))

        return result.rowcount > 0

    async def delete(self, skill_id: str) -> bool:
        """Completely uninstall/delete a Skill from database."""
        from sqlalchemy import delete
        stmt = delete(SkillModel).where(SkillModel.tenant_id == self.tenant_id).where(SkillModel.skill_id == skill_id)
        result = await self.session.execute(stmt)

        # Sync to Milvus (delete embedding)
        try:
            from src.core.memory.rag_manager import rag_manager
            from src.core.memory.rag_manager import MockMilvusClient
            if rag_manager.connected and rag_manager.client and not isinstance(rag_manager.client, MockMilvusClient):
                rag_manager.client.delete(
                    collection_name="skill_embeddings",
                    filter=f"skill_id == '{skill_id}'"
                )
            # Also clean from local fallback
            rag_manager.local_skills = [s for s in rag_manager.local_skills if s["skill_id"] != skill_id]
        except Exception as e:
            logger.error("Failed to delete skill embedding from Milvus on uninstall", skill_id=skill_id, error=str(e))

        return result.rowcount > 0

    async def search_by_tags(self, tags: list[str], workspace_path: str | None = None) -> list[dict]:
        """Find Skills that match any of the given tags using raw SQL to avoid type cast issues."""
        if workspace_path is not None:
            stmt = text(
                "SELECT * FROM skills WHERE tenant_id = :tenant_id AND is_active = true AND tags && cast(:tags as text[]) AND (workspace_path IS NULL OR workspace_path = '' OR workspace_path = :workspace_path)"
            )
            result = await self.session.execute(stmt, {"tags": tags, "workspace_path": workspace_path, "tenant_id": self.tenant_id})
        else:
            stmt = text(
                "SELECT * FROM skills WHERE tenant_id = :tenant_id AND is_active = true AND tags && cast(:tags as text[])"
            )
            result = await self.session.execute(stmt, {"tags": tags, "tenant_id": self.tenant_id})

        rows = result.mappings().all()
        # Convert to dict matching SkillModel.to_dict() format
        return [
            {
                "id": str(r["id"]),
                "tenant_id": str(r["tenant_id"]),
                "skill_id": r["skill_id"],
                "name": r["name"],
                "version": r["version"],
                "description": r["description"],
                "tags": r["tags"] or [],
                "trigger_patterns": r["trigger_patterns"] or [],
                "context_budget": r["context_budget"],
                "required_tools": r["required_tools"] or [],
                "input_schema": r["input_schema"] or {},
                "output_schema": r["output_schema"] or {},
                "system_prompt": r["system_prompt"],
                "risk_level": r["risk_level"],
                "approval_required": r["approval_required"],
                "estimated_tokens": r["estimated_tokens"],
                "estimated_duration_sec": r["estimated_duration_sec"],
                "workspace_path": r["workspace_path"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in rows
        ]
