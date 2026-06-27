import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.skill.models import Base as SkillBase
from src.core.role.models import Base as RoleBase
from src.core.skill.service import SkillService

@pytest.mark.asyncio
async def test_dag_self_healing_flow():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        skill_svc = SkillService(session)
        # Clear existing
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'code_refactor'"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "code_refactor",
            "name": "Mock Refactor",
            "tags": ["refactor"],
            "system_prompt": "Refactor prompt",
        })
        await session.commit()

    # Define a simple DAG
    dag = DAGDefinition(
        name="Self Healing Test DAG",
        workspace_path="/tmp/test_workspace",
        project_name="self_healing_test",
        nodes=[
            DAGNode(
                node_id="node-fail",
                name="Failing Node",
                skill_id="code_refactor",
                description="Refactor python imports",
            )
        ]
    )

    # State variables for our mock execution states
    exec_counts = 0

    async def mock_agent_execute(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        nonlocal exec_counts
        exec_counts += 1
        
        if task_id == "node-fail" and exec_counts == 1:
            # First execution fails
            return {
                "status": "failed",
                "error": "ModuleNotFoundError: No module named 'requests'",
                "trace": {}
            }
        
        # Second execution or healing node execution succeeds
        return {
            "status": "completed",
            "result": f"Executed task {task_id} successfully",
            "trace": {}
        }

    # Mock litellm diagnostics response
    mock_choice = AsyncMock()
    mock_choice.message.content = (
        '{"can_heal": true, "healing_step_name": "Install Requests", '
        '"healing_step_description": "pip install requests", "skill_id": "code_refactor"}'
    )
    mock_litellm_resp = AsyncMock()
    mock_litellm_resp.choices = [mock_choice]

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute), \
         patch("litellm.acompletion", return_value=mock_litellm_resp):
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()

            # The DAG nodes list should now contain 2 nodes:
            # 1. The dynamically injected healing node: heal-node-fail-1
            # 2. The original failing node: node-fail
            assert len(result_dag.nodes) == 2
            assert result_dag.nodes[0].node_id == "heal-node-fail-1"
            assert result_dag.nodes[1].node_id == "node-fail"

            # Both nodes should have successfully completed (GREEN)
            assert result_dag.nodes[0].color == "green"
            assert result_dag.nodes[1].color == "green"
            assert result_dag.status == "completed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dag_self_healing_prevention_of_recursive_loops():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        skill_svc = SkillService(session)
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'code_refactor'"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "code_refactor",
            "name": "Mock Refactor",
            "tags": ["refactor"],
            "system_prompt": "Refactor prompt",
        })
        await session.commit()

    # Define a simple DAG
    dag = DAGDefinition(
        name="Recursive Healing Test DAG",
        workspace_path="/tmp/test_workspace",
        project_name="self_healing_test",
        nodes=[
            DAGNode(
                node_id="node-fail",
                name="Failing Node",
                skill_id="code_refactor",
                description="Refactor python imports",
            )
        ]
    )

    async def mock_agent_execute(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        # Every execution fails (including the healing node!)
        return {
            "status": "failed",
            "error": "Simulated error on task_id: " + task_id,
            "trace": {}
        }

    # Mock litellm diagnostics response to say we can heal (so it inserts a healing node)
    mock_choice = AsyncMock()
    mock_choice.message.content = (
        '{"can_heal": true, "healing_step_name": "Install Requests", '
        '"healing_step_description": "pip install requests", "skill_id": "code_refactor"}'
    )
    mock_litellm_resp = AsyncMock()
    mock_litellm_resp.choices = [mock_choice]

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute), \
         patch("litellm.acompletion", return_value=mock_litellm_resp):
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()

            # Ensure the healing node failed and did not spawn another healing node (no nested healing)
            # The DAG nodes list should be rolled back to only contain the original node:
            # 1. The original failing node: node-fail (suspended)
            assert len(result_dag.nodes) == 1
            assert result_dag.nodes[0].node_id == "node-fail"
            assert result_dag.nodes[0].color == "suspended"
            assert result_dag.status == "paused"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dag_self_healing_configurable_attempts():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        skill_svc = SkillService(session)
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'code_refactor'"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "code_refactor",
            "name": "Mock Refactor",
            "tags": ["refactor"],
            "system_prompt": "Refactor prompt",
        })
        await session.commit()

    # Define a simple DAG with constraints max_self_healing_attempts = 1
    dag = DAGDefinition(
        name="Max Attempts Test DAG",
        workspace_path="/tmp/test_workspace",
        project_name="self_healing_test",
        constraints={"max_self_healing_attempts": 1, "self_healing_delay": 0.01},
        nodes=[
            DAGNode(
                node_id="node-fail-max",
                name="Failing Node Max",
                skill_id="code_refactor",
                description="Refactor python imports",
            )
        ]
    )

    exec_counts = 0
    async def mock_agent_execute(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        nonlocal exec_counts
        exec_counts += 1
        return {
            "status": "failed",
            "error": f"Failed run {exec_counts}",
            "trace": {}
        }

    mock_choice = AsyncMock()
    mock_choice.message.content = (
        '{"can_heal": true, "healing_step_name": "Install Requests", '
        '"healing_step_description": "pip install requests", "skill_id": "code_refactor"}'
    )
    mock_litellm_resp = AsyncMock()
    mock_litellm_resp.choices = [mock_choice]

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute), \
         patch("litellm.acompletion", return_value=mock_litellm_resp):
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()

            # When heal-node-fail-max-1 fails, it halts and rolls back the dynamic healing nodes.
            # Total node count in the final DAG returns to 1.
            assert len(result_dag.nodes) == 1
            assert result_dag.nodes[0].node_id == "node-fail-max"
            assert result_dag.status == "paused"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dag_self_healing_hitl_approval_flow():
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel

    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    async with async_session() as session:
        skill_svc = SkillService(session)
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'code_refactor'"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "code_refactor",
            "name": "Mock Refactor",
            "tags": ["refactor"],
            "system_prompt": "Refactor prompt",
        })
        await session.commit()

    # Define a simple DAG with constraints self_healing_hitl = True
    dag = DAGDefinition(
        name="HITL Self Healing Test DAG",
        workspace_path="/tmp/test_workspace",
        project_name="self_healing_test",
        constraints={"self_healing_hitl": True},
        nodes=[
            DAGNode(
                node_id="node-fail-hitl",
                name="Failing Node HITL",
                skill_id="code_refactor",
                description="Refactor python imports",
            )
        ]
    )

    mock_choice = AsyncMock()
    mock_choice.message.content = (
        '{"can_heal": true, "healing_step_name": "Install Requests", '
        '"healing_step_description": "pip install requests", "skill_id": "code_refactor"}'
    )
    mock_litellm_resp = AsyncMock()
    mock_litellm_resp.choices = [mock_choice]

    # First, test REJECTED approval
    exec_counts_reject = 0
    async def mock_agent_execute_reject(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        nonlocal exec_counts_reject
        exec_counts_reject += 1
        if task_id == "node-fail-hitl" and exec_counts_reject == 1:
            return {
                "status": "failed",
                "error": "ModuleNotFoundError: No module named 'requests'",
                "trace": {}
            }
        return {
            "status": "completed",
            "result": f"Executed task {task_id} successfully",
            "trace": {}
        }

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute_reject), \
         patch("litellm.acompletion", return_value=mock_litellm_resp), \
         patch("src.core.governance.approval.ApprovalManager.request_approval", return_value="appr-123") as mock_req, \
         patch("src.core.governance.approval.ApprovalManager.wait_for_approval", return_value=False) as mock_wait:
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()

            # Since the user rejected, the healing node should NOT be inserted
            # and the node should be SUSPENDED
            assert len(result_dag.nodes) == 1
            assert result_dag.nodes[0].node_id == "node-fail-hitl"
            assert result_dag.nodes[0].color == "suspended"
            assert result_dag.status == "paused"
            
            mock_req.assert_called_once()
            mock_wait.assert_called_once_with("appr-123")

    # Second, test APPROVED approval
    # Reset DAG state for retry
    dag = DAGDefinition(
        name="HITL Self Healing Test DAG",
        workspace_path="/tmp/test_workspace",
        project_name="self_healing_test",
        constraints={"self_healing_hitl": True},
        nodes=[
            DAGNode(
                node_id="node-fail-hitl",
                name="Failing Node HITL",
                skill_id="code_refactor",
                description="Refactor python imports",
            )
        ]
    )

    exec_counts_approve = 0
    async def mock_agent_execute_approve(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        nonlocal exec_counts_approve
        exec_counts_approve += 1
        if task_id == "node-fail-hitl" and exec_counts_approve == 1:
            return {
                "status": "failed",
                "error": "ModuleNotFoundError: No module named 'requests'",
                "trace": {}
            }
        return {
            "status": "completed",
            "result": f"Executed task {task_id} successfully",
            "trace": {}
        }

    with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute_approve), \
         patch("litellm.acompletion", return_value=mock_litellm_resp), \
         patch("src.core.governance.approval.ApprovalManager.request_approval", return_value="appr-456") as mock_req, \
         patch("src.core.governance.approval.ApprovalManager.wait_for_approval", return_value=True) as mock_wait:
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()

            # Since the user approved, the healing node is inserted and executed
            assert len(result_dag.nodes) == 2
            assert result_dag.nodes[0].node_id == "heal-node-fail-hitl-1"
            assert result_dag.nodes[0].color == "green"
            assert result_dag.nodes[1].node_id == "node-fail-hitl"
            assert result_dag.nodes[1].color == "green"
            assert result_dag.status == "completed"
            
            mock_req.assert_called_once()
            mock_wait.assert_called_once_with("appr-456")

    await engine.dispose()
