import pytest
import asyncio
import time
from src.core.orchestrator.models import DAGDefinition, DAGNode, DAGEdge, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.agent.pool import agent_bus

pytestmark = pytest.mark.integration

@pytest.mark.anyio
async def test_complex_topology_stress_and_high_frequency():
    """Stress test DAG Engine scheduling, cycle detection, and high-frequency updates on a 500-node topology."""
    # 1. Generate a complex layered topology: 50 layers, 10 nodes per layer = 500 nodes
    num_layers = 50
    nodes_per_layer = 10
    nodes = []
    edges = []
    
    # Add nodes
    for layer in range(num_layers):
        for idx in range(nodes_per_layer):
            node_id = f"L{layer}N{idx}"
            # Layer 0 has no dependencies, others depend on all nodes in the previous layer
            deps = []
            if layer > 0:
                deps = [f"L{layer-1}N{i}" for i in range(nodes_per_layer)]
            nodes.append(DAGNode(
                node_id=node_id,
                name=f"Node {node_id}",
                skill_id="test_skill",
                dependencies=deps
            ))
            
            # Create edges matching dependencies
            for dep in deps:
                edges.append(DAGEdge(from_node=dep, to_node=node_id))
                
    dag = DAGDefinition(
        dag_id="stress-test-500",
        name="500 Node Stress DAG",
        nodes=nodes,
        edges=edges
    )
    
    # 2. Performance benchmark: cycle validation on 500 nodes
    engine = DAGEngine(skill_service=None)
    start_time = time.perf_counter()
    has_no_cycles = engine._validate_no_cycles(dag)
    duration = time.perf_counter() - start_time
    
    assert has_no_cycles is True
    # Kahn's algorithm on a 500-node graph with 4900 edges should run in < 0.05 seconds
    assert duration < 0.05, f"Cycle validation took too long: {duration:.4f}s"
    
    # 3. Test high frequency event emission over agent_bus
    messages_received = []
    
    async def message_callback(msg):
        messages_received.append(msg)
        
    await agent_bus.subscribe("dag_updates", message_callback)
    
    # Emit 500 state updates sequentially and verify high frequency delivery
    emit_start = time.perf_counter()
    for node in nodes:
        # Simulate state transition: GRAY -> BLUE -> YELLOW -> GREEN
        engine._transition(dag, node, NodeColor.BLUE)
        engine._transition(dag, node, NodeColor.YELLOW)
        engine._transition(dag, node, NodeColor.GREEN)
        
    # Allow event loop to process callbacks
    for _ in range(50):
        if len(messages_received) >= 1500:
            break
        await asyncio.sleep(0.1)
    emit_duration = time.perf_counter() - emit_start
    
    # Unsubscribe to clean up
    await agent_bus.unsubscribe("dag_updates", message_callback)
    
    # Verify we received all 1500 transitions (3 per node)
    assert len(messages_received) >= 1500
    # Average transition latency should be extremely fast
    assert emit_duration < 5.0, f"Emitting 1500 updates took too long: {emit_duration:.4f}s"


@pytest.mark.anyio
async def test_dag_execution_stress_with_concurrency(monkeypatch):
    """Stress test DAG Engine executing 100 nodes concurrently with mocked LLM and DB."""
    # 1. Create a 100-node DAG: 10 layers, 10 nodes per layer
    num_layers = 10
    nodes_per_layer = 10
    nodes = []
    edges = []
    
    for layer in range(num_layers):
        for idx in range(nodes_per_layer):
            node_id = f"L{layer}N{idx}"
            deps = []
            if layer > 0:
                deps = [f"L{layer-1}N{i}" for i in range(nodes_per_layer)]
            nodes.append(DAGNode(
                node_id=node_id,
                name=f"Node {node_id}",
                skill_id="test_skill",
                dependencies=deps
            ))
            for dep in deps:
                edges.append(DAGEdge(from_node=dep, to_node=node_id))
                
    dag = DAGDefinition(
        dag_id="stress-execute-100",
        name="100 Node Stress Execution DAG",
        nodes=nodes,
        edges=edges
    )
    
    # 2. Mock external services to bypass I/O and database
    from src.core.skill.service import SkillService
    from src.core.evolution.ab_manager import ab_manager
    from src.core.orchestrator import persistence
    import litellm
    from unittest.mock import AsyncMock
    from src.core.orchestrator.central_brain import central_brain
    monkeypatch.setattr(central_brain, "check_budget_safety", AsyncMock(return_value=True))
    
    # Mock SkillService.get_by_id
    async def mock_get_by_id(self, skill_id):
        return {
            "skill_id": skill_id,
            "name": "Test Skill",
            "system_prompt": "You are a test skill.",
            "required_tools": [],
            "approval_required": False
        }
    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)
    
    # Mock A/B testing manager
    async def mock_get_routing_decision(skill_id):
        return skill_id
    async def mock_record_run_result(skill_id, success, tokens):
        pass
    monkeypatch.setattr(ab_manager, "get_routing_decision", mock_get_routing_decision)
    monkeypatch.setattr(ab_manager, "record_run_result", mock_record_run_result)
    
    # Mock persistence (no disk writes)
    monkeypatch.setattr(persistence, "save_dag_to_disk", lambda d: None)
    
    class MockChoiceMessage:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None
        def model_dump(self):
            return {"role": "assistant", "content": self.content}
            
    class MockChoice:
        def __init__(self, content):
            self.message = MockChoiceMessage(content)
            
    class MockUsage:
        def __init__(self):
            self.prompt_tokens = 10
            self.completion_tokens = 10
            self.total_tokens = 20
            
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]
            self.usage = MockUsage()
            
    async def mock_acompletion(*args, **kwargs):
        # Simulate short execution time
        await asyncio.sleep(0.01)
        return MockResponse('{"status": "completed", "result": "Success"}')
        
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)
    
    # Force Tier 1 (Small) routing to use GeneralistAgent for execution
    dag.routing_tier = "small"
    
    # 3. Execute the DAG
    engine = DAGEngine(skill_service=None)
    start_time = time.perf_counter()
    result_dag = await engine.execute(dag)
    duration = time.perf_counter() - start_time
    
    # 4. Assertions
    assert result_dag.status == "completed"
    for node in result_dag.nodes:
        assert node.color == NodeColor.GREEN
        assert node.result is not None
        
    print(f"Executed 100-node DAG in {duration:.4f}s")
    assert duration < 5.0


@pytest.mark.anyio
async def test_dag_cascading_rollback_concurrency_stress(monkeypatch):
    """Stress test cascading self-healing rollbacks with concurrent node execution and failures."""
    # Create a 25-node DAG: 5 layers, 5 nodes per layer
    num_layers = 5
    nodes_per_layer = 5
    nodes = []
    edges = []
    
    for layer in range(num_layers):
        for idx in range(nodes_per_layer):
            node_id = f"L{layer}N{idx}"
            deps = []
            if layer > 0:
                deps = [f"L{layer-1}N{i}" for i in range(nodes_per_layer)]
            nodes.append(DAGNode(
                node_id=node_id,
                name=f"Node {node_id}",
                skill_id="test_skill",
                dependencies=deps
            ))
            for dep in deps:
                edges.append(DAGEdge(from_node=dep, to_node=node_id))
                
    dag = DAGDefinition(
        dag_id="stress-rollback-25",
        name="25 Node Cascading Rollback Stress DAG",
        nodes=nodes,
        edges=edges
    )

    # Mock external dependencies
    from src.core.skill.service import SkillService
    from src.core.evolution.ab_manager import ab_manager
    from src.core.orchestrator import persistence
    from src.core.orchestrator.central_brain import central_brain
    import litellm
    from unittest.mock import AsyncMock

    monkeypatch.setattr(central_brain, "check_budget_safety", AsyncMock(return_value=True))
    
    async def mock_get_by_id(self, skill_id):
        return {
            "skill_id": skill_id,
            "name": "Test Skill",
            "system_prompt": "You are a test skill.",
            "required_tools": [],
            "approval_required": False
        }
    monkeypatch.setattr(SkillService, "get_by_id", mock_get_by_id)
    
    async def mock_get_routing_decision(skill_id):
        return skill_id
    monkeypatch.setattr(ab_manager, "get_routing_decision", mock_get_routing_decision)
    monkeypatch.setattr(persistence, "save_dag_to_disk", lambda d: None)

    # Mock GeneralistAgent.execute_node to fail for specific nodes
    from src.core.agent.generalist import GeneralistAgent
    async def mock_execute_node(self, *args, **kwargs):
        task_id = kwargs.get("task_id") or (args[0] if len(args) > 0 else "")
        # Fail Layer 1 nodes to trigger self-healing failures
        if "L1" in task_id or "heal-L1" in task_id:
            return {
                "status": "failed",
                "error": "Simulated compilation error",
                "trace": {}
            }
        return {
            "status": "completed",
            "result": "Success",
            "trace": {}
        }
    monkeypatch.setattr(GeneralistAgent, "execute_node", mock_execute_node)

    # Mock LiteLLM to return can_heal = false for L1 nodes (forcing rollback)
    class MockChoiceMessage:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None
        def model_dump(self):
            return {"role": "assistant", "content": self.content}
            
    class MockChoice:
        def __init__(self, content):
            self.message = MockChoiceMessage(content)
            
    class MockUsage:
        def __init__(self):
            self.prompt_tokens = 10
            self.completion_tokens = 10
            self.total_tokens = 20
            
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]
            self.usage = MockUsage()

    async def mock_acompletion(*args, **kwargs):
        prompt = kwargs.get("messages", [{}])[0].get("content", "")
        if "L1" in prompt:
            return MockResponse('{"can_heal": false}')
        return MockResponse('{"can_heal": true, "healing_step_name": "Install NumPy", "healing_step_description": "pip install numpy", "skill_id": "shell_exec", "arguments": {"command": "pip install numpy"}}')

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # Execute
    engine = DAGEngine(skill_service=None)
    dag.routing_tier = "small"
    result_dag = await engine.execute(dag)

    # Verify that the DAG status is paused/failed because L1 nodes failed and rolled back
    assert result_dag.status in ("paused", "failed")
    
    # Verify that no "heal-L1" nodes remain in the nodes list (they must be rolled back)
    heal_nodes = [n.node_id for n in result_dag.nodes if n.node_id.startswith("heal-")]
    assert len(heal_nodes) == 0

    # L1 nodes must be suspended and restored to their original dependencies
    for node in result_dag.nodes:
        if "L1" in node.node_id:
            assert node.color == NodeColor.SUSPENDED
            # original_dependencies of L1 is L0 nodes (e.g. L0N0 to L0N4)
            assert len(node.dependencies) == 5
            assert all(dep.startswith("L0") for dep in node.dependencies)


@pytest.mark.anyio
async def test_dag_budget_melting_circuit_breaker_stress(monkeypatch):
    """Stress test the Central Brain budget circuit breaker with a large DAG exceeding cost limits."""
    # Create a 100-node DAG
    nodes = [DAGNode(node_id=f"N{i}", name=f"Node {i}", skill_id="test_skill") for i in range(100)]
    dag = DAGDefinition(
        dag_id="stress-circuit-breaker-100",
        name="100 Node Circuit Breaker Stress DAG",
        nodes=nodes,
        edges=[]
    )
    
    from src.core.orchestrator.central_brain import central_brain
    from unittest.mock import AsyncMock
    # Mock budget check to return False (simulating budget safety breach)
    monkeypatch.setattr(central_brain, "check_budget_safety", AsyncMock(return_value=False))
    
    from src.core.skill.service import SkillService
    from src.core.orchestrator import persistence
    from unittest.mock import MagicMock
    
    mock_skill_service = MagicMock(spec=SkillService)
    monkeypatch.setattr(persistence, "save_dag_to_disk", lambda d: None)
    
    # Execute the DAG
    engine = DAGEngine(mock_skill_service)
    result_dag = await engine.execute(dag)
    
    # Assertions
    assert result_dag.status == "failed"
    # No nodes should have run (their color should remain GRAY)
    assert all(n.color == NodeColor.GRAY for n in result_dag.nodes)
