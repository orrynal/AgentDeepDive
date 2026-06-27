"""API routes for Phase 4 Self-evolution Flywheel."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
from src.evolution.evaluator import evaluator
from src.evolution.diagnostics import diagnostics_engine
from src.evolution.optimizer import skill_optimizer
from src.core.evolution.ab_manager import ab_manager
from src.database import async_session

router = APIRouter()


class EvolutionTaskRequest(BaseModel):
    task_id: str
    task_description: str
    skill_id: str
    trace_steps: list[dict[str, Any]]
    agent_output: str
    error_message: str | None = None
    max_tokens: int = 16000
    total_tokens: int = 2000
    fork_ab_variant: bool = True


@router.post("/evolution/evaluate", response_model=dict)
async def evaluate_and_optimize(body: EvolutionTaskRequest):
    """Evaluate an execution trace, diagnose any issues, and auto-patch the Skill if needed."""
    # 1. Run multi-judge evaluation
    eval_res = await evaluator.evaluate_trace(
        task_description=body.task_description,
        skill_name=body.skill_id,
        trace_steps=body.trace_steps,
        agent_output=body.agent_output
    )

    # 2. Run diagnostics if there's an error or if score is low (< 0.6)
    score = eval_res["score"]
    needs_optimization = score < 0.6 or body.error_message is not None

    diagnostic_res = None
    optimized = False
    variant_info = None

    if needs_optimization:
        diagnostic_res = diagnostics_engine.diagnose(
            trace_error=body.error_message,
            total_tokens=body.total_tokens,
            max_tokens=body.max_tokens,
            eval_result=eval_res
        )

        # 3. Trigger Skill Self-Optimizer
        if body.fork_ab_variant:
            # Generate optimized prompt without directly modifying production file on disk
            new_prompt = await skill_optimizer.generate_optimized_prompt(
                skill_id=body.skill_id,
                diagnostic=diagnostic_res
            )
            if new_prompt:
                async with async_session() as session:
                    variant = await ab_manager.fork_grey_skill(
                        parent_skill_id=body.skill_id,
                        new_prompt=new_prompt,
                        session=session
                    )
                    if variant:
                        optimized = True
                        variant_info = {
                            "variant_id": variant.get("skill_id"),
                            "version": variant.get("version")
                        }
        else:
            # Direct patch on disk mode
            optimized = await skill_optimizer.optimize_skill(
                skill_id=body.skill_id,
                diagnostic=diagnostic_res
            )

    return {
        "score": score,
        "evaluation": eval_res,
        "needs_optimization": needs_optimization,
        "diagnostics": diagnostic_res,
        "optimized": optimized,
        "variant": variant_info
    }
