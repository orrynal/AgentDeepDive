import sys
from pathlib import Path

agent_deep_dive_path = str(Path(__file__).parent.parent.parent)
if agent_deep_dive_path not in sys.path:
    sys.path.insert(0, agent_deep_dive_path)

# Remove any paths containing ProsodyFlow from sys.path to prevent namespace collision
sys.path = [p for p in sys.path if "ProsodyFlow" not in p]

# Clear cached src and all its submodules only if it was loaded from the wrong path (e.g. ProsodyFlow)
if "src" in sys.modules:
    src_file = getattr(sys.modules["src"], "__file__", "") or ""
    if src_file:
        try:
            abs_src_path = str(Path(src_file).resolve())
        except Exception:
            abs_src_path = src_file
        if "ProsodyFlow" in abs_src_path:
            for key in list(sys.modules.keys()):
                if key == "src" or key.startswith("src."):
                    sys.modules.pop(key, None)

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.agent.router import AdaptiveRouter, RoutingTier
from src.core.agent.generalist import GeneralistAgent
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine

def test_adaptive_router_file_counting(tmp_path):
    # Create some dummy files in the tmp_path
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "utils.py").write_text("pass")
    
    # Create ignored folder
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pip.py").write_text("pass")
    
    # Count should be 2 (main.py, utils.py)
    count = AdaptiveRouter.count_workspace_files(str(tmp_path))
    assert count == 2

def test_adaptive_router_tier_determination():
    # Settings default check: max_nodes_small=5, max_files_small=20
    # 1. Tier 1 (Small)
    tier = AdaptiveRouter.determine_tier(node_count=3, workspace_path=None)
    assert tier == RoutingTier.SMALL

    # 2. Tier 2 (Medium) - higher nodes than small limit but within medium limit (15)
    tier = AdaptiveRouter.determine_tier(node_count=7, workspace_path=None)
    assert tier == RoutingTier.MEDIUM

    # 3. Tier 3 (Large) - exceeds medium node limit
    tier = AdaptiveRouter.determine_tier(node_count=20, workspace_path=None)
    assert tier == RoutingTier.LARGE

    # 4. Explicit override
    tier = AdaptiveRouter.determine_tier(node_count=1, workspace_path=None, explicit_tier="medium")
    assert tier == RoutingTier.MEDIUM

@pytest.mark.asyncio
async def test_generalist_agent_context_assembly(monkeypatch):
    agent = GeneralistAgent()
    
    # Mock executor execute method
    mock_execute = AsyncMock(return_value={"status": "completed", "result": "success", "trace": {}})
    monkeypatch.setattr(agent.executor, "execute", mock_execute)
    
    parent_outputs = {
        "node-1": "designed schema",
        "node-2": {"status": "ok", "rows": 10}
    }
    
    res = await agent.execute_node(
        task_id="task-123",
        node_instruction="implement logic",
        parent_outputs=parent_outputs,
        allowed_tools=["file_read", "file_write"]
    )
    
    assert res["status"] == "completed"
    
    # Verify execute arguments
    args, kwargs = mock_execute.call_args
    assert kwargs["task_id"] == "task-123"
    assert "designed schema" in kwargs["context"]
    assert "node-1" in kwargs["context"]
    assert "node-2" in kwargs["context"]
    assert kwargs["skill"]["required_tools"] == ["file_read", "file_write"]

@pytest.mark.asyncio
async def test_dag_engine_small_tier_routing(monkeypatch):
    # Mock SkillService
    from src.core.skill.service import SkillService
    mock_skill = {"skill_id": "test-skill", "required_tools": ["file_read"], "approval_required": False}
    
    monkeypatch.setattr(SkillService, "get_by_id", AsyncMock(return_value=mock_skill))
    
    # Mock ab_manager methods to bypass DB/Redis
    from src.core.evolution.ab_manager import ab_manager
    monkeypatch.setattr(ab_manager, "get_routing_decision", AsyncMock(return_value="test-skill"))
    monkeypatch.setattr(ab_manager, "record_run_result", AsyncMock())
    
    engine = DAGEngine(skill_service=None)
    
    # 1. Create a 1-node DAG (Small tier)
    node_a = DAGNode(node_id="A", name="Node A", skill_id="test-skill")
    dag = DAGDefinition(
        dag_id="small-dag-123",
        name="Small Test DAG",
        nodes=[node_a],
        routing_tier="small"
    )
    
    # Mock AgentExecutor execution
    from src.core.agent.executor import AgentExecutor
    mock_execute = AsyncMock(return_value={"status": "completed", "result": "node_a_success", "trace": {}})
    monkeypatch.setattr(AgentExecutor, "execute", mock_execute)
    
    import src.core.orchestrator.persistence as persistence_module
    import src.core.agent.pool as pool_module
    import src.database as db_module
    
    # Mock save to disk to bypass actual disk writes
    monkeypatch.setattr(persistence_module, "save_dag_to_disk", lambda x: None)
    monkeypatch.setattr(pool_module.agent_bus, "publish", AsyncMock())
    
    # We must patch async_session context manager
    mock_session = AsyncMock()
    async_context = MagicMock()
    async_context.__aenter__.return_value = mock_session
    monkeypatch.setattr(db_module, "async_session", MagicMock(return_value=async_context))
    
    # Execute the DAG
    await engine.execute(dag)
    
    # Verify it ran using GeneralistAgent execution
    assert dag.routing_tier == "small"
    assert mock_execute.called is True
    assert dag.nodes[0].color == NodeColor.GREEN
    assert dag.nodes[0].result["output"] == "node_a_success"
