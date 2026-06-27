import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.skill.service import SkillService
from src.core.agent.pool import agent_bus
from src.core.orchestrator.persistence import save_dag_to_disk, load_dags_from_disk
from src.cli.chat.session import ChatSession
from src.cli.chat.renderer import StreamRenderer
from src.cli.chat.slash_commands import handle_slash_command
from rich.console import Console

@pytest.mark.asyncio
async def test_dag_breakpoint_and_interactivity_flow(tmp_path):
    # Setup database
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    from src.database import Base as DbBase
    from src.core.auth.models import TenantModel, UserModel
    async with engine.begin() as conn:
        await conn.run_sync(DbBase.metadata.create_all)

    # Register a mock skill for testing
    async with async_session() as session:
        skill_svc = SkillService(session)
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'test_breakpoint_skill'"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "test_breakpoint_skill",
            "name": "Test Breakpoint",
            "tags": ["test"],
            "system_prompt": "Test prompt",
        })
        await session.commit()

    # Define a DAG with a node that will fail
    dag = DAGDefinition(
        name="Breakpoint Test DAG",
        workspace_path=str(tmp_path),
        project_name="breakpoint_test",
        nodes=[
            DAGNode(
                node_id="node-failing-breakpoint",
                name="Failing Node",
                skill_id="test_breakpoint_skill",
                description="This node will fail execution",
            )
        ]
    )

    # 1. Test Suspension State & Bus Notification
    exec_counts = 0
    async def mock_agent_execute(self, task_id, task_description, skill, context="", role=None, tenant_id=None):
        nonlocal exec_counts
        exec_counts += 1
        if exec_counts == 1:
            return {
                "status": "failed",
                "error": "Simulated unhealable failure",
                "trace": {}
            }
        return {
            "status": "completed",
            "result": "Success after intervention",
            "trace": {}
        }

    # Listen to the message bus for workflow.suspended
    suspended_events = []
    async def on_suspended(event_data):
        suspended_events.append(event_data)

    await agent_bus.subscribe("workflow.suspended", on_suspended)

    # Mock litellm choice to return can_heal=False so it goes straight to suspended
    mock_choice = AsyncMock()
    mock_choice.message.content = '{"can_heal": false, "healing_step_name": "", "healing_step_description": "", "skill_id": ""}'
    mock_litellm_resp = AsyncMock()
    mock_litellm_resp.choices = [mock_choice]

    try:
        with patch("src.core.agent.executor.AgentExecutor.execute", mock_agent_execute), \
             patch("litellm.acompletion", return_value=mock_litellm_resp):
            
            async with async_session() as session:
                skill_svc = SkillService(session)
                dag_engine = DAGEngine(skill_svc)
                
                result_dag = await dag_engine.execute(dag)
                await session.commit()

                # Verify execution suspended
                assert result_dag.status == "paused"
                failed_node = result_dag.get_node("node-failing-breakpoint")
                assert failed_node.color == NodeColor.SUSPENDED
                assert failed_node.error == "Simulated unhealable failure"

                # Verify event was published
                await asyncio.sleep(0.1)  # allow pub/sub task to run
                assert len(suspended_events) == 1
                assert suspended_events[0]["payload"]["node_id"] == "node-failing-breakpoint"
                assert suspended_events[0]["payload"]["dag_id"] == dag.dag_id

        # 2. Test REPL slash command /bypass integration
        chat_session = ChatSession(tenant_id="00000000-0000-0000-0000-000000000000")
        chat_session.active_suspended_node = {
            "dag_id": dag.dag_id,
            "node_id": "node-failing-breakpoint",
            "error": "Simulated unhealable failure"
        }
        renderer = StreamRenderer(Console())

        # Mock detect_mode_async to return local
        with patch("src.cli.context.CLIContext.detect_mode_async", return_value=AsyncMock(value="local")), \
             patch("src.cli.context.CLIContext.resolve_tenant_id", return_value="00000000-0000-0000-0000-000000000000"), \
             patch("src.cli.context.CLIContext.get_db", return_value=AsyncMock(__aenter__=AsyncMock(return_value=session))):
            
            # Execute /bypass command
            success = await handle_slash_command("/bypass", chat_session, renderer)
            assert success is True
            assert chat_session.active_suspended_node is None

            # Verify node status updated to GREEN locally
            await asyncio.sleep(0.5)  # wait for local background run task to finish
            dags = load_dags_from_disk(tenant_id="00000000-0000-0000-0000-000000000000")
            updated_dag = dags.get(dag.dag_id)
            assert updated_dag is not None
            assert updated_dag.status == "completed"
            assert updated_dag.get_node("node-failing-breakpoint").color == NodeColor.GREEN

    finally:
        await agent_bus.unsubscribe("workflow.suspended", on_suspended)
        await engine.dispose()
