import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.role.models import Base as RoleBase
from src.core.role.loader import load_roles_from_directory
from src.core.role.router import RoleRouter
from src.core.memory.rag_manager import rag_manager
from pathlib import Path

@pytest.mark.asyncio
async def test_semantic_role_router():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 1. Initialize tables and load built-in roles
    async with engine.begin() as conn:
        await conn.run_sync(RoleBase.metadata.create_all)

    async with async_session() as session:
        roles_dir = Path(__file__).parent.parent.parent / "roles"
        await load_roles_from_directory(roles_dir, session)
        await session.commit()

    async with async_session() as session:
        # 2. Instantiate RoleRouter (using the embedder from rag_manager)
        router = RoleRouter(session, embedder=rag_manager.embedder)

        # Case A: If only one role allows the skill, security gate assigns it directly
        # 'task_splitting' is only allowed by 'supervisor'
        role_a = await router.route_role(
            query="Analyze requirements and split them into subtasks",
            skill_id="task_splitting"
        )
        assert role_a is not None
        assert role_a["role_id"] == "supervisor"

        # Case B: Multiple roles allow 'test_generation' (senior_coder and qa_tester)
        # Let's verify selection
        role_b = await router.route_role(
            query="Write robust developer algorithms and core database storage engine logic",
            skill_id="test_generation"
        )
        assert role_b is not None
        assert role_b["role_id"] in ["senior_coder", "qa_tester"]

        role_c = await router.route_role(
            query="Rigorous QA testing coverage mock verification boundary check",
            skill_id="test_generation"
        )
        assert role_c is not None
        assert role_c["role_id"] in ["senior_coder", "qa_tester"]

    await engine.dispose()
