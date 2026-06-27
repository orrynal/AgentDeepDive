import os
import json
import pytest
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.orchestrator.persistence import save_dag_to_disk, load_dags_from_disk, get_store_dir
from src.core.redis_pool import get_redis_client

pytestmark = pytest.mark.integration

def test_redis_recovery_queue_survives_disk_wipe():
    # 1. Create a dummy paused DAG
    dag = DAGDefinition(
        dag_id="test-recovery-dag-123",
        name="Test Recovery DAG",
        status="paused",
        nodes=[
            DAGNode(node_id="node-1", name="Node 1", skill_id="dummy_skill")
        ]
    )
    
    # Ensure any previous state is cleared from Redis
    t_id = dag.tenant_id
    r = get_redis_client()
    r.hdel(f"agentdeep:dags:state:{t_id}", dag.dag_id)
    r.srem(f"agentdeep:dags:paused_queue:{t_id}", dag.dag_id)
    
    # 2. Save DAG (this saves to disk AND Redis)
    save_dag_to_disk(dag)
    
    # 3. Verify Redis has the state and is in the paused queue
    assert r.hexists(f"agentdeep:dags:state:{t_id}", dag.dag_id)
    assert r.sismember(f"agentdeep:dags:paused_queue:{t_id}", dag.dag_id)
    
    # Parse and verify content in Redis
    stored_json = r.hget(f"agentdeep:dags:state:{t_id}", dag.dag_id)
    stored_data = json.loads(stored_json)
    assert stored_data["name"] == "Test Recovery DAG"
    assert stored_data["status"] == "paused"
    
    # 4. Simulate Pod restart by wiping the disk (.dag_store JSON file)
    store_dir = get_store_dir(t_id)
    disk_file_path = os.path.join(store_dir, f"{dag.dag_id}.json")
    if os.path.exists(disk_file_path):
        os.remove(disk_file_path)
        
    # 5. Load DAGs from disk (which now falls back to Redis recovery queue)
    loaded_dags = load_dags_from_disk(t_id)
    
    # 6. Assert DAG was successfully recovered from Redis
    assert dag.dag_id in loaded_dags
    recovered_dag = loaded_dags[dag.dag_id]
    assert recovered_dag.name == "Test Recovery DAG"
    assert recovered_dag.status == "paused"
    
    # Clean up Redis
    r.hdel(f"agentdeep:dags:state:{t_id}", dag.dag_id)
    r.srem(f"agentdeep:dags:paused_queue:{t_id}", dag.dag_id)
