from datetime import datetime, timezone
from uuid import uuid4

class ExecutionTrace:
    """Records every step of an Agent's execution for observability."""

    def __init__(self, task_id: str, agent_id: str):
        self.trace_id = f"tr-{uuid4().hex[:12]}"
        self.task_id = task_id
        self.agent_id = agent_id
        self.steps: list[dict] = []
        self.total_tokens_input = 0
        self.total_tokens_output = 0
        self.model_used = ""
        self.started_at = datetime.now(timezone.utc)

    def add_step(
        self,
        action: str,
        input_summary: str,
        output_summary: str,
        reasoning: str = "",
        error: str = "",
        duration_ms: int = 0,
        tokens: int = 0,
    ):
        self.steps.append({
            "step": len(self.steps) + 1,
            "action": action,
            "input_summary": input_summary[:500],
            "output_summary": output_summary[:1000],
            "reasoning": reasoning[:500],
            "error": error,
            "duration_ms": duration_ms,
            "tokens_used": tokens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "model_used": self.model_used,
            "steps": self.steps,
            "total_tokens_input": self.total_tokens_input,
            "total_tokens_output": self.total_tokens_output,
            "started_at": self.started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_sec": (datetime.now(timezone.utc) - self.started_at).total_seconds(),
        }
