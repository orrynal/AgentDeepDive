"""Agent Executor — the core execution engine.

Receives a task + Skill definition, invokes an LLM with tool-calling,
executes tool calls in a loop, and returns structured results with full trace.
Integrates dynamic priority locking and token budgeting.
"""

from src.core.agent.executor_logic.trace import ExecutionTrace
from src.core.agent.executor_logic.utils import extract_critical_log_context
from src.core.agent.executor_logic.main import AgentExecutor

__all__ = ["ExecutionTrace", "extract_critical_log_context", "AgentExecutor"]
