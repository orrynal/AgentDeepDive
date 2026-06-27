"""Failure Diagnostics Engine to identify root causes of Agent errors.

Categorizes failures into BAD_ROUTING, TOKEN_EXCEEDED, TOOL_ERROR, JSON_SCHEMA_VIOLATION, and LLM_QUALITY_FAILURE.
"""

from typing import Any
import structlog

logger = structlog.get_logger()


class DiagnosticsEngine:
    """Diagnoses root causes of failed or low-quality Agent executions."""

    def diagnose(
        self,
        trace_error: str | None,
        total_tokens: int,
        max_tokens: int,
        eval_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Diagnose failure and return failure category and recommendations."""
        category = "UNKNOWN"
        reason = "No distinct error signature detected."
        recommendation = "Review execution logs manually."

        # 1. Token Budget Exceeded
        if total_tokens >= max_tokens or (trace_error and "token budget" in trace_error.lower()):
            category = "TOKEN_EXCEEDED"
            reason = f"Execution hit token limit ({total_tokens} >= {max_tokens})."
            recommendation = "Increase the context/token budget or utilize a more concise system prompt."

        # 2. Tool Execution Error
        elif trace_error and ("tool" in trace_error.lower() or "lock" in trace_error.lower() or "permission" in trace_error.lower()):
            category = "TOOL_ERROR"
            reason = f"A tool execution failed: {trace_error}"
            recommendation = "Verify tool arguments, file permissions, and directory locations."

        # 3. JSON Schema Violation
        elif eval_result and not eval_result.get("json_valid") and eval_result.get("rule_score", 1.0) < 1.0:
            category = "JSON_SCHEMA_VIOLATION"
            reason = "The output was expected to be structured JSON but failed parsing."
            recommendation = "Inject structure formatting rules into the prompt or set response_format in completion."

        # 4. LLM Quality Failure (low score)
        elif eval_result and eval_result.get("score", 1.0) < 0.6:
            category = "LLM_QUALITY_FAILURE"
            reason = f"Judges returned low consensus score: {eval_result.get('score')}"
            recommendation = "The prompt wording might be ambiguous. Clarify instructions and requirements in the Skill definition."

        # 5. Bad Routing (Default fallback when skill matched but task completely failed to progress)
        elif trace_error and "skill" in trace_error.lower():
            category = "BAD_ROUTING"
            reason = f"Agent failed to locate or initialize the correct skill: {trace_error}"
            recommendation = "Refine the trigger patterns or tags of the target Skill YAML."

        return {
            "failure_category": category,
            "reason": reason,
            "recommendation": recommendation,
        }


# Global Singleton
diagnostics_engine = DiagnosticsEngine()
