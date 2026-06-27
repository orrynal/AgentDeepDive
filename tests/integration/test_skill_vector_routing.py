import asyncio
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.memory.rag_manager import rag_manager
from src.core.skill.service import SkillService
from src.core.skill.router import SkillRouter
from src.core.skill.models import Base

@pytest.mark.asyncio
async def test_skill_vector_routing():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        service = SkillService(session)
        
        # Clear existing test skills from DB completely first
        await session.execute(
            text("DELETE FROM skills WHERE skill_id IN ('test-router-skill-1', 'test-router-skill-2')")
        )
        await session.commit()

        # Clear from local memory too
        rag_manager.local_skills = [
            s for s in rag_manager.local_skills 
            if s["skill_id"] not in ("test-router-skill-1", "test-router-skill-2")
        ]

        skill_data_1 = {
            "skill_id": "test-router-skill-1",
            "name": "Database Optimizer Pro",
            "description": "Analyzes Postgres tables, identifies missing indexes, and rewrites slow queries.",
            "tags": ["database", "postgres", "sql-optimization"],
            "trigger_patterns": ["optimize database", "slow query"],
            "required_tools": ["db_execute"],
            "risk_level": "medium",
            "approval_required": True
        }
        
        skill_data_2 = {
            "skill_id": "test-router-skill-2",
            "name": "Image Wizard",
            "description": "Generates beautiful user interfaces and marketing assets from text prompts.",
            "tags": ["graphics", "ui-design", "generation"],
            "trigger_patterns": ["create image", "design page"],
            "required_tools": ["generate_image"],
            "risk_level": "low",
            "approval_required": False
        }

        # Create skills
        await service.create(skill_data_1)
        await service.create(skill_data_2)
        await session.commit()

        # Add brief sleep to let Milvus background indexes update
        await asyncio.sleep(2.0)

        router = SkillRouter(
            session,
            embedder=rag_manager.embedder,
            milvus_client=rag_manager.client
        )
        
        # Test Query A (semantic similarity to database optimizer)
        query_a = "Can you help fix a slow query and find missing indexes?"
        matches_a = await router.route(query_a, top_k=1)
        assert len(matches_a) > 0
        assert matches_a[0]["skill_id"] == "test-router-skill-1"

        # Test Query B (semantic similarity to image wizard)
        query_b = "I need some marketing assets and UI illustrations generated."
        matches_b = await router.route(query_b, top_k=1)
        assert len(matches_b) > 0
        assert matches_b[0]["skill_id"] == "test-router-skill-2"

        # Update Skill 2 to be translation
        update_data = {
            "name": "Neural Translator Wizard",
            "description": "Translates documents from English to Chinese using high-fidelity neural networks."
        }
        await service.update("test-router-skill-2", update_data)
        await session.commit()
        await asyncio.sleep(2.0)

        query_c = "Translate this legal document to Mandarine Chinese"
        matches_c = await router.route(query_c, top_k=1)
        assert len(matches_c) > 0
        assert matches_c[0]["skill_id"] == "test-router-skill-2"

        # Deactivate Skill 1
        await service.deactivate("test-router-skill-1")
        await session.commit()
        await asyncio.sleep(2.0)

        matches_a_after = await router.route(query_a, top_k=1)
        assert "test-router-skill-1" not in [m["skill_id"] for m in matches_a_after]

        # Clean up
        await service.deactivate("test-router-skill-2")
        await session.commit()

    await engine.dispose()
