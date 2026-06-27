import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.role.models import Base, RoleModel
from src.core.role.service import RoleService
from src.core.role.loader import load_roles_from_directory
from pathlib import Path

@pytest.mark.asyncio
async def test_role_loader_and_crud():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 1. Initialize tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        service = RoleService(session)

        # 2. Test CRUD - Create Role
        test_role_data = {
            "role_id": "test_qa_engineer",
            "name": "Test QA Engineer",
            "description": "Specialist for executing test suites.",
            "system_prompt_prefix": "You are a test engineer.",
            "allowed_skills": ["test_generation"],
            "default_model": "ollama/qwen3.5:2b",
            "max_token_budget": 30000,
        }

        # Clear existing first
        existing = await service.get_by_id("test_qa_engineer")
        if existing:
            await service.deactivate("test_qa_engineer")
            await session.commit()

        new_role = await service.create(test_role_data)
        assert new_role["role_id"] == "test_qa_engineer"
        assert new_role["is_active"] is True

        # 3. Test CRUD - Get Role
        fetched = await service.get_by_id("test_qa_engineer")
        assert fetched is not None
        assert fetched["name"] == "Test QA Engineer"

        # 4. Test CRUD - Update Role
        updated = await service.update("test_qa_engineer", {"name": "Senior Test QA"})
        assert updated["name"] == "Senior Test QA"

        # 5. Test CRUD - Deactivate Role
        deactivated = await service.deactivate("test_qa_engineer")
        assert deactivated is True
        fetched_deactivated = await service.get_by_id("test_qa_engineer")
        assert fetched_deactivated["is_active"] is False

        # Clean up database entry
        from sqlalchemy import text
        await session.execute(text("DELETE FROM roles WHERE role_id = 'test_qa_engineer'"))
        await session.commit()

    # 6. Test Loader from directory (load the 10 built-in roles)
    roles_dir = Path(__file__).parent.parent.parent / "roles"
    async with async_session() as session:
        count = await load_roles_from_directory(roles_dir, session)
        await session.commit()
        assert count >= 10
        
        # Verify a specific role exists in the DB
        stmt = select(RoleModel).where(RoleModel.role_id == "senior_coder")
        result = await session.execute(stmt)
        coder_role = result.scalar_one_or_none()
        assert coder_role is not None
        assert coder_role.name == "Senior Coder / Developer"
        assert "code_refactor" in coder_role.allowed_skills

    await engine.dispose()
