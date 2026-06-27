"""Task submission and execution endpoints."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.agent.executor import AgentExecutor
from src.core.skill.router import SkillRouter
from src.database import get_db
from src.core.auth.security import get_current_user, RoleRequired
from src.core.auth.models import UserModel

router = APIRouter()


class TaskSubmit(BaseModel):
    """Schema for submitting a new task."""
    description: str = Field(..., description="Natural language task description")
    skill_id: str | None = Field(None, description="Explicit Skill ID (auto-routed if omitted)")
    model: str | None = Field(None, description="Override the LLM model for this task")
    context: str = Field("", description="Additional context to provide")


class TaskResult(BaseModel):
    """Schema for task execution results."""
    task_id: str
    status: str
    result: str | None = None
    error: str | None = None
    skill_used: str | None = None
    trace: dict | None = None


@router.post("/tasks/execute", response_model=TaskResult)
async def execute_task(
    body: TaskSubmit,
    session: AsyncSession = Depends(get_db),
    user: UserModel = Depends(RoleRequired(["admin", "developer"]))
):
    """Submit a task for immediate Agent execution.

    If skill_id is not specified, the system will auto-route to the best Skill.
    """
    task_id = f"task-{uuid4().hex[:12]}"

    # Step 1: Resolve Skill
    if body.skill_id:
        # Explicit skill specified
        from src.core.skill.service import SkillService
        svc = SkillService(session, tenant_id=user.tenant_id)
        skill = await svc.get_by_id(body.skill_id)
        if not skill:
            raise HTTPException(404, f"Skill '{body.skill_id}' not found")
    else:
        # Auto-route to best matching Skill
        from src.core.memory.rag_manager import rag_manager
        router = SkillRouter(
            session,
            embedder=rag_manager.embedder,
            milvus_client=rag_manager.client,
            tenant_id=user.tenant_id,
        )
        matches = await router.route(body.description, top_k=1)
        if not matches:
            raise HTTPException(
                404,
                "No matching Skill found for this task. "
                "Please register a Skill or specify skill_id explicitly.",
            )
        skill = matches[0]

    # Step 2: Execute with Agent
    executor = AgentExecutor(model=body.model)
    result = await executor.execute(
        task_id=task_id,
        task_description=body.description,
        skill=skill,
        context=body.context,
        tenant_id=user.tenant_id,
    )

    return TaskResult(
        task_id=task_id,
        status=result["status"],
        result=result.get("result"),
        error=result.get("error"),
        skill_used=skill.get("skill_id"),
        trace=result.get("trace"),
    )
