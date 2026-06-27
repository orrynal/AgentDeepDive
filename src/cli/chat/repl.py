"""Asynchronous REPL event loop for AgentDeepDive Interactive Terminal."""

import asyncio
import os
import re
import json
import structlog
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
import litellm

from src.cli.chat.session import ChatSession, HISTORY_DIR
from src.cli.chat.renderer import StreamRenderer
from src.cli.chat.slash_commands import handle_slash_command
from src.cli.chat.tool_bridge import ToolBridge
from src.core.budget.manager import budget_manager

logger = structlog.get_logger()

# Setup style for prompt_toolkit
prompt_style = Style.from_dict({
    "prompt": "bold cyan",
})

def expand_file_references(text: str, workspace_path: str, renderer: StreamRenderer) -> tuple[str, list[str]]:
    """Scan user input for @filename pattern and inject file context if exists."""
    # Matches words starting with @ followed by characters that form a valid path
    matches = re.findall(r"@([a-zA-Z0-9_\-\.\/]+)", text)
    if not matches:
        return text, []

    workspace = Path(workspace_path)
    injected_files = []
    appended_content = []

    for match in matches:
        # Check relative to workspace
        target_path = workspace / match
        if not target_path.exists():
            # Check absolute path
            target_path = Path(match)

        if target_path.exists() and target_path.is_file():
            try:
                # Read file content safely
                content = target_path.read_text(encoding="utf-8", errors="replace")
                # Cap the file length to avoid blowing up the context too much (max 15k chars per file)
                if len(content) > 15000:
                    content = content[:15000] + "\n... (file content truncated to 15k characters)"

                appended_content.append(f"\n\n--- File Context: {match} ---\n{content}\n-----------------------------")
                injected_files.append(match)
            except Exception as e:
                renderer.console.print(f"⚠️ [yellow]Warning: Could not read file @{match}: {e}[/yellow]")

    if injected_files:
        renderer.console.print(
            f"📎 [bold green]Injected context from {len(injected_files)} file(s):[/bold green] " + 
            ", ".join(injected_files)
        )
        text += "".join(appended_content)

    return text, injected_files

async def retrieve_episodic_memories(query: str, renderer: StreamRenderer) -> str:
    """Retrieve similar historical episodic memories from Milvus/RAG manager."""
    try:
        from src.core.memory.rag_manager import rag_manager
        # Check if connected or local fallback contains records
        if rag_manager.connected or hasattr(rag_manager, "local_em"):
            memories = rag_manager.query_episodic_memory(query, limit=2)
            if memories:
                renderer.console.print(
                    f"🧠 [bold cyan]Recalled {len(memories)} relevant episodic memories from Vector DB.[/bold cyan]"
                )
                memory_blocks = []
                for idx, mem in enumerate(memories):
                    prompt_str = mem.get("prompt", "")
                    error_str = mem.get("error_stack", "")
                    patch_str = mem.get("patch", "")
                    block = (
                        f"Memory #{idx+1}:\n"
                        f"- Prompt: {prompt_str}\n"
                        f"- Previous Error Stack: {error_str}\n"
                        f"- Successful Fix Patch:\n{patch_str}"
                    )
                    memory_blocks.append(block)
                return "\n\n--- Relevant Historical Memories ---\n" + "\n\n".join(memory_blocks) + "\n------------------------------------"
    except Exception as e:
        logger.debug("Failed to retrieve episodic memories in REPL", error=str(e))
    return ""

async def run_repl(session: ChatSession, renderer: StreamRenderer):
    """Main REPL event loop for the chat interface."""
    # Ensure history directory exists
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_file = HISTORY_DIR / ".repl_history"

    # Initialize ToolBridge
    tool_bridge = ToolBridge(renderer.console)

    # Fetch workspace path
    from src.config import settings
    workspace_path = settings.resolved_workspace_path

    # Define bottom toolbar function for prompt_toolkit
    def get_bottom_toolbar():
        token_count = session.estimate_tokens()
        from src.core.budget.manager import MODEL_PRICING
        pricing = MODEL_PRICING.get(session.model, {"input": 0.0, "output": 0.0})
        est_cost = (token_count * pricing["input"]) / 1_000_000
        spent_usd = budget_manager._in_memory_spent_usd.get(session.tenant_id, 0.0)
        return f" Model: {session.model} | Est. Context: {token_count:,} (${est_cost:.4f}) | Spent: ${spent_usd:.4f} | Tenant: {session.tenant_id} "

    # Initialize prompt_toolkit PromptSession with file history and bottom toolbar
    prompt_session = PromptSession(
        history=FileHistory(str(history_file)),
        style=prompt_style,
        bottom_toolbar=get_bottom_toolbar
    )

    # Print welcome banner
    # Resolve running mode (LOCAL vs REMOTE) from config/environment
    mode = os.getenv("AGENTDEEP_MODE", "LOCAL").upper()
    renderer.print_banner(model=session.model, tenant_id=session.tenant_id, mode=mode)

    async def on_workflow_suspended(data: dict):
        payload = data.get("payload", {})
        dag_id = payload.get("dag_id")
        node_id = payload.get("node_id")
        error = payload.get("error", "Unknown error")
        
        session.active_suspended_node = {
            "dag_id": dag_id,
            "node_id": node_id,
            "error": error
        }
        
        renderer.console.print("\n")
        renderer.console.print(f"⚠️ [bold red]Node '{node_id}' in DAG '{dag_id}' has execution failure and is SUSPENDED![/bold red]")
        renderer.console.print(f"❌ [bold yellow]Error detail:[/bold yellow] {error}")
        renderer.console.print("\n[bold]You can resolve this using the following interactive commands:[/bold]")
        renderer.console.print("  [bold cyan]/retry[/bold cyan]            - Reset node state to GRAY and rerun the DAG")
        renderer.console.print("  [bold cyan]/bypass[/bold cyan]           - Force mark node as completed (GREEN) and resume downstream nodes")
        renderer.console.print("  [bold cyan]/patch <file> <text>[/bold cyan] - Write new content to a file, then automatically retry")
        renderer.console.print("\n>>> ", end="")

    from src.core.agent.pool import agent_bus
    await agent_bus.subscribe("workflow.suspended", on_workflow_suspended)

    try:
        while True:
            try:
                # prompt_async runs asynchronously and integrates seamlessly with asyncio
                user_input = await prompt_session.prompt_async(">>> ")
                
                # Skip empty inputs
                user_input = user_input.strip()
                if not user_input:
                    continue

                # 1. Check for slash command
                if user_input.startswith("/"):
                    should_continue = await handle_slash_command(user_input, session, renderer)
                    if not should_continue:
                        break
                    continue

                # 2. File Context Injection (@file syntax)
                processed_input, injected_files = expand_file_references(user_input, workspace_path, renderer)

                # 3. Episodic Memory Recall (Milvus Vector DB)
                memory_context = await retrieve_episodic_memories(user_input, renderer)
                if memory_context:
                    processed_input += memory_context

                # 4. Add processed message (with files and memories) to session history
                session.add_user_message(processed_input)

                # 5. Call LiteLLM & Tool execution inner loop
                MAX_ITERATIONS = 10
                for iteration in range(MAX_ITERATIONS):
                    # Request budget clearance
                    budget_approval = await budget_manager.request_budget(
                        task_type="default",
                        tenant_id=session.tenant_id
                    )
                    if not budget_approval.approved:
                        renderer.console.print(
                            f"❌ [bold red]Budget Denied:[/bold red] {budget_approval.reason}. {budget_approval.suggestion}"
                        )
                        break
                    
                    # Use approved model (might be downgraded due to budget limits)
                    active_model = budget_approval.model or session.model

                    try:
                        # Disable excessive debug info from litellm
                        litellm.suppress_debug_info = True
                        
                        kwargs = {
                            "model": active_model,
                            "messages": session.messages,
                            "stream": True
                        }
                        # Retrieve tool schemas and pass them to LiteLLM
                        schemas = tool_bridge.get_tool_schemas()
                        if schemas:
                            kwargs["tools"] = schemas

                        # A. Call LLM
                        response_stream = await litellm.acompletion(**kwargs)

                        # B. Stream response to terminal
                        in_tokens_est = session.estimate_tokens()
                        stream_res = await renderer.stream_and_collect(response_stream)
                        out_tokens_est = len(stream_res.full_content) // 4

                        # Record actual token usage to budget manager
                        await budget_manager.record_usage(
                            model=active_model,
                            task_type="default",
                            tokens_in=in_tokens_est,
                            tokens_out=out_tokens_est,
                            tenant_id=session.tenant_id
                        )

                        # C. Handle tool execution if requested
                        if stream_res.has_tool_calls:
                            # Convert ToolCall objects to dicts for conversation history
                            tc_list = []
                            for tc in stream_res.tool_calls:
                                tc_list.append({
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments
                                    }
                                })
                            
                            session.add_raw_message({
                                "role": "assistant",
                                "content": stream_res.full_content or "",
                                "tool_calls": tc_list
                            })

                            # Execute tool calls sequentially
                            for tc in stream_res.tool_calls:
                                tool_name = tc.function.name
                                try:
                                    # Parse tool args
                                    fn_args = json.loads(tc.function.arguments, strict=False)
                                except Exception as parse_err:
                                    logger.error("Failed to parse tool call arguments", tool=tool_name, error=str(parse_err))
                                    fn_args = {}

                                # Notify start of tool call
                                renderer.print_tool_start(tool_name, fn_args)

                                # Execute tool with safety guardrails and lock manager
                                result_str = await tool_bridge.execute_tool(
                                    tool_name=tool_name,
                                    arguments=fn_args,
                                    session_id=session.session_id,
                                    tenant_id=session.tenant_id
                                )

                                # Notify finish of tool call
                                try:
                                    res_dict = json.loads(result_str)
                                    if res_dict.get("status") == "success":
                                        renderer.print_tool_success(tool_name, str(res_dict.get("output", "")))
                                    else:
                                        renderer.print_tool_error(tool_name, str(res_dict.get("error", "Unknown error")))
                                except Exception:
                                    renderer.print_tool_success(tool_name, result_str)

                                # Add tool output back to conversation history
                                session.add_tool_result(tc.id, tool_name, result_str)

                            # Continue loop for agent to evaluate tool outputs
                            continue
                        else:
                            # Case 2: Final response with no tool calls, add to conversation history
                            session.add_assistant_message(stream_res.full_content)
                            break

                    except Exception as llm_err:
                        renderer.console.print(f"❌ [bold red]LLM Error:[/bold red] {llm_err}")
                        logger.error("Error during LLM completion in REPL loop", error=str(llm_err))
                        break

            except KeyboardInterrupt:
                # Handle Ctrl+C inside the input prompt
                renderer.console.print("\n[yellow]KeyboardInterrupt (Ctrl+C). Type /exit to quit.[/yellow]")
                continue
            except EOFError:
                # Handle Ctrl+D
                renderer.console.print("\n👋 [bold green]Goodbye! Session ended (EOF).[/bold green]")
                break
            except Exception as e:
                renderer.console.print(f"❌ [bold red]Unexpected Error:[/bold red] {e}")
                logger.error("Unexpected error in REPL loop", error=str(e))
                continue
    finally:
        try:
            from src.core.agent.pool import agent_bus
            await agent_bus.unsubscribe("workflow.suspended", on_workflow_suspended)
        except Exception:
            pass
        # Release all file locks held by the session before exit
        await tool_bridge.release_all_locks()
