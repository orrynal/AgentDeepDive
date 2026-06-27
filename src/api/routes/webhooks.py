"""Webhook integration endpoints, optimized for n8n ecosystem connectivity."""

import httpx
import asyncio
import structlog
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.orchestrator.dag_engine import DAGEngine
from src.core.orchestrator.task_splitter import split_task
from src.core.skill.service import SkillService
from src.database import get_db, async_session
from src.config import settings

logger = structlog.get_logger()
router = APIRouter()

class N8NWebhookRequest(BaseModel):
    event: str = Field("jira_bug", description="Triggering event type (e.g. jira_bug, github_issue)")
    task_description: str = Field(..., description="Details of the task to perform")
    callback_url: str | None = Field(None, description="Optional custom callback URL to post results back to")

async def run_n8n_flow_in_background(
    task_description: str,
    callback_url: str | None
):
    """Decompose and execute the task as a DAG, then callback n8n with results."""
    logger.info("Starting n8n background flow execution", task_description=task_description)
    try:
        # 1. Decompose task into DAG
        dag = await split_task(task_description)
        logger.info("Successfully split task into DAG", dag_id=dag.dag_id, nodes=len(dag.nodes))
        
        # Store in DAG memory store for API queries
        from src.api.routes.dags import _dag_store
        _dag_store[dag.dag_id] = dag
        
        # 2. Execute DAG using a fresh DB session
        async with async_session() as session:
            skill_svc = SkillService(session)
            engine = DAGEngine(skill_svc)
            result_dag = await engine.execute(dag)
            await session.commit()
            
        # Update store with results
        _dag_store[dag.dag_id] = result_dag
        logger.info("DAG execution finished successfully for n8n flow", dag_id=dag.dag_id, status=result_dag.status)
        
        # 3. Post results back to callback url if defined
        target_callback = callback_url or settings.n8n_callback_url
        if target_callback:
            from src.core.governance.ssrf import is_safe_url
            if not is_safe_url(target_callback):
                logger.error("SSRF validation failed: Blocked callback URL from execution", url=target_callback)
            else:
                logger.info("Posting n8n execution callback", callback_url=target_callback, dag_id=dag.dag_id)
            
            # Format payload for n8n
            payload = {
                "dag_id": result_dag.dag_id,
                "name": result_dag.name,
                "status": result_dag.status,
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "name": n.name,
                        "skill_id": n.skill_id,
                        "color": n.color.value,
                        "error": n.error,
                        "result": n.result,
                        "completed_at": (
                            n.completed_at.isoformat()
                            if hasattr(n.completed_at, "isoformat")
                            else (str(n.completed_at) if n.completed_at else None)
                        )
                    }
                    for n in result_dag.nodes
                ]
            }
            
            async with httpx.AsyncClient() as client:
                resp = await client.post(target_callback, json=payload, timeout=30)
                logger.info("n8n callback response", status_code=resp.status_code)
        else:
            logger.info("No callback URL defined, finished execution in background", dag_id=dag.dag_id)
            
    except Exception as e:
        logger.error("Error running n8n background flow", error=str(e))
        target_callback = callback_url or settings.n8n_callback_url
        if target_callback:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(target_callback, json={
                        "status": "failed",
                        "error": str(e)
                    }, timeout=10)
            except Exception as callback_ex:
                logger.error("Failed to post failure callback", error=str(callback_ex))

@router.post("/webhooks/n8n", response_model=dict)
async def trigger_n8n_webhook(
    body: N8NWebhookRequest,
    background_tasks: BackgroundTasks
):
    """Receive task trigger from n8n, decompose it, and run in background."""
    if body.callback_url:
        from src.core.governance.ssrf import is_safe_url
        if not is_safe_url(body.callback_url):
            raise HTTPException(status_code=400, detail="Invalid callback_url: SSRF validation failed")
            
    background_tasks.add_task(run_n8n_flow_in_background, body.task_description, body.callback_url)
    
    return {
        "status": "accepted",
        "message": "Task received and queued for background DAG orchestration.",
        "task_description": body.task_description
    }
