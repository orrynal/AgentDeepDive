import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import litellm
import structlog

from src.config import settings
from src.core.agent.pool import agent_bus, agent_pool
from src.core.agent.tools import Tool, tool_registry
from src.core.budget.manager import budget_manager
from src.core.concurrency.lock_manager import lock_manager
from src.core.concurrency.priority import calculate_priority
from src.core.governance.guardrails import guardrail_engine
from src.core.governance.approval import approval_manager
from src.core.governance.audit import audit_logger

from src.core.agent.executor_logic.trace import ExecutionTrace
from src.core.agent.executor_logic.utils import extract_critical_log_context

logger = structlog.get_logger()

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


class AgentExecutor:
    """Executes a single task using an LLM with tool-calling capabilities."""

    MAX_ITERATIONS = 15  # Safety limit on tool-call loops

    def __init__(self, model: str | None = None):
        self.model = model or settings.default_model
        self.agent_id = f"agent-{uuid4().hex[:8]}"
        self.priority = 50
        self.acquired_locks: set[str] = set()
        self.tenant_id = "00000000-0000-0000-0000-000000000000"

    async def execute(
        self,
        task_id: str,
        task_description: str,
        skill: dict,
        context: str = "",
        role: dict | None = None,
        tenant_id: str = "00000000-0000-0000-0000-000000000000",
    ) -> dict[str, Any]:
        """Execute a task with the given Skill definition.

        Args:
            task_id: Unique task identifier
            task_description: What the user wants done
            skill: Full Skill definition dict
            context: Additional context (loaded progressively)
            role: Optional Role definition dict
            tenant_id: Optional tenant identifier for budget isolation

        Returns:
            Dict with 'status', 'result', 'trace' keys
        """
        from src.core.telemetry import get_tracer
        from opentelemetry import trace as otel_trace

        tracer = get_tracer()
        with tracer.start_as_current_span("AgentExecutor.execute") as span:
            span.set_attribute("task_id", task_id)
            span.set_attribute("agent_id", self.agent_id)
            span.set_attribute("skill_id", skill.get("skill_id", "unknown"))
            span.set_attribute("tenant_id", tenant_id)
            self.tenant_id = tenant_id
            if role:
                span.set_attribute("role_id", role.get("role_id", "unknown"))

            trace = ExecutionTrace(task_id, self.agent_id)
            trace.model_used = self.model

            # 1. Role Skill Permission Check
            if role and skill.get("skill_id") not in role.get("allowed_skills", []):
                logger.error("Role authorization failed", role_id=role.get("role_id"), skill_id=skill.get("skill_id"))
                span.set_status(otel_trace.StatusCode.ERROR, "Role authorization failed")
                return {
                    "status": "failed",
                    "error": f"Security Alert: Role '{role.get('name')}' is not authorized to execute Skill '{skill.get('skill_id')}'",
                    "trace": trace.to_dict(),
                }

            # Determine task type from skill tags
            tags = skill.get("tags", [])
            task_type = "default"
            for t in ["analysis", "refactor", "bug_fix", "documentation", "formatting", "test_generation"]:
                if t in tags:
                    task_type = t
                    break
            span.set_attribute("task_type", task_type)

            # Dynamic priority calculation
            risk_map = {"low": 1, "medium": 3, "high": 5}
            severity = risk_map.get(skill.get("risk_level", "low"), 1)
            self.priority = calculate_priority(
                task_type=task_type,
                severity=severity,
                wait_start=time.time(),
                target_module="default",
            )
            span.set_attribute("priority", self.priority)

            # Budget Check & Model Routing
            budget_approval = await budget_manager.request_budget(task_type, tenant_id=tenant_id)
            if not budget_approval.approved:
                logger.error("Budget request rejected", task_id=task_id, reason=budget_approval.reason)
                span.set_status(otel_trace.StatusCode.ERROR, f"Budget rejected: {budget_approval.reason}")
                return {
                    "status": "failed",
                    "error": f"Rejected by Budget Manager: {budget_approval.reason}. {budget_approval.suggestion}",
                    "trace": trace.to_dict(),
                }

            # Override model based on role preference or budget manager recommendation
            if role and role.get("default_model"):
                self.model = role["default_model"]
            else:
                self.model = budget_approval.model
            trace.model_used = self.model
            span.set_attribute("model", self.model)

            # Token limit resolution
            max_tokens = budget_approval.max_tokens
            if role and role.get("max_token_budget"):
                max_tokens = min(max_tokens, role["max_token_budget"])

            # Build system prompt from Skill + Role definitions
            system_prompt = self._build_system_prompt(skill, context, role)

            # Get tools for this Skill
            required_tools = skill.get("required_tools", [])
            tools_schema = tool_registry.get_llm_schemas(required_tools) if required_tools else []
            available_tools = tool_registry.get_tools_for_skill(required_tools)
            tool_map = {t.name: t for t in available_tools}

            # Initial messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task_description},
            ]

            logger.info(
                "Agent execution started with budget/priority",
                agent_id=self.agent_id,
                task_id=task_id,
                skill=skill.get("skill_id"),
                model=self.model,
                priority=self.priority,
                max_tokens=max_tokens,
            )

            # Acquire slot from Agent Pool before execution
            await agent_pool.acquire_slot(self.agent_id, task_id)
            await agent_pool.register_active_task(self.agent_id, asyncio.current_task())

            async def heartbeat_loop(agent_id: str):
                import time
                from src.core.agent.pool import agent_bus
                r = await agent_bus._get_redis()
                key = f"agentdeep:heartbeat:{agent_id}"
                try:
                    while True:
                        await r.set(key, str(time.time()), ex=8)
                        await asyncio.sleep(3)
                except asyncio.CancelledError:
                    try:
                        await r.delete(key)
                    except Exception:
                        pass
                    raise

            heartbeat_task = asyncio.create_task(heartbeat_loop(self.agent_id))

            try:
                result = await self._run_loop(messages, tools_schema, tool_map, trace, task_id, max_tokens)
                
                # Coder-Reviewer Loop: If it's a code generation task, run reviewer critic loop
                is_code_generation = skill.get("skill_id", "").startswith("code-generator")
                is_sub_review = "-review-" in task_id
                
                if is_code_generation and not is_sub_review:
                    logger.info("Entering Coder-Reviewer Loop for code generation task")
                    for iteration in range(2):
                        try:
                            from src.core.skill.service import SkillService
                            from src.database import async_session
                            
                            # Load reviewer skill
                            async with async_session() as session:
                                skill_svc = SkillService(session)
                                reviewer_skill = await skill_svc.get_by_id("code-reviewer-v1")
                                
                            if reviewer_skill:
                                logger.info(f"Running Coder-Reviewer Loop iteration {iteration + 1}")
                                reviewer_executor = AgentExecutor(
                                    model=settings.default_model  # High reasoning
                                )
                                reviewer_executor.priority = self.priority
                                
                                review_task = (
                                    f"Review the generated code for task: '{task_description}'.\n"
                                    f"Analyze the written files for bugs, code style, and potential runtime errors.\n"
                                    f"Output '[APPROVED]' if it is complete and correct, or '[REJECTED]' with details on what to fix."
                                )
                                
                                review_res = await reviewer_executor.execute(
                                    task_id=f"{task_id}-review-{iteration}",
                                    task_description=review_task,
                                    skill=reviewer_skill
                                )
                                
                                review_text = review_res.get("result", "")
                                if "[APPROVED]" in review_text:
                                    logger.info("Code generation approved by reviewer agent")
                                    break
                                else:
                                    logger.info("Code generation rejected by reviewer, starting refinement", feedback=review_text[:200])
                                    # Feed review findings back to coder messages
                                    messages.append({
                                        "role": "user",
                                        "content": f"The code review rejected the implementation. Feedback:\n{review_text}\n\nPlease refine the code and fix the reported issues."
                                    })
                                    # Re-run coder loop
                                    result = await self._run_loop(messages, tools_schema, tool_map, trace, task_id, max_tokens)
                            else:
                                logger.warning("code-reviewer-v1 skill not found, skipping critic loop")
                                break
                        except Exception as loop_ex:
                            logger.error("Error in Coder-Reviewer loop iteration", error=str(loop_ex))
                            break
                
                # Save task execution experience to episodic memory if it was a bug fix, refactor, or had errors
                errors_list = [step.get("error") for step in trace.steps if step.get("error")]
                if task_type in ["bug_fix", "refactor"] or errors_list:
                    try:
                        from src.core.memory.rag_manager import rag_manager
                        error_stack = "\n".join(errors_list)
                        rag_manager.save_episodic_memory(
                            task_id=task_id,
                            prompt=task_description,
                            error_stack=error_stack,
                            patch=result if len(result) < 5000 else "Result summary: success"
                        )
                    except Exception as mem_ex:
                        logger.error("Failed to save episodic memory on completion", error=str(mem_ex))

                span.set_status(otel_trace.StatusCode.OK)
                return {
                    "status": "completed",
                    "result": result,
                    "trace": trace.to_dict(),
                }
            except asyncio.CancelledError:
                logger.warning("Agent execution was cancelled", task_id=task_id)
                trace.add_step("error", "", "", error="Execution cancelled")
                span.set_status(otel_trace.StatusCode.ERROR, "Execution cancelled")
                return {
                    "status": "failed",
                    "error": "Execution cancelled",
                    "trace": trace.to_dict(),
                }
            except Exception as e:
                logger.error("Agent execution failed", error=str(e), task_id=task_id)
                trace.add_step("error", "", "", error=str(e))
                span.record_exception(e)
                span.set_status(otel_trace.StatusCode.ERROR, str(e))
                return {
                    "status": "failed",
                    "error": str(e),
                    "trace": trace.to_dict(),
                }
            finally:
                if 'heartbeat_task' in locals() and heartbeat_task:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                # Release slot in Agent Pool
                await agent_pool.release_slot(self.agent_id)

                # Release all acquired locks
                for path in list(self.acquired_locks):
                    try:
                        await lock_manager.release(path, self.agent_id)
                    except Exception as ex:
                        logger.error("Failed to release lock on cleanup", path=path, error=str(ex))
                self.acquired_locks.clear()

                # Record final budget usage
                await budget_manager.record_usage(
                    model=self.model,
                    task_type=task_type,
                    tokens_in=trace.total_tokens_input,
                    tokens_out=trace.total_tokens_output,
                    tenant_id=tenant_id,
                )
                
                if role:
                    try:
                        r = await agent_bus._get_redis()
                        key = f"agentdeep:spent_tokens:{tenant_id}:{role.get('role_id')}"
                        total_tokens = trace.total_tokens_input + trace.total_tokens_output
                        await r.incrby(key, total_tokens)
                        logger.info("Recorded role token usage in Redis", role_id=role.get('role_id'), added_tokens=total_tokens, tenant_id=tenant_id)
                    except Exception as redis_err:
                        logger.error("Failed to record role token usage in Redis", error=str(redis_err))

    async def _run_loop(
        self,
        messages: list[dict],
        tools_schema: list[dict],
        tool_map: dict[str, Tool],
        trace: ExecutionTrace,
        task_id: str,
        max_tokens: int,
    ) -> str:
        """Main execution loop: LLM reasoning → tool calls → repeat until done."""
        dag_id, node_id = None, task_id
        if ":" in task_id:
            dag_id, node_id = task_id.split(":", 1)

        def set_node_color(color: str):
            if dag_id:
                try:
                    from src.api.routes.dags import _dag_store
                    from src.core.orchestrator.models import NodeColor
                    from src.core.agent.pool import agent_bus
                    from datetime import datetime, timezone
                    dag_def = _dag_store.get(dag_id)
                    if dag_def:
                        node = dag_def.get_node(node_id)
                        if node:
                            node.color = NodeColor(color)
                            _dag_store[dag_id] = dag_def
                            
                            # Publish state transition to message bus
                            asyncio.create_task(
                                agent_bus.publish(
                                    topic="dag_updates",
                                    sender_id="dag_engine",
                                    payload={
                                        "dag_id": dag_id,
                                        "node_id": node_id,
                                        "color": color,
                                        "role_id": getattr(node, "role_id", None),
                                        "dag_status": dag_def.status,
                                        "timestamp": datetime.now(timezone.utc).isoformat()
                                    }
                                )
                            )
                except Exception as ex:
                    logger.error("Failed to update node color in store", error=str(ex))

        for iteration in range(self.MAX_ITERATIONS):
            t0 = time.time()

            # 1. Budget Token Check
            current_tokens = trace.total_tokens_input + trace.total_tokens_output
            if current_tokens > max_tokens:
                raise RuntimeError(
                    f"Token budget exceeded ({current_tokens} > {max_tokens}) for model {self.model}"
                )

            # 2. Lock Preemption Check: Verify all acquired locks are still ours
            for lock_path in list(self.acquired_locks):
                lock_info = await lock_manager.get_lock_info(lock_path)
                if not lock_info or lock_info.holder_agent != self.agent_id:
                    raise RuntimeError(
                        f"Execution aborted: Lock on file '{lock_path}' was preempted by another agent."
                    )

            # Call LLM
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": min(max_tokens, 8192),
            }
            if tools_schema:
                kwargs["tools"] = tools_schema

            response = await litellm.acompletion(**kwargs)
            elapsed_ms = int((time.time() - t0) * 1000)

            # Track token usage
            usage = response.usage
            if usage:
                trace.total_tokens_input += usage.prompt_tokens or 0
                trace.total_tokens_output += usage.completion_tokens or 0

            choice = response.choices[0]
            message = choice.message

            # Case 1: LLM wants to call tools
            if message.tool_calls:
                messages.append(message.model_dump())

                for tool_call in message.tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        # Parse with strict=False to tolerate literal newlines and tabs in string values
                        fn_args = json.loads(tool_call.function.arguments, strict=False)
                    except json.JSONDecodeError as json_err:
                        logger.warning("Failed to parse tool call arguments as-is. Attempting JSON repair.", fn_name=fn_name, error=str(json_err))
                        try:
                            repaired_args = self._repair_json(tool_call.function.arguments)
                            fn_args = json.loads(repaired_args, strict=False)
                            logger.info("Successfully repaired truncated tool call arguments JSON", fn_name=fn_name)
                        except Exception as repair_err:
                            logger.error("Failed to parse tool call arguments even after repair", fn_name=fn_name, raw_args=tool_call.function.arguments, error=str(repair_err))
                            raise RuntimeError(f"Tool call '{fn_name}' arguments are not valid JSON: {tool_call.function.arguments}") from json_err

                    # Map absolute/external paths to safe paths inside the workspace
                    path_keys = ["path", "target_path", "TargetFile"]
                    for key in path_keys:
                        if isinstance(fn_args, dict) and key in fn_args and isinstance(fn_args[key], str):
                            val = fn_args[key]
                            from src.config import settings
                            workspace = settings.resolved_workspace_path
                            
                            # Strip known prefixes
                            for prefix in ["/home/user", "/workspace"]:
                                if val.startswith(prefix):
                                    val = val[len(prefix):].lstrip("/")
                                    break
                            if val.startswith("~"):
                                val = val.lstrip("~").lstrip("/")
                            
                            # Resolve path relative to settings.resolved_workspace_path
                            # If it is absolute, check if it's already in the workspace
                            import os
                            try:
                                abs_p = os.path.abspath(val)
                                common = os.path.commonpath([abs_p, workspace])
                                if common == workspace:
                                    fn_args[key] = abs_p
                                    continue
                            except Exception:
                                pass
                                
                            # Otherwise treat as relative to workspace
                            rel_p = val
                            if rel_p.startswith("/"):
                                rel_p = rel_p.lstrip("/")
                            import re
                            rel_p = re.sub(r'^[a-zA-Z]:[/\\]+', '', rel_p)
                            
                            fn_args[key] = os.path.abspath(os.path.join(workspace, rel_p))

                    trace.add_step(
                        action=f"tool_call:{fn_name}",
                        input_summary=json.dumps(fn_args, ensure_ascii=False),
                        output_summary="(executing...)",
                        reasoning=message.content or "",
                        duration_ms=elapsed_ms,
                        tokens=usage.total_tokens if usage else 0,
                    )

                    # Intercept file write calls for dynamic locking
                    if fn_name == "file_write":
                        file_path = fn_args.get("path")
                        if file_path:
                            abs_path = os.path.abspath(file_path)
                            if abs_path not in self.acquired_locks:
                                logger.info(
                                    "Attempting to acquire lock for file_write",
                                    file=abs_path,
                                    agent=self.agent_id,
                                )
                                lock_res = await lock_manager.acquire(
                                    file_path=abs_path,
                                    agent_id=self.agent_id,
                                    task_id=task_id,
                                    priority=self.priority,
                                )
                                if not lock_res.granted:
                                    # Wait/enqueue
                                    wait_start = time.time()
                                    acquired = False
                                    logger.info(
                                        "File lock busy, queuing/waiting",
                                        file=abs_path,
                                        position=lock_res.queue_position,
                                    )
                                    while time.time() - wait_start < 30:
                                        await asyncio.sleep(1)
                                        # Retry acquire
                                        lock_res = await lock_manager.acquire(
                                            file_path=abs_path,
                                            agent_id=self.agent_id,
                                            task_id=task_id,
                                            priority=self.priority,
                                        )
                                        if lock_res.granted:
                                            acquired = True
                                            break
                                    if not acquired:
                                        raise RuntimeError(
                                            f"Lock acquisition timeout for file '{abs_path}' (held by {lock_res.holder_agent})"
                                        )
                                self.acquired_locks.add(abs_path)

                    # 3. Guardrails & Approvals Check (Phase 3)
                    risk_level = guardrail_engine.evaluate(
                        fn_name,
                        fn_args,
                        tenant_id=self.tenant_id,
                        role=role.get("name") if role else None
                    )
                    
                    # Log audit event
                    await audit_logger.log_event(
                        event_type="guardrail_evaluation",
                        task_id=task_id,
                        agent_id=self.agent_id,
                        details={
                            "tool_name": fn_name,
                            "arguments": fn_args,
                            "risk_level": risk_level
                        }
                    )

                    if risk_level == "L4":
                        from src.config import settings
                        if settings.auto_approve_l4:
                            logger.info("Auto-approval enabled (auto_approve_l4=True). Bypassing L4 tool approval.", tool=fn_name)
                            granted = True
                        else:
                            raise RuntimeError(f"Tool execution forbidden by security policy (L4): {fn_name}")
                    
                    elif risk_level == "L3":
                        from src.config import settings
                        if settings.auto_approve_l3:
                            logger.info("Auto-approval enabled (auto_approve_l3=True). Bypassing tool approval.", tool=fn_name)
                            granted = True
                        else:
                            logger.info("Suspending execution for L3 approval", tool=fn_name)
                            # Set node color to orange
                            set_node_color("orange")

                            # Request approval
                            appr_id = await approval_manager.request_approval(
                                task_id=task_id,
                                agent_id=self.agent_id,
                                tool_name=fn_name,
                                arguments=fn_args,
                                priority=self.priority,
                                tenant_id=self.tenant_id,
                                task_description=task_description,
                            )
                            
                            # Wait for human signal
                            granted = await approval_manager.wait_for_approval(appr_id)
                            
                            # Restore node color to yellow (running)
                            if granted:
                                set_node_color("yellow")
                                # Read possibly updated arguments
                                updated_args = await approval_manager.get_approval_arguments(appr_id)
                                if updated_args is not None:
                                    fn_args = updated_args
                        
                        # Log audit decision
                        await audit_logger.log_event(
                            event_type="approval_resolution",
                            task_id=task_id,
                            agent_id=self.agent_id,
                            details={
                                "approval_id": appr_id,
                                "tool_name": fn_name,
                                "arguments": fn_args,
                                "decision": "approved" if granted else "rejected"
                            }
                        )

                        if not granted:
                            raise RuntimeError(f"Tool execution rejected by user approval (L3): {fn_name}")

                    # Execute tool
                    tool = tool_map.get(fn_name)
                    if tool:
                        from src.core.agent.tools import current_task_id, current_agent_id
                        task_token = current_task_id.set(task_id)
                        agent_token = current_agent_id.set(self.agent_id)
                        try:
                            tool_result = await tool.execute(**fn_args)
                        finally:
                            current_task_id.reset(task_token)
                            current_agent_id.reset(agent_token)
                        output = json.dumps(tool_result, ensure_ascii=False)
                    else:
                        output = json.dumps({"error": f"Unknown tool: {fn_name}"})

                    # Smart log/error compression for non-reading tools to save token cost and prevent truncation
                    is_reading_tool = any(k in fn_name.lower() for k in ["read", "view", "list", "grep"])
                    processed_output = output
                    if not is_reading_tool:
                        processed_output = extract_critical_log_context(output)

                    # Update trace with tool output
                    trace.steps[-1]["output_summary"] = processed_output[:1000]

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": processed_output,
                    })

            # Case 2: LLM returns final answer (no tool calls)
            else:
                final_answer = message.content or ""
                trace.add_step(
                    action="final_answer",
                    input_summary="(synthesizing final response)",
                    output_summary=final_answer[:1000],
                    duration_ms=elapsed_ms,
                    tokens=usage.total_tokens if usage else 0,
                )
                return final_answer

        return "Error: Agent exceeded maximum iterations without producing a final answer."

    def _build_system_prompt(self, skill: dict, context: str, role: dict | None = None) -> str:
        """Assemble the system prompt from Skill definition + loaded context."""
        parts = []

        # Role's system prompt prefix
        if role and role.get("system_prompt_prefix"):
            parts.append(role["system_prompt_prefix"])

        # Skill's own system prompt
        if skill.get("system_prompt"):
            parts.append(skill["system_prompt"])

        # Global constraints
        from src.config import settings
        workspace = settings.resolved_workspace_path
        parts.append(
            "\n## Global Rules\n"
            "1. Always output valid JSON when asked for structured output.\n"
            "2. Never fabricate file paths or function names — verify with tools first.\n"
            "3. If unsure, use tools to gather information before making changes.\n"
            "4. Stay within the scope of the assigned task.\n"
            f"5. The project workspace storage directory is '{workspace}'. All project files MUST be stored inside this directory. When using file_write or file_read, use paths relative to this directory (e.g., 'tetris_game.py') or absolute paths within it (e.g., '{workspace}/tetris_game.py'). Never write to external directories like /home/user.\n"
            "6. Smart Reuse & Review Principle (智能审查与复用原则):\n"
            "   Before writing or generating any new file or document, ALWAYS use directory_list or file_read to check if a file with that name (or similar design/code files) already exists in the workspace (or its subdirectories like docs/ or src/).\n"
            "   If it exists: (a) READ it first; (b) REVIEW and evaluate it against current requirements; (c) If it is correct/complete, reuse it directly instead of overwriting/regenerating from scratch; (d) If it needs changes, only modify or append the necessary parts to save time and tokens.\n"
            "7. Test-Driven Diagnosis Principle (双重验证原则):\n"
            "   Before fixing any bugs or implementing new features, ALWAYS check if there are existing tests. Run them first to verify the issue. If a test fails, do not blindly assume the source code is wrong; analyze whether the test assertion itself contains a coordinate system or logical mismatch, and fix the test first if necessary.\n"
            "   Whenever you make a code change, immediately run the corresponding unit/integration tests to verify correctness, rather than waiting until the end.\n"
            "8. Minimal Edits & Anti-Truncation Principle (最小修改与抗截断原则):\n"
            "   When editing files, always perform the smallest contiguous edits possible (e.g., modifying specific lines rather than overwriting whole files). This avoids LLM output truncation, prevents syntax breakage, and significantly reduces token consumption.\n"
            "9. Anti-Looping Self-Termination Principle (循环自我终止原则):\n"
            "   If you encounter the same compilation, syntax, or test error for 3 consecutive iterations, DO NOT continue repeating the same modifications. Stop immediately, write a brief explanation of the blocker, suggest potential solutions, and request user approval or guidance."
        )

        # Loaded context
        if context:
            parts.append(f"\n## Project Context\n{context}")

        return "\n".join(parts)

    def _repair_json(self, s: str) -> str:
        """Attempt to repair a truncated or malformed JSON string."""
        in_string = False
        escape = False
        stack = []
        repaired = []
        
        for char in s:
            repaired.append(char)
            if escape:
                escape = False
                continue
            if char == '\\':
                if in_string:
                    escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char in ('{', '['):
                    stack.append(char)
                elif char in ('}', ']'):
                    if stack:
                        stack.pop()
        
        if in_string:
            if repaired and repaired[-1] == '\\':
                repaired.pop()
            repaired.append('"')
        
        while stack:
            top = stack.pop()
            if top == '{':
                repaired.append('}')
            elif top == '[':
                repaired.append(']')
                
        return "".join(repaired)
