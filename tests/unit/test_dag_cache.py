import pytest
from unittest.mock import patch, mock_open
from src.core.orchestrator.persistence import TenantDAGCache, get_tenant_cache, save_dag_to_disk, load_dags_from_disk
from src.core.orchestrator.models import DAGDefinition

def test_tenant_dag_cache_lru_eviction():
    # Create cache with capacity of 3
    cache = TenantDAGCache(capacity=3)
    
    dag1 = DAGDefinition(dag_id="dag-1", name="DAG 1", nodes=[])
    dag2 = DAGDefinition(dag_id="dag-2", name="DAG 2", nodes=[])
    dag3 = DAGDefinition(dag_id="dag-3", name="DAG 3", nodes=[])
    dag4 = DAGDefinition(dag_id="dag-4", name="DAG 4", nodes=[])
    
    cache.put(dag1.dag_id, dag1)
    cache.put(dag2.dag_id, dag2)
    cache.put(dag3.dag_id, dag3)
    
    assert cache.get("dag-1") is dag1
    
    # Adding 4th should evict dag-2 (since we accessed dag-1, dag-2 is now the least recently used!)
    cache.put(dag4.dag_id, dag4)
    
    assert cache.get("dag-2") is None
    assert cache.get("dag-1") is dag1
    assert cache.get("dag-3") is dag3
    assert cache.get("dag-4") is dag4

def test_persistence_cache_integration(monkeypatch):
    tenant_id = "test-tenant-cache-integration"
    cache = get_tenant_cache(tenant_id)
    cache.capacity = 2  # Set low capacity for testing
    
    # Clean cache
    cache.cache.clear()
    
    dag1 = DAGDefinition(dag_id="dag-c1", name="DAG C1", nodes=[], tenant_id=tenant_id)
    
    # Mock file operations and redis
    monkeypatch.setattr("src.core.orchestrator.persistence.save_dag_to_redis", lambda d, t: None)
    monkeypatch.setattr("src.core.orchestrator.persistence.load_dags_from_redis", lambda t: {})
    monkeypatch.setattr("os.path.exists", lambda path: True)
    monkeypatch.setattr("os.walk", lambda path: [("/workspace/.dag_store/test-tenant-cache-integration", [], ["dag-c1.json"])])
    
    with patch("builtins.open", mock_open()) as mock_file:
        save_dag_to_disk(dag1, tenant_id)
        
    # Verify it is in cache
    assert cache.get("dag-c1") is dag1
    
    # Load dags from disk should return the cached instance
    dags = load_dags_from_disk(tenant_id)
    assert dags.get("dag-c1") is dag1
