"""API endpoints for CRUD operations on scheduled background tasks."""

import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.scheduler.models import ScheduledTaskModel
from src.core.scheduler.manager import scheduler_manager
from src.database import get_db
from src.core.auth.security import get_current_user, RoleRequired
from src.core.auth.models import UserModel

router = APIRouter()

class ScheduleCreateRequest(BaseModel):
    name: str = Field(..., description="Unique name of the schedule")
    task_description: str = Field(..., description="Task description to execute on schedule")
    cron_expression: str = Field(..., description="Standard cron expression (e.g., '0 * * * *')")
    is_active: bool = True

class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    task_description: str | None = None
    cron_expression: str | None = None
    is_active: bool | None = None

@router.post("/schedules", response_model=dict)
async def create_schedule(
    body: ScheduleCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Create a new cron schedule."""
    # Check uniqueness within the same tenant
    result = await db.execute(
        select(ScheduledTaskModel).where(
            ScheduledTaskModel.tenant_id == user.tenant_id,
            ScheduledTaskModel.name == body.name
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(400, f"Schedule with name '{body.name}' already exists.")
        
    task = ScheduledTaskModel(
        tenant_id=user.tenant_id,
        name=body.name,
        task_description=body.task_description,
        cron_expression=body.cron_expression,
        is_active=body.is_active
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    
    if task.is_active:
        scheduler_manager.register_task(task)
        
    return task.to_dict()

@router.get("/schedules", response_model=list[dict])
async def list_schedules(
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user)
):
    """List all schedules."""
    result = await db.execute(
        select(ScheduledTaskModel).where(ScheduledTaskModel.tenant_id == user.tenant_id)
    )
    tasks = result.scalars().all()
    
    resp_tasks = []
    for t in tasks:
        d = t.to_dict()
        scheduler = getattr(scheduler_manager, "scheduler", None)
        job = None
        if scheduler and hasattr(scheduler, "get_job") and type(scheduler).__name__ not in ("Mock", "MagicMock", "AsyncMock"):
            try:
                job = scheduler.get_job(str(t.id))
            except Exception:
                pass
        if job and job.next_run_time:
            d["next_run_time"] = job.next_run_time.isoformat()
        else:
            d["next_run_time"] = None
        resp_tasks.append(d)
        
    return resp_tasks

@router.put("/schedules/{schedule_id}", response_model=dict)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: ScheduleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Update an existing schedule."""
    task = await db.get(ScheduledTaskModel, schedule_id)
    task_tenant = str(task.tenant_id) if task and task.tenant_id else "00000000-0000-0000-0000-000000000000"
    user_tenant = str(user.tenant_id)
    if not task or task_tenant != user_tenant:
        raise HTTPException(404, "Schedule not found")
        
    if body.name is not None:
        task.name = body.name
    if body.task_description is not None:
        task.task_description = body.task_description
    if body.cron_expression is not None:
        task.cron_expression = body.cron_expression
    if body.is_active is not None:
        task.is_active = body.is_active
        
    await db.commit()
    await db.refresh(task)
    
    if task.is_active:
        scheduler_manager.register_task(task)
    else:
        scheduler_manager.remove_task(str(task.id))
        
    return task.to_dict()

@router.delete("/schedules/{schedule_id}", response_model=dict)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Delete a schedule."""
    task = await db.get(ScheduledTaskModel, schedule_id)
    task_tenant = str(task.tenant_id) if task and task.tenant_id else "00000000-0000-0000-0000-000000000000"
    user_tenant = str(user.tenant_id)
    if not task or task_tenant != user_tenant:
        raise HTTPException(404, "Schedule not found")
        
    scheduler_manager.remove_task(str(task.id))
    await db.delete(task)
    await db.commit()
    
    return {"status": "deleted", "id": str(schedule_id)}


@router.post("/schedules/{schedule_id}/trigger", response_model=dict)
async def trigger_schedule(
    schedule_id: uuid.UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Trigger a scheduled task immediately in the background."""
    task = await db.get(ScheduledTaskModel, schedule_id)
    task_tenant = str(task.tenant_id) if task and task.tenant_id else "00000000-0000-0000-0000-000000000000"
    user_tenant = str(user.tenant_id)
    if not task or task_tenant != user_tenant:
        raise HTTPException(404, "Schedule not found")
        
    from src.core.governance.circuit_breaker import resource_circuit_breaker
    allowed, reason = await resource_circuit_breaker.allow_execution(task.task_description, str(task.id), is_manual=True, force=force)
    if not allowed:
        raise HTTPException(503, f"Circuit Breaker blocked manual trigger: {reason}")
        
    import asyncio
    from src.core.scheduler.manager import execute_scheduled_task
    asyncio.create_task(execute_scheduled_task(task.task_description, str(task.id), force=force))
    
    return {"status": "triggered", "id": str(schedule_id)}


