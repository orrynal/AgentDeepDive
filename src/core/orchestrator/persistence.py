import json
import os
import glob
import structlog
from src.core.orchestrator.models import DAGDefinition

from src.core.redis_pool import get_redis_client

logger = structlog.get_logger()

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

def get_store_dir(tenant_id: str = DEFAULT_TENANT_ID) -> str:
    """Get the active workspace-specific DAG store directory partitioned by tenant."""
    from src.config import settings
    path = os.path.join(settings.resolved_workspace_path, ".dag_store", tenant_id)
    os.makedirs(path, exist_ok=True)
    return path

def _get_store_dir_safely(tenant_id: str) -> str:
    import inspect
    func = globals().get("get_store_dir")
    try:
        sig = inspect.signature(func)
        if len(sig.parameters) == 0:
            return func()
    except Exception:
        pass
    try:
        return func(tenant_id)
    except TypeError:
        return func()

def save_dag_to_redis(dag: DAGDefinition, tenant_id: str | None = None):
    """Save DAG details in a Redis queue/hash partitioned by tenant."""
    t_id = tenant_id or dag.tenant_id or DEFAULT_TENANT_ID
    try:
        r = get_redis_client()
        dag_json = dag.model_dump_json()
        # Persist DAG state in a hash
        r.hset(f"agentdeep:dags:state:{t_id}", dag.dag_id, dag_json)
        
        # Track active/paused/unfinished DAGs in the recovery set
        if dag.status in ("paused", "running") or not dag.is_complete():
            r.sadd(f"agentdeep:dags:paused_queue:{t_id}", dag.dag_id)
        else:
            r.srem(f"agentdeep:dags:paused_queue:{t_id}", dag.dag_id)
        logger.debug("DAG saved to Redis", dag_id=dag.dag_id, status=dag.status, tenant_id=t_id)
    except Exception as e:
        logger.error("Failed to save DAG to Redis", dag_id=dag.dag_id, error=str(e), tenant_id=t_id)

def load_dags_from_redis(tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, DAGDefinition]:
    """Load all stored DAG definitions and states from Redis for a tenant."""
    dags = {}
    try:
        r = get_redis_client()
        all_states = r.hgetall(f"agentdeep:dags:state:{tenant_id}")
        if all_states:
            for dag_id, dag_json in all_states.items():
                try:
                    data = json.loads(dag_json)
                    dag = DAGDefinition.model_validate(data)
                    dags[dag.dag_id] = dag
                except Exception as fe:
                    logger.error("Failed to parse DAG from Redis", dag_id=dag_id, error=str(fe), tenant_id=tenant_id)
            logger.info("Loaded DAGs from Redis", count=len(dags), tenant_id=tenant_id)
    except Exception as e:
        logger.error("Failed to load DAGs from Redis", error=str(e), tenant_id=tenant_id)
    return dags

import threading
from collections import OrderedDict

class TenantDAGCache:
    def __init__(self, capacity: int = 500):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        
    def get(self, key):
        with self.lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]
            
    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
                
    def items(self):
        with self.lock:
            return list(self.cache.items())

_global_dag_cache: dict[str, TenantDAGCache] = {}
_cache_lock = threading.Lock()

def get_tenant_cache(tenant_id: str) -> TenantDAGCache:
    with _cache_lock:
        if tenant_id not in _global_dag_cache:
            _global_dag_cache[tenant_id] = TenantDAGCache(capacity=500)
        return _global_dag_cache[tenant_id]


def save_dag_to_disk(dag: DAGDefinition, tenant_id: str | None = None):
    """Save a single DAG definition and state to disk, memory cache, and Redis."""
    t_id = tenant_id or dag.tenant_id or DEFAULT_TENANT_ID
    
    # Populate workspace metadata before saving
    from src.config import settings
    if not dag.workspace_path:
        dag.workspace_path = settings.resolved_workspace_path
    if not dag.project_name:
        dag.project_name = os.path.basename(settings.resolved_workspace_path) or settings.resolved_workspace_path

    try:
        store_dir = _get_store_dir_safely(t_id)
        file_path = os.path.join(store_dir, f"{dag.dag_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(dag.model_dump_json(indent=2))
        logger.debug("DAG saved to disk", dag_id=dag.dag_id, path=file_path, tenant_id=t_id)
    except Exception as e:
        logger.error("Failed to save DAG to disk", dag_id=dag.dag_id, error=str(e), tenant_id=t_id)
    
    # Update local memory cache
    cache = get_tenant_cache(t_id)
    cache.put(dag.dag_id, dag)
    
    # Also persist to Redis for Pod recovery
    save_dag_to_redis(dag, t_id)


def load_dags_from_disk(tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, DAGDefinition]:
    """Load all stored DAG definitions and states from disk and Redis recursively for a workspace, leveraging LRU caching."""
    dags = {}
    from src.config import settings
    workspace_path = settings.resolved_workspace_path
    
    target_subdir = os.path.join(".dag_store", tenant_id)
    cache = get_tenant_cache(tenant_id)
    
    if os.path.exists(workspace_path):
        try:
            for root, dirs, files in os.walk(workspace_path):
                if root.endswith(target_subdir):
                    # Deduce project path and project name
                    deduced_workspace = os.path.dirname(os.path.dirname(root))
                    project_name = os.path.basename(deduced_workspace) or deduced_workspace
                    
                    for file in files:
                        if file.endswith(".json"):
                            dag_id = file[:-5]
                            file_path = os.path.join(root, file)
                            
                            # Check LRU cache first
                            cached_dag = cache.get(dag_id)
                            if cached_dag:
                                dags[dag_id] = cached_dag
                            else:
                                try:
                                    with open(file_path, "r", encoding="utf-8") as f:
                                        data = json.load(f)
                                    dag = DAGDefinition.model_validate(data)
                                    if not dag.workspace_path:
                                        dag.workspace_path = deduced_workspace
                                    if not dag.project_name:
                                        dag.project_name = project_name
                                    cache.put(dag.dag_id, dag)
                                    dags[dag.dag_id] = dag
                                except Exception as fe:
                                    logger.error("Failed to load DAG file", file=file_path, error=str(fe), tenant_id=tenant_id)
            logger.info("Loaded DAGs from disk recursively (cache-assisted)", count=len(dags), path=workspace_path, tenant_id=tenant_id)
        except Exception as e:
            logger.error("Failed to load DAGs from disk recursively", error=str(e), tenant_id=tenant_id)
            
    # Load from Redis and merge/override only if they belong to this workspace
    try:
        redis_dags = load_dags_from_redis(tenant_id)
        for r_id, r_dag in redis_dags.items():
            on_disk = r_id in dags
            belongs_to_workspace = False
            if r_dag.workspace_path:
                try:
                    rel = os.path.relpath(r_dag.workspace_path, workspace_path)
                    belongs_to_workspace = not rel.startswith("..")
                except ValueError:
                    pass
            
            if on_disk or belongs_to_workspace:
                if on_disk:
                    r_dag.project_name = dags[r_id].project_name
                    r_dag.workspace_path = dags[r_id].workspace_path
                else:
                    if not r_dag.project_name:
                        r_dag.project_name = os.path.basename(r_dag.workspace_path) or r_dag.workspace_path
                cache.put(r_id, r_dag)
                dags[r_id] = r_dag
    except Exception as e:
        logger.error("Failed to merge Redis DAGs", error=str(e), tenant_id=tenant_id)
        
    return dags
