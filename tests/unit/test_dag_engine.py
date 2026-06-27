import os
import tempfile
import pytest
from src.core.orchestrator.models import DAGDefinition, DAGNode, DAGEdge, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.orchestrator import persistence

def test_dag_cycle_validation():
    # Create engine with None for SkillService as we won't execute nodes
    engine = DAGEngine(skill_service=None)

    # 1. Valid DAG (A -> B -> C)
    node_a = DAGNode(node_id="A", name="Node A", skill_id="test")
    node_b = DAGNode(node_id="B", name="Node B", skill_id="test", dependencies=["A"])
    node_c = DAGNode(node_id="C", name="Node C", skill_id="test", dependencies=["B"])
    
    dag_valid = DAGDefinition(
        name="Valid DAG",
        nodes=[node_a, node_b, node_c],
        edges=[
            DAGEdge(from_node="A", to_node="B"),
            DAGEdge(from_node="B", to_node="C")
        ]
    )
    assert engine._validate_no_cycles(dag_valid) is True

    # 2. Cycle in DAG (A -> B -> C -> A)
    node_a_cyc = DAGNode(node_id="A", name="Node A", skill_id="test", dependencies=["C"])
    node_b_cyc = DAGNode(node_id="B", name="Node B", skill_id="test", dependencies=["A"])
    node_c_cyc = DAGNode(node_id="C", name="Node C", skill_id="test", dependencies=["B"])
    
    dag_cycle = DAGDefinition(
        name="Cyclic DAG",
        nodes=[node_a_cyc, node_b_cyc, node_c_cyc],
        edges=[
            DAGEdge(from_node="A", to_node="B"),
            DAGEdge(from_node="B", to_node="C"),
            DAGEdge(from_node="C", to_node="A")
        ]
    )
    assert engine._validate_no_cycles(dag_cycle) is False

def test_node_color_transitions():
    # NodeColor state transitions
    assert NodeColor.BLUE in NodeColor.GRAY.can_transition_to
    assert NodeColor.YELLOW in NodeColor.BLUE.can_transition_to
    assert NodeColor.GREEN in NodeColor.YELLOW.can_transition_to
    assert NodeColor.RED in NodeColor.YELLOW.can_transition_to
    assert NodeColor.ORANGE in NodeColor.YELLOW.can_transition_to
    
    # GREEN is a terminal state
    assert len(NodeColor.GREEN.can_transition_to) == 0

def test_dag_persistence(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock get_store_dir to return our temporary directory
        monkeypatch.setattr(persistence, "get_store_dir", lambda: tmpdir)

        # Create a mock DAG
        node_a = DAGNode(node_id="A", name="Node A", skill_id="test")
        dag = DAGDefinition(
            dag_id="test-dag-123",
            name="Persistence Test DAG",
            nodes=[node_a]
        )

        # Save to disk
        persistence.save_dag_to_disk(dag)

        # Verify file exists
        expected_file = os.path.join(tmpdir, "test-dag-123.json")
        assert os.path.exists(expected_file)

        # Load from disk
        loaded_dags = persistence.load_dags_from_disk()
        assert "test-dag-123" in loaded_dags
        assert loaded_dags["test-dag-123"].name == "Persistence Test DAG"
        assert loaded_dags["test-dag-123"].nodes[0].node_id == "A"


def test_dag_node_result_coercion():
    # 1. Dictionary result should remain unchanged
    node_dict = DAGNode(node_id="A", name="Node A", result={"output": "Done", "trace": {}})
    assert node_dict.result == {"output": "Done", "trace": {}}

    # 2. String result should be coerced to dict with "output" key
    node_str = DAGNode(node_id="B", name="Node B", result="Coverage: 88%")
    assert node_str.result == {"output": "Coverage: 88%"}


@pytest.mark.asyncio
async def test_dag_restore_running_dags(monkeypatch):
    import json
    import asyncio
    from src.api.routes.dags import restore_running_dags
    from src.config import settings
    
    class MockSession:
        async def commit(self):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass
            
    monkeypatch.setattr("src.database.async_session", lambda: MockSession())
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        store_dir = os.path.join(tmpdir, ".dag_store", tenant_id)
        os.makedirs(store_dir, exist_ok=True)
        
        # Mock settings and persistence store paths
        monkeypatch.setattr(settings, "project_workspace_path", tmpdir)
        monkeypatch.setattr(persistence, "get_store_dir", lambda t_id=None: os.path.join(tmpdir, ".dag_store", t_id or tenant_id))
        monkeypatch.setattr(persistence, "_get_store_dir_safely", lambda t_id: os.path.join(tmpdir, ".dag_store", t_id))
        
        # Mock load_dags_from_disk and save_dag_to_disk inside persistence and dags route module
        def mock_save_dag(dag, t_id=None):
            t = t_id or dag.tenant_id or tenant_id
            target_dir = os.path.join(tmpdir, ".dag_store", t)
            os.makedirs(target_dir, exist_ok=True)
            fpath = os.path.join(target_dir, f"{dag.dag_id}.json")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(dag.model_dump_json(indent=2))
                
        from src.api.routes import dags
        monkeypatch.setattr(persistence, "save_dag_to_disk", mock_save_dag)
        monkeypatch.setattr(dags, "save_dag_to_disk", mock_save_dag)
        
        def mock_load_dags(t_id=tenant_id):
            res = {}
            path = os.path.join(tmpdir, ".dag_store", t_id)
            if os.path.exists(path):
                for f in os.listdir(path):
                    if f.endswith(".json"):
                        with open(os.path.join(path, f), "r") as file:
                            data = json.load(file)
                        dag = DAGDefinition.model_validate(data)
                        res[dag.dag_id] = dag
            return res
        monkeypatch.setattr(persistence, "load_dags_from_disk", mock_load_dags)
        monkeypatch.setattr(dags, "load_dags_from_disk", mock_load_dags)

        # Mock Redis calls to bypass during test
        monkeypatch.setattr(persistence, "save_dag_to_redis", lambda dag, t_id=None: None)

        # Mock execute call on DAGEngine so it returns immediately
        class DummyEngine:
            def __init__(self, *args, **kwargs):
                pass
            async def execute(self, dag, *args, **kwargs):
                # Verify node BLUE and YELLOW have been reset to GRAY before execution
                for n in dag.nodes:
                    if n.node_id in ("n2", "n3"):
                        assert n.color == NodeColor.GRAY
                dag.status = "completed"
                return dag
        from src.api.routes import dags
        monkeypatch.setattr(dags, "DAGEngine", DummyEngine)

        # Create running DAG with interrupted nodes
        node_1 = DAGNode(node_id="n1", name="n1", skill_id="t", color=NodeColor.GREEN)
        node_2 = DAGNode(node_id="n2", name="n2", skill_id="t", color=NodeColor.BLUE) # Interrupted!
        node_3 = DAGNode(node_id="n3", name="n3", skill_id="t", color=NodeColor.YELLOW) # Interrupted!
        node_4 = DAGNode(node_id="n4", name="n4", skill_id="t", color=NodeColor.ORANGE, approval_id="ap-1") # Approval, keep!
        
        dag = DAGDefinition(
            dag_id="running-dag-999",
            tenant_id=tenant_id,
            name="Recoverable Running DAG",
            status="running",
            nodes=[node_1, node_2, node_3, node_4]
        )
        
        # Save to our mock store
        mock_save_dag(dag, tenant_id)
        
        # Run restore process
        await restore_running_dags()
        
        # Let task run to completion
        await asyncio.sleep(0.1)
        
        # Verify node states are cleaned
        loaded_dags = mock_load_dags(tenant_id)
        recovered_dag = loaded_dags["running-dag-999"]
        
        assert recovered_dag.status == "completed"

