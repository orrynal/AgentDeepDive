import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor, DAGEdge
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.memory.rag_manager import rag_manager
from src.core.skill.service import SkillService


class MockSession:
    async def commit(self):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.mark.anyio
async def test_episodic_memory_query_during_healing(monkeypatch):
    # Setup DAG with a single failing node
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        description="Compile main module",
        color=NodeColor.GRAY,
        dependencies=[]
    )
    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="pending",
        nodes=[node],
        edges=[]
    )

    # Mock SkillService and database session
    mock_skill_service = MagicMock(spec=SkillService)
    mock_skill_service.session = MockSession()
    
    # Mock RAG episodic query
    mock_query_mem = MagicMock(return_value=[{
        "task_id": "prev-task",
        "prompt": "Compile main module",
        "error_stack": "ModuleNotFoundError: No module named 'numpy'",
        "patch": "pip install numpy",
        "score": 0.95
    }])
    monkeypatch.setattr(rag_manager, "query_episodic_memory", mock_query_mem)

    # Mock LiteLLM diagnostics response
    class MockMessage:
        content = '{"can_heal": true, "healing_step_name": "Install NumPy", "healing_step_description": "pip install numpy", "skill_id": "shell_exec", "arguments": {"command": "pip install numpy"}}'
    
    class MockChoice:
        message = MockMessage()
        
    class MockResponse:
        choices = [MockChoice()]

    mock_acompletion = AsyncMock(return_value=MockResponse())
    import litellm
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # Run attempt_self_healing
    engine = DAGEngine(mock_skill_service)
    healed = await engine._attempt_self_healing(dag, node, "ModuleNotFoundError: No module named 'numpy'")
    
    assert healed is True
    # Verify episodic memory query was called with the error stack
    mock_query_mem.assert_called_once_with("ModuleNotFoundError: No module named 'numpy'", limit=2, skill_id="")
    # Verify diagnostic prompt contains our history context
    called_args, called_kwargs = mock_acompletion.call_args
    prompt_sent = called_kwargs["messages"][0]["content"]
    assert "历史相似报错及成功修复经验" in prompt_sent
    assert "pip install numpy" in prompt_sent
    assert "last_error" in node.constraints
    assert node.constraints["last_error"] == "ModuleNotFoundError: No module named 'numpy'"
    assert node.constraints["self_healing_attempts"] == 1


@pytest.mark.anyio
async def test_episodic_memory_save_upon_success(monkeypatch):
    # Setup a DAG where the node previously failed (attempts = 1) and now succeeds.
    # It has a completed healing node in the DAG.
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        skill_id="compile_skill",
        description="Compile main module",
        color=NodeColor.YELLOW,  # currently running/rerunning
        dependencies=["heal-node_a-1"]
    )
    node.constraints = {
        "self_healing_attempts": 1,
        "last_error": "ModuleNotFoundError: No module named 'numpy'"
    }

    healing_node = DAGNode(
        node_id="heal-node_a-1",
        name="Install NumPy",
        skill_id="shell_exec",
        description="pip install numpy",
        color=NodeColor.GREEN,  # Succeeded
        dependencies=[]
    )
    healing_node.result = {
        "output": "Successfully installed numpy-1.24.2"
    }

    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="running",
        nodes=[healing_node, node],
        edges=[DAGEdge(from_node="heal-node_a-1", to_node="node_a")]
    )

    # Mock SkillService, DB Session, and AgentExecutor
    mock_skill_service = MagicMock(spec=SkillService)
    mock_skill_service.session = MockSession()
    
    # Mock RoleService and database calls
    class MockRoleService:
        def __init__(self, session): pass
        async def get_by_id(self, r_id): return None
    monkeypatch.setattr("src.config.settings.contract_net_enabled", False)
    monkeypatch.setattr("src.database.async_session", lambda: MockSession())

    # Mock AgentExecutor.execute to return completed
    class MockAgentExecutor:
        def __init__(self, model=None): pass
        async def execute(self, *args, **kwargs):
            return {
                "status": "completed",
                "result": "Compilation success",
                "trace": {}
            }
    monkeypatch.setattr("src.core.orchestrator.dag_engine.AgentExecutor", MockAgentExecutor)

    # Mock save_episodic_memory
    mock_save_mem = MagicMock()
    monkeypatch.setattr(rag_manager, "save_episodic_memory", mock_save_mem)

    # Run execute_node
    engine = DAGEngine(mock_skill_service)
    # Patch database session lookup and skill routing inside execute_node
    async def mock_get_by_id(self, s_id):
        return {"skill_id": s_id, "risk_level": "low", "approval_required": False}
    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)

    # Mock persistence
    monkeypatch.setattr("src.core.orchestrator.persistence.save_dag_to_disk", lambda d: None)

    await engine._execute_node(dag, node)

    # Verify original node is green
    assert node.color == NodeColor.GREEN
    # Verify episodic memory was successfully saved with the correct patch output
    mock_save_mem.assert_called_once_with(
        task_id="node_a",
        prompt="Compile main module",
        error_stack="ModuleNotFoundError: No module named 'numpy'",
        patch="Successfully installed numpy-1.24.2",
        skill_id="compile_skill"
    )


@pytest.mark.anyio
async def test_self_healing_duplicate_error_protection(monkeypatch):
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        description="Compile main module",
        color=NodeColor.GRAY,
        dependencies=[]
    )
    node.constraints = {
        "last_error": "ModuleNotFoundError: No module named 'numpy'",
        "original_dependencies": []
    }
    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="pending",
        nodes=[node],
        edges=[]
    )
    
    mock_skill_service = MagicMock(spec=SkillService)
    mock_skill_service.session = MockSession()
    
    engine = DAGEngine(mock_skill_service)
    # Consecutive same error should trigger rollback and return False
    healed = await engine._attempt_self_healing(dag, node, "ModuleNotFoundError: No module named 'numpy'")
    assert healed is False


@pytest.mark.anyio
async def test_self_healing_failed_healing_node_rollback(monkeypatch):
    # Setup node with dynamic dependency
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        description="Compile main module",
        color=NodeColor.GRAY,
        dependencies=["heal-node_a-1"]
    )
    node.constraints = {
        "original_dependencies": [],
        "self_healing_attempts": 1
    }
    healing_node = DAGNode(
        node_id="heal-node_a-1",
        name="Install NumPy",
        description="pip install numpy",
        color=NodeColor.GRAY,
        dependencies=[]
    )
    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="pending",
        nodes=[healing_node, node],
        edges=[DAGEdge(from_node="heal-node_a-1", to_node="node_a")]
    )
    
    mock_skill_service = MagicMock(spec=SkillService)
    mock_skill_service.session = MockSession()
    
    engine = DAGEngine(mock_skill_service)
    # The healing node itself fails, triggering self-healing on heal-node_a-1
    healed = await engine._attempt_self_healing(dag, healing_node, "Some install error")
    
    assert healed is False
    # Original parent node should be suspended
    assert node.color == NodeColor.SUSPENDED
    # The healing node heal-node_a-1 should be pruned/removed from the DAG nodes
    assert healing_node not in dag.nodes
    # Original dependencies of node_a should be restored
    assert node.dependencies == []
    # Dynamic edge should be removed
    assert len(dag.edges) == 0


@pytest.mark.anyio
async def test_self_healing_cannot_heal_diagnostics_rollback(monkeypatch):
    node = DAGNode(
        node_id="node_a",
        name="Compile Task",
        description="Compile main module",
        color=NodeColor.GRAY,
        dependencies=[]
    )
    node.constraints = {
        "original_dependencies": []
    }
    dag = DAGDefinition(
        dag_id="dag-123",
        name="Test DAG",
        status="pending",
        nodes=[node],
        edges=[]
    )
    
    mock_skill_service = MagicMock(spec=SkillService)
    mock_skill_service.session = MockSession()
    
    monkeypatch.setattr(rag_manager, "query_episodic_memory", MagicMock(return_value=[]))
    
    # Mock LiteLLM response with can_heal = false
    class MockMessage:
        content = '{"can_heal": false}'
    class MockChoice:
        message = MockMessage()
    class MockResponse:
        choices = [MockChoice()]
    monkeypatch.setattr("litellm.acompletion", AsyncMock(return_value=MockResponse()))
    
    engine = DAGEngine(mock_skill_service)
    healed = await engine._attempt_self_healing(dag, node, "Unresolvable syntax error")
    
    assert healed is False
