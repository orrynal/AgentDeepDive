"""Celery background tasks definition."""

import asyncio
import structlog
from src.core.celery_app import celery_app

logger = structlog.get_logger()

@celery_app.task(name="src.core.celery_tasks.execute_dag_task_async")
def execute_dag_task_async(task_description: str, task_id: str | None = None, force: bool = False):
    """Celery worker task that wrapper the async DAG execution under circuit breaker."""
    logger.info("Celery task received for scheduled run", task_id=task_id, description=task_description)
    
    # We must use asyncio.run to execute the async database & DAG operations in Celery prefork worker
    try:
        return asyncio.run(_execute_dag_task_coro(task_description, task_id, force))
    except Exception as e:
        logger.exception("Failed running Celery task coroutine", task_id=task_id, error=str(e))
        return "FAILED"

async def _execute_dag_task_coro(task_description: str, task_id: str | None = None, force: bool = False):
    from src.database import async_session
    from src.core.scheduler.models import ScheduledTaskModel
    import uuid
    from datetime import datetime, timezone
    
    # 1. Check resource circuit breaker
    from src.core.governance.circuit_breaker import resource_circuit_breaker
    allowed, reason = await resource_circuit_breaker.allow_execution(task_description, task_id, force=force)
    if not allowed:
        logger.warning("Celery task trigger BLOCKED by Circuit Breaker", task_id=task_id, reason=reason)
        if task_id:
            try:
                async with async_session() as session:
                    task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                    if task:
                        task.last_run_time = datetime.now(timezone.utc)
                        task.last_run_status = "BLOCKED"
                        await session.commit()
            except Exception as err:
                logger.warning("Failed to update schedule status to BLOCKED in Celery", task_id=task_id, error=str(err))
        return "BLOCKED"

    if task_id:
        try:
            async with async_session() as session:
                task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                if task:
                    task.last_run_time = datetime.now(timezone.utc)
                    task.last_run_status = "RUNNING"
                    await session.commit()
        except Exception as err:
            logger.warning("Failed to update schedule status to RUNNING in Celery", task_id=task_id, error=str(err))
            
    status = "SUCCESS"
    try:
        from src.core.orchestrator.dag_engine import DAGEngine
        from src.core.orchestrator.task_splitter import split_task
        from src.core.skill.service import SkillService
        
        # 2. Decompose task to DAG
        dag = await split_task(task_description)
        logger.info("Celery worker split scheduled task into DAG", dag_id=dag.dag_id, nodes=len(dag.nodes))
        
        # 3. Cache DAG in Celery worker process's store
        from src.api.routes.dags import _dag_store
        _dag_store[dag.dag_id] = dag
        
        # 4. Execute the DAG
        async with async_session() as session:
            skill_svc = SkillService(session)
            engine = DAGEngine(skill_svc)
            result_dag = await engine.execute(dag)
            await session.commit()
            
        _dag_store[dag.dag_id] = result_dag
        logger.info("Celery worker scheduled task finished execution", dag_id=dag.dag_id, status=result_dag.status)
        if result_dag.status == "FAILED":
            status = "FAILED"
            await resource_circuit_breaker.record_failure("DAG status is FAILED")
        else:
            await resource_circuit_breaker.record_success()
    except Exception as e:
        logger.error("Error executing Celery worker scheduled task", task_description=task_description, error=str(e))
        status = "FAILED"
        await resource_circuit_breaker.record_failure(str(e))
        
    if task_id:
        try:
            async with async_session() as session:
                task = await session.get(ScheduledTaskModel, uuid.UUID(task_id))
                if task:
                    task.last_run_status = status
                    await session.commit()
        except Exception as err:
            logger.warning("Failed to update schedule status with final result in Celery", task_id=task_id, error=str(err))
            
    return status


@celery_app.task(name="src.core.celery_tasks.execute_existing_dag_async")
def execute_existing_dag_async(dag_id: str, tenant_id: str | None = None, model_override: str | None = None):
    """Celery worker task that executes an existing DAG by its dag_id."""
    logger.info("Celery task received for existing DAG execution", dag_id=dag_id, tenant_id=tenant_id)
    try:
        return asyncio.run(_execute_existing_dag_coro(dag_id, tenant_id, model_override))
    except Exception as e:
        logger.exception("Failed running Celery existing DAG execution coroutine", dag_id=dag_id, error=str(e))
        return "FAILED"

async def _execute_existing_dag_coro(dag_id: str, tenant_id: str | None = None, model_override: str | None = None):
    from src.database import async_session
    from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk
    from src.core.orchestrator.dag_engine import DAGEngine
    from src.core.skill.service import SkillService
    from src.core.agent.pool import agent_bus
    from src.core.orchestrator.models import NodeColor
    from datetime import datetime, timezone
    
    dags_map = load_dags_from_disk(tenant_id)
    dag = dags_map.get(dag_id)
    if not dag:
        logger.error("DAG not found in Celery worker disk store", dag_id=dag_id, tenant_id=tenant_id)
        return "FAILED"
        
    try:
        async with async_session() as session:
            skill_svc = SkillService(session, tenant_id=tenant_id)
            engine = DAGEngine(skill_svc)
            result = await engine.execute(dag, model_override=model_override)
            save_dag_to_disk(result, tenant_id)
            return "SUCCESS"
    except asyncio.CancelledError:
        dag.status = "failed"
        for node in dag.nodes:
            if node.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                node.color = NodeColor.RED
                node.error = "Execution cancelled in Celery worker"
        save_dag_to_disk(dag, tenant_id)
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
        return "CANCELLED"
    except Exception as e:
        logger.exception("DAG execution failed in Celery worker", dag_id=dag.dag_id, error=str(e))
        dag.status = "failed"
        for node in dag.nodes:
            if node.color in [NodeColor.BLUE, NodeColor.YELLOW, NodeColor.ORANGE]:
                node.color = NodeColor.RED
                node.error = f"Execution failed in Celery: {str(e)}"
        save_dag_to_disk(dag, tenant_id)
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
        return "FAILED"
