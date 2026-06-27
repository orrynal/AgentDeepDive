"""Generalist Agent implementation for Tier 1 Single-Agent execution."""

import os
from typing import Any
import structlog
from src.config import settings
from src.core.agent.executor import AgentExecutor

logger = structlog.get_logger()


class GeneralistAgent:
    """A unified Generalist Agent that can execute any DAG node sequentially in Tier 1."""

    def __init__(self, model: str | None = None):
        self.executor = AgentExecutor(model=model or settings.default_model)

    async def execute_node(
        self,
        task_id: str,
        node_instruction: str,
        parent_outputs: dict[str, Any],
        allowed_tools: list[str] | None = None,
        tenant_id: str = "00000000-0000-0000-0000-000000000000"
    ) -> dict[str, Any]:
        """Execute a single DAG node using the Generalist Agent.

        Args:
            task_id: The unique execution ID (e.g. "dag_run_id:node_id").
            node_instruction: The instruction describing this node's task.
            parent_outputs: A dictionary mapping parent node IDs to their output results.
            allowed_tools: Optional custom list of tool names this node is allowed to use. 
                           If None, the Generalist has access to all registered tools.
            tenant_id: Optional tenant ID for budget isolation.

        Returns:
            Execution result dict from AgentExecutor.
        """
        # 1. Assemble parent context dynamically
        context_parts = []
        if parent_outputs:
            context_parts.append("### Outputs from Predecessor Nodes (Parent Dependencies):")
            for parent_id, output in parent_outputs.items():
                context_parts.append(f"#### Node: {parent_id}")
                if isinstance(output, (dict, list)):
                    import json
                    output_str = json.dumps(output, indent=2, ensure_ascii=False)
                else:
                    output_str = str(output)
                context_parts.append(output_str)
        
        context = "\n".join(context_parts)

        # 2. Build virtual Generalist Skill definition
        # If no specific allowed tools are specified, grant access to all tools in the registry
        if not allowed_tools:
            from src.core.agent.tools import tool_registry
            allowed_tools = list(tool_registry._tools.keys())

        generalist_skill = {
            "skill_id": "generalist-node-runner",
            "name": "Generalist Node Execution",
            "description": "Unified worker for sequential execution of DAG nodes",
            "required_tools": allowed_tools,
            "risk_level": "medium",
            "system_prompt": self._get_generalist_system_prompt()
        }

        # 3. Build virtual Generalist Role definition to bypass constraints
        generalist_role = {
            "role_id": "generalist-general",
            "name": "Generalist Full-Stack Agent",
            "system_prompt_prefix": "You are a senior full-stack software engineer and system architect. You have full system permissions to design, implement, test, and debug code.",
            "allowed_skills": ["generalist-node-runner"],
            "max_token_budget": 50000
        }

        logger.info(
            "Generalist Agent executing node",
            task_id=task_id,
            allowed_tools_count=len(allowed_tools),
            has_parent_outputs=bool(parent_outputs),
            tenant_id=tenant_id
        )

        # 4. Delegate to the Executor
        res = await self.executor.execute(
            task_id=task_id,
            task_description=node_instruction,
            skill=generalist_skill,
            context=context,
            role=generalist_role,
            tenant_id=tenant_id
        )

        return res

    def _get_generalist_system_prompt(self) -> str:
        return (
            "You are the Generalist Agent of the AgentDeepDive multi-agent framework.\n"
            "Your task is to execute the current DAG node's instruction successfully.\n"
            "You have access to all tools including directory listing, file reading, writing, patching, running commands, and web searching.\n"
            "Use these tools strategically to complete your task.\n\n"
            "When executing:\n"
            "1. Read the outputs from predecessor nodes carefully to understand the context and design choices.\n"
            "2. If you write code, ensure it aligns perfectly with the architecture designed in previous nodes.\n"
            "3. If any command execution fails, diagnose the problem, modify the code, and re-run tests until it succeeds.\n"
            "4. Ensure your output is structured, clear, and contains all necessary details so that subsequent nodes can read and use it."
        )
