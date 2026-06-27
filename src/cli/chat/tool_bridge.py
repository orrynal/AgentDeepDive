"""Tool execution bridge with OPA guardrails and interactive approvals for AgentDeepDive CLI."""

import os
import json
import re
import asyncio
from typing import Any
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from src.config import settings
from src.core.agent.tools import tool_registry, current_task_id, current_agent_id
from src.core.governance.guardrails import guardrail_engine
from src.core.governance.audit import audit_logger
from src.core.concurrency.lock_manager import lock_manager

logger = structlog.get_logger()

class ToolBridge:
    """Bridges CLI Chat with system tools, safety policies, and local concurrency locks."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.acquired_locks = set()

    def get_tool_schemas(self) -> list[dict]:
        """Fetch LLM function-calling schemas for all registered tools."""
        return tool_registry.get_llm_schemas()

    def resolve_safe_paths(self, tool_name: str, arguments: dict):
        """Sanitize path arguments to keep them within the workspace."""
        path_keys = ["path", "target_path", "TargetFile"]
        workspace = settings.resolved_workspace_path
        
        for key in path_keys:
            if isinstance(arguments, dict) and key in arguments and isinstance(arguments[key], str):
                val = arguments[key]
                # Strip known prefixes
                for prefix in ["/home/user", "/workspace"]:
                    if val.startswith(prefix):
                        val = val[len(prefix):].lstrip("/")
                        break
                if val.startswith("~"):
                    val = val[len(prefix):].lstrip("~").lstrip("/")
                
                # Check absolute vs relative
                try:
                    abs_p = os.path.abspath(val)
                    common = os.path.commonpath([abs_p, workspace])
                    if common == workspace:
                        arguments[key] = abs_p
                        continue
                except Exception:
                    pass
                
                # Treat as relative to workspace
                rel_p = val
                if rel_p.startswith("/"):
                    rel_p = rel_p.lstrip("/")
                rel_p = re.sub(r'^[a-zA-Z]:[/\\]+', '', rel_p)
                arguments[key] = os.path.abspath(os.path.join(workspace, rel_p))

    async def execute_tool(self, tool_name: str, arguments: dict, session_id: str, tenant_id: str) -> str:
        """Evaluate guardrails, request permissions if needed, and execute a tool safely."""
        # 1. Resolve paths
        self.resolve_safe_paths(tool_name, arguments)
        
        # 2. Guardrails check
        risk_level = guardrail_engine.evaluate(tool_name, arguments, tenant_id=tenant_id, role="admin")
        
        # Log audit evaluation
        await audit_logger.log_event(
            event_type="cli_chat_guardrail_eval",
            task_id=session_id,
            agent_id="cli-chat-agent",
            details={
                "tool_name": tool_name,
                "arguments": arguments,
                "risk_level": risk_level
            },
            tenant_id=tenant_id
        )

        # 3. Handle L4 (Forbidden)
        if risk_level == "L4":
            err_msg = f"Security Violation: Tool '{tool_name}' blocked by L4 policy restriction."
            self.console.print(f"❌ [bold red]{err_msg}[/bold red]")
            return json.dumps({"status": "error", "error": err_msg})

        # 4. Handle L3 (Interactive HITL Approval)
        if risk_level == "L3":
            if settings.auto_approve_l3:
                logger.info("Auto-approval enabled (auto_approve_l3=True). Bypassing L3 approval.", tool=tool_name)
            else:
                self.console.print("\n[bold yellow]⚠️  Security Action Approval Required (L3)[/bold yellow]")
                arg_str = json.dumps(arguments, indent=2, ensure_ascii=False)
                self.console.print(Panel(
                    f"[bold]Tool:[/bold] {tool_name}\n"
                    f"[bold]Risk Level:[/bold] {risk_level} (Approval Required)\n"
                    f"[bold]Parameters:[/bold]\n{arg_str}",
                    title="Human-in-the-Loop Verification",
                    border_style="yellow"
                ))
                
                granted = Confirm.ask("Do you want to authorize this execution?", default=False)
                
                await audit_logger.log_event(
                    event_type="cli_chat_hitl_resolution",
                    task_id=session_id,
                    agent_id="cli-chat-agent",
                    details={
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "decision": "approved" if granted else "rejected"
                    },
                    tenant_id=tenant_id
                )

                if not granted:
                    err_msg = f"Permission denied: Tool '{tool_name}' execution declined by user."
                    self.console.print(f"❌ [bold red]{err_msg}[/bold red]")
                    return json.dumps({"status": "error", "error": err_msg})

        # 5. Acquire Concurrency Locks for write operations
        if tool_name in ("file_write", "file_patch"):
            file_path = arguments.get("path") or arguments.get("TargetFile") or arguments.get("target_path")
            if file_path:
                abs_path = os.path.abspath(file_path)
                if abs_path not in self.acquired_locks:
                    logger.info("Acquiring file lock for CLI write", file=abs_path)
                    lock_res = await lock_manager.acquire(
                        file_path=abs_path,
                        agent_id="cli-chat-agent",
                        task_id=session_id,
                        priority=100  # High priority for direct developer CLI interaction
                    )
                    if not lock_res.granted:
                        err_msg = f"Lock conflict: File '{abs_path}' is busy. Holder: {lock_res.holder_agent}"
                        self.console.print(f"❌ [bold red]{err_msg}[/bold red]")
                        return json.dumps({"status": "error", "error": err_msg})
                    self.acquired_locks.add(abs_path)

        # 6. Execute the tool
        tool = tool_registry.get(tool_name)
        if not tool:
            err_msg = f"Unknown tool: '{tool_name}'"
            return json.dumps({"status": "error", "error": err_msg})

        task_token = current_task_id.set(session_id)
        agent_token = current_agent_id.set("cli-chat-agent")
        try:
            res = await tool.execute(**arguments)
            return json.dumps(res, ensure_ascii=False)
        except Exception as e:
            logger.error("Error executing tool in CLI bridge", tool=tool_name, error=str(e))
            return json.dumps({"status": "error", "error": str(e)})
        finally:
            current_task_id.reset(task_token)
            current_agent_id.reset(agent_token)

    async def release_all_locks(self):
        """Release all locks acquired during the session."""
        for path in list(self.acquired_locks):
            try:
                await lock_manager.release(path, "cli-chat-agent")
            except Exception:
                pass
        self.acquired_locks.clear()
