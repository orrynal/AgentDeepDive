"""DAG orchestration API endpoints."""

import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.orchestrator.dag_engine import DAGEngine
from src.core.orchestrator.models import DAGDefinition, DAGEdge, DAGNode, NodeColor
from src.core.orchestrator.task_splitter import split_task
from src.core.skill.service import SkillService
from src.database import get_db
from src.core.auth.security import get_current_user, RoleRequired
from src.core.auth.models import UserModel
from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk

router = APIRouter()

active_tasks = {}

# Persistent DAG store dynamically loaded from active workspace (backward compatible wrapper)
class DAGStoreWrapper(dict):
    def items(self):
        return load_dags_from_disk().items()
    def get(self, key, default=None):
        return load_dags_from_disk().get(key, default)
    def values(self):
        return load_dags_from_disk().values()
    def keys(self):
        return load_dags_from_disk().keys()
    def __getitem__(self, key):
        return load_dags_from_disk()[key]
    def __setitem__(self, key, value):
        save_dag_to_disk(value)
    def __contains__(self, key):
        return key in load_dags_from_disk()
    def __len__(self):
        return len(load_dags_from_disk())
    def __iter__(self):
        return iter(load_dags_from_disk())

_dag_store = DAGStoreWrapper()


class DAGNodeInput(BaseModel):
    node_id: str = ""
    name: str
    skill_id: str
    description: str = ""
    dependencies: list[str] = []
    priority: int = 50

class DAGEdgeInput(BaseModel):
    from_node: str
    to_node: str

class DAGCreateRequest(BaseModel):
    dag_id: str | None = None
    name: str
    description: str = ""
    nodes: list[DAGNodeInput]
    edges: list[DAGEdgeInput] = []

class AutoSplitRequest(BaseModel):
    description: str = Field(..., description="Complex task to auto-decompose into DAG")

class DAGStatusResponse(BaseModel):
    dag_id: str
    name: str
    status: str
    nodes: list[dict]
    summary: dict


@router.post("/dags", response_model=dict)
async def create_dag(
    body: DAGCreateRequest,
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Create a DAG from an explicit node/edge definition."""
    nodes = [DAGNode(**n.model_dump()) for n in body.nodes]
    edges = [DAGEdge(**e.model_dump()) for e in body.edges]
    kwargs = {
        "tenant_id": user.tenant_id,
        "name": body.name,
        "description": body.description,
        "nodes": nodes,
        "edges": edges,
    }
    if body.dag_id:
        kwargs["dag_id"] = body.dag_id
    dag = DAGDefinition(**kwargs)
    save_dag_to_disk(dag, user.tenant_id)
    return {"dag_id": dag.dag_id, "nodes": len(nodes), "edges": len(edges), "status": dag.status}


@router.post("/dags/auto-split", response_model=dict)
async def auto_split_dag(
    body: AutoSplitRequest,
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Use LLM to automatically decompose a task into a DAG."""
    dag = await split_task(body.description)
    dag.tenant_id = user.tenant_id
    save_dag_to_disk(dag, user.tenant_id)
    return {
        "dag_id": dag.dag_id,
        "name": dag.name,
        "nodes": [{"node_id": n.node_id, "name": n.name, "skill_id": n.skill_id,
                    "dependencies": n.dependencies} for n in dag.nodes],
        "edges": [{"from": e.from_node, "to": e.to_node} for e in dag.edges],
        "status": dag.status,
    }


class DAGExecuteRequest(BaseModel):
    model: str | None = None


@router.post("/dags/{dag_id}/execute", response_model=dict)
async def execute_dag(
    dag_id: str,
    body: DAGExecuteRequest = DAGExecuteRequest(),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Execute a DAG — schedules and runs all nodes respecting dependencies."""
    dags_map = load_dags_from_disk(user.tenant_id)
    dag = dags_map.get(dag_id)
    if not dag:
        raise HTTPException(404, f"DAG '{dag_id}' not found")
    if dag.status == "running":
        raise HTTPException(409, "DAG is already running")

    # Set dag status to running immediately and save
    dag.status = "running"
    save_dag_to_disk(dag, user.tenant_id)

    from src.config import settings
    if settings.celery_enabled:
        from src.core.celery_tasks import execute_existing_dag_async
        # Dispatch task to Celery Queue asynchronously
        execute_existing_dag_async.delay(dag_id, user.tenant_id, body.model)
        return {"status": "running", "dag_id": dag_id, "mode": "celery"}

    async def run_in_background():
        from src.database import async_session
        from src.core.agent.pool import agent_bus
        async with async_session() as session:
            try:
                # SkillService should be tenant-scoped
                skill_svc = SkillService(session, tenant_id=user.tenant_id)
                engine = DAGEngine(skill_svc)
                result = await engine.execute(dag, model_override=body.model)
                save_dag_to_disk(result, user.tenant_id)
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task and getattr(current_task, "is_resuming", False):
                    pass
                else:
                    dag.status = "failed"
                    for node in dag.nodes:
                        if node.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                            node.color = NodeColor.RED
                            node.error = "Execution cancelled by user"
                    save_dag_to_disk(dag, user.tenant_id)
                    # Publish status to bus
                    try:
                        await agent_bus.publish(
                            topic="dag_updates",
                            sender_id="dag_engine",
                            payload={
                                "dag_id": dag.dag_id,
                                "node_id": None,
                                "color": None,
                                "dag_status": "failed",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        )
                    except Exception:
                        pass
            except Exception as e:
                import structlog
                logger = structlog.get_logger()
                logger.exception("DAG background execution failed", dag_id=dag.dag_id, error=str(e))
                dag.status = "failed"
                for node in dag.nodes:
                    if node.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                        node.color = NodeColor.RED
                        node.error = f"Execution failed: {str(e)}"
                save_dag_to_disk(dag, user.tenant_id)
                # Publish status to bus
                try:
                    await agent_bus.publish(
                        topic="dag_updates",
                        sender_id="dag_engine",
                        payload={
                            "dag_id": dag.dag_id,
                            "node_id": None,
                            "color": None,
                            "dag_status": "failed",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    )
                except Exception:
                    pass
            finally:
                active_tasks.pop(dag_id, None)

    task = asyncio.create_task(run_in_background())
    active_tasks[dag_id] = task

    return {"status": "running", "dag_id": dag_id, "mode": "local"}


@router.post("/dags/{dag_id}/cancel", response_model=dict)
async def cancel_dag(
    dag_id: str,
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Cancel a running DAG execution."""
    task = active_tasks.get(dag_id)
    if not task:
        # Fallback: check if the DAG in store is currently marked as running/paused/suspended, and reset it
        dags_map = load_dags_from_disk(user.tenant_id)
        dag = dags_map.get(dag_id)
        if dag and dag.status not in ("completed", "completed_with_errors", "failed"):
            dag.status = "failed"
            for node in dag.nodes:
                if node.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                    node.color = NodeColor.RED
                    node.error = "Execution cancelled by user"

            save_dag_to_disk(dag, user.tenant_id)
            
            # Publish status to bus
            from src.core.agent.pool import agent_bus
            try:
                await agent_bus.publish(
                    topic="dag_updates",
                    sender_id="dag_engine",
                    payload={
                        "dag_id": dag.dag_id,
                        "node_id": None,
                        "color": None,
                        "dag_status": "failed",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
            except Exception:
                pass
                
            return {"status": "cancelled", "dag_id": dag_id, "message": f"DAG status reset from {dag.status} to failed."}
        raise HTTPException(404, f"No active execution task found for DAG '{dag_id}'")
        
    task.cancel()
    return {"status": "cancelled", "dag_id": dag_id}



@router.get("/dags/{dag_id}", response_model=dict)
async def get_dag_status(
    dag_id: str,
    user: UserModel = Depends(get_current_user)
):
    """Get the current status of a DAG."""
    dags_map = load_dags_from_disk(user.tenant_id)
    dag = dags_map.get(dag_id)
    if not dag:
        raise HTTPException(404, f"DAG '{dag_id}' not found")
    return _build_status_response(dag)


@router.get("/dags", response_model=list[dict])
async def list_dags(
    user: UserModel = Depends(get_current_user)
):
    """List all DAGs."""
    dags_map = load_dags_from_disk(user.tenant_id)
    return [
        {
            "dag_id": d.dag_id,
            "name": d.name,
            "status": d.status,
            "nodes": len(d.nodes),
            "created_at": d.created_at,
            "project_name": d.project_name,
            "workspace_path": d.workspace_path,
            "node_details": [{"name": n.name, "status": n.color.value} for n in d.nodes]
        }
        for d in dags_map.values()
    ]


def _build_status_response(dag: DAGDefinition) -> dict:
    color_counts = {}
    for n in dag.nodes:
        c = n.color.value
        color_counts[c] = color_counts.get(c, 0) + 1

    return {
        "dag_id": dag.dag_id,
        "name": dag.name,
        "status": dag.status,
        "nodes": [
            {
                "node_id": n.node_id,
                "name": n.name,
                "skill_id": n.skill_id,
                "color": n.color.value,
                "dependencies": n.dependencies,
                "error": n.error,
                "has_result": n.result is not None,
                "started_at": n.started_at,
                "completed_at": n.completed_at,
            }
            for n in dag.nodes
        ],
        "summary": {
            "total_nodes": len(dag.nodes),
            "color_distribution": color_counts,
            "created_at": dag.created_at,
            "completed_at": dag.completed_at,
        },
    }


class NodeActionRequest(BaseModel):
    action: str  # retry, bypass, patch
    file_path: str | None = None
    content: str | None = None


@router.post("/dags/{dag_id}/nodes/{node_id}/action", response_model=dict)
async def node_action(
    dag_id: str,
    node_id: str,
    body: NodeActionRequest,
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Perform interactive breakpoint action (retry, bypass, or patch) on a suspended DAG node."""
    dags_map = load_dags_from_disk(user.tenant_id)
    dag = dags_map.get(dag_id)
    if not dag:
        raise HTTPException(404, f"DAG '{dag_id}' not found")
    
    node = dag.get_node(node_id)
    if not node:
        raise HTTPException(404, f"Node '{node_id}' not found in DAG")

    if body.action == "retry":
        node.color = NodeColor.GRAY
        node.error = None
    elif body.action == "bypass":
        node.color = NodeColor.GREEN
        node.error = None
        node.result = {"output": "Bypassed by user interactive intervention", "trace": {}}
    elif body.action == "patch":
        if not body.file_path or body.content is None:
            raise HTTPException(400, "file_path and content are required for patch action")
        
        # Apply patch to local file safely
        from src.config import settings
        from pathlib import Path
        workspace_path = Path(settings.resolved_workspace_path)
        target_path = Path(body.file_path)
        if not target_path.is_absolute():
            target_path = workspace_path / target_path
            
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(body.content, encoding="utf-8")
        except Exception as e:
            raise HTTPException(500, f"Failed to apply patch file: {e}")
            
        # After patch, automatically retry the node
        node.color = NodeColor.GRAY
        node.error = None
    else:
        raise HTTPException(400, f"Unsupported action: {body.action}")

    # Reset DAG status to running as it resumes
    dag.status = "running"
    save_dag_to_disk(dag, user.tenant_id)

    # Cancel any active running task for this DAG
    old_task = active_tasks.get(dag_id)
    if old_task and not old_task.done():
        old_task.is_resuming = True
        old_task.cancel()
        try:
            await old_task
        except (asyncio.CancelledError, Exception):
            pass

    from src.config import settings
    if settings.celery_enabled:
        from src.core.celery_tasks import execute_existing_dag_async
        # Dispatch task to Celery Queue asynchronously
        execute_existing_dag_async.delay(dag_id, user.tenant_id)
        return {"status": "resumed", "dag_id": dag_id, "node_id": node_id, "action": body.action, "mode": "celery"}

    # Trigger execution background task
    async def run_in_background():
        from src.database import async_session
        async with async_session() as session:
            try:
                skill_svc = SkillService(session, tenant_id=user.tenant_id)
                engine = DAGEngine(skill_svc)
                result = await engine.execute(dag)
                save_dag_to_disk(result, user.tenant_id)
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task and getattr(current_task, "is_resuming", False):
                    pass
                else:
                    dag.status = "failed"
                    for n in dag.nodes:
                        if n.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE, NodeColor.SUSPENDED]:
                            n.color = NodeColor.RED
                            n.error = "Execution cancelled by user"
                    save_dag_to_disk(dag, user.tenant_id)
            finally:
                active_tasks.pop(dag_id, None)

    task = asyncio.create_task(run_in_background())
    active_tasks[dag_id] = task

    return {"status": "resumed", "dag_id": dag_id, "node_id": node_id, "action": body.action, "mode": "local"}


async def restore_running_dags():
    """Scan all tenants in the workspace, identify dags in 'running' status, reset their interrupted nodes, and resume execution."""
    import os
    from src.config import settings
    from src.database import async_session
    import structlog
    
    logger = structlog.get_logger()
    
    workspace_path = settings.resolved_workspace_path
    store_root = os.path.join(workspace_path, ".dag_store")
    if not os.path.exists(store_root):
        logger.info("No DAG store found. Skipping DAG recovery.")
        return
        
    tenants = [d for d in os.listdir(store_root) if os.path.isdir(os.path.join(store_root, d))]
    
    recovered_count = 0
    for tenant_id in tenants:
        try:
            dags_map = load_dags_from_disk(tenant_id)
            for dag_id, dag in dags_map.items():
                if dag.status == "running":
                    logger.info("Found running DAG to restore on startup", dag_id=dag_id, tenant_id=tenant_id)
                    
                    # Reset interrupted nodes to GRAY to allow re-scheduling
                    for node in dag.nodes:
                        if node.color in (NodeColor.BLUE, NodeColor.YELLOW):
                            node.color = NodeColor.GRAY
                            node.error = None
                            
                    # Save the cleaned state back to disk
                    save_dag_to_disk(dag, tenant_id)
                    
                    # Re-launch in background
                    async def run_recovered_in_background(target_dag=dag, t_id=tenant_id):
                        async with async_session() as session:
                            try:
                                skill_svc = SkillService(session, tenant_id=t_id)
                                engine = DAGEngine(skill_svc)
                                result = await engine.execute(target_dag)
                                save_dag_to_disk(result, t_id)
                            except asyncio.CancelledError:
                                current_task = asyncio.current_task()
                                if current_task and getattr(current_task, "is_resuming", False):
                                    pass
                                else:
                                    target_dag.status = "failed"
                                    for n in target_dag.nodes:
                                        if n.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                                            n.color = NodeColor.RED
                                            n.error = "Execution cancelled by user"
                                    save_dag_to_disk(target_dag, t_id)
                            except Exception as e:
                                logger.exception("Recovered DAG background execution failed", dag_id=target_dag.dag_id, error=str(e))
                                target_dag.status = "failed"
                                for n in target_dag.nodes:
                                    if n.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                                        n.color = NodeColor.RED
                                        n.error = f"Execution failed: {str(e)}"
                                save_dag_to_disk(target_dag, t_id)
                            finally:
                                active_tasks.pop(target_dag.dag_id, None)

                    task = asyncio.create_task(run_recovered_in_background())
                    active_tasks[dag_id] = task
                    recovered_count += 1
        except Exception as err:
            logger.error("Failed to restore DAGs for tenant", tenant_id=tenant_id, error=str(err))
            
    if recovered_count > 0:
        logger.info("DAG recovery process finished", total_recovered=recovered_count)

