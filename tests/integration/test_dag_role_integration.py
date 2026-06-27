import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.skill.models import Base as SkillBase, SkillModel
from src.core.role.models import Base as RoleBase
from src.core.role.loader import load_roles_from_directory
from src.core.skill.service import SkillService
from pathlib import Path

@pytest.mark.asyncio
async def test_dag_role_binding_and_auto_routing():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    # 1. Initialize tables
    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        # Load the built-in roles
        roles_dir = Path(__file__).parent.parent.parent / "roles"
        await load_roles_from_directory(roles_dir, session)
        
        # Insert test skills (using valid allowed_skills names from roles configuration)
        skill_svc = SkillService(session)
        
        # Clear existing
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id IN ('code_refactor', 'test_generation')"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "code_refactor",
            "name": "Mock Refactor",
            "tags": ["refactor"],
            "system_prompt": "Refactor prompt",
        })
        await skill_svc.create({
            "skill_id": "test_generation",
            "name": "Mock Test Gen",
            "tags": ["test_generation"],
            "system_prompt": "Test gen prompt",
        })
        await session.commit()

    # 2. Define a DAG with explicit role and auto role
    dag = DAGDefinition(
        name="Test Role DAG",
        workspace_path="/tmp/test_workspace",
        project_name="role_test",
        nodes=[
            DAGNode(
                node_id="node-refactor",
                name="Refactor Node",
                skill_id="code_refactor",
                role_id="senior_coder",  # Explicit role
                description="Refactor memory management",
            ),
            DAGNode(
                node_id="node-test",
                name="Test Node",
                skill_id="test_generation",
                role_id="auto",  # Auto role resolution
                description="Generate unit tests",
                dependencies=["node-refactor"],
            )
        ]
    )

    # 3. Mock AgentExecutor.execute to avoid making LLM calls during DAG engine test
    captured_executes = []
    
    async def mock_execute(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        captured_executes.append({
            "task_id": task_id,
            "skill_id": skill["skill_id"],
            "role_id": role["role_id"] if role else None,
            "role_name": role["name"] if role else None,
        })
        return {
            "status": "completed",
            "result": f"Executed task {task_id} successfully",
            "trace": {}
        }

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_execute):
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()
            
            # Print node errors if any failed
            for n in result_dag.nodes:
                if n.error:
                    print(f"Node {n.node_id} failed with error: {n.error}")

            assert result_dag.status == "completed"
            assert result_dag.nodes[0].color == "green"
            assert result_dag.nodes[1].color == "green"

    # 4. Assert role mappings were resolved and passed correctly
    assert len(captured_executes) == 2
    
    # First node: explicit 'senior_coder'
    assert captured_executes[0]["task_id"] == "node-refactor"
    assert captured_executes[0]["skill_id"] == "code_refactor"
    assert captured_executes[0]["role_id"] == "senior_coder"
    assert captured_executes[0]["role_name"] == "Senior Coder / Developer"
    
    # Second node: 'auto' should be resolved to 'qa_tester' or 'senior_coder' based on semantic description
    assert captured_executes[1]["task_id"] == "node-test"
    assert captured_executes[1]["skill_id"] == "test_generation"
    assert captured_executes[1]["role_id"] in ["qa_tester", "senior_coder"]

    # Verify node model itself was updated
    assert result_dag.get_node("node-test").role_id in ["qa_tester", "senior_coder"]

    await engine.dispose()
