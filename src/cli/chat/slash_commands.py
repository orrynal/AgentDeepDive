"""Slash command handlers for AgentDeepDive Interactive Terminal."""

import sys
import os
import time
from pathlib import Path
from rich.table import Table
from rich.panel import Panel
from src.cli.chat.session import ChatSession, HISTORY_DIR
from src.cli.chat.renderer import StreamRenderer

async def handle_slash_command(user_input: str, session: ChatSession, renderer: StreamRenderer) -> bool:
    """Process a slash command from the user.
    
    Returns:
        bool: True if the conversation loop should continue, False if the program should exit.
    """
    parts = user_input.strip().split()
    if not parts:
        return True

    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/exit", "/quit"):
        renderer.console.print("👋 [bold green]Goodbye! Session ended.[/bold green]")
        return False

    elif cmd == "/help":
        table = Table(title="Available Slash Commands", border_style="dim cyan")
        table.add_column("Command", style="bold green")
        table.add_column("Arguments", style="yellow")
        table.add_column("Description")

        table.add_row("/help", "", "Show this help table")
        table.add_row("/clear", "", "Clear the current chat history (keeps system prompt)")
        table.add_row("/model", "[model_name]", "Switch or print the current active model")
        table.add_row("/status", "", "Show current session statistics and resource usage")
        table.add_row("/save", "[filename]", "Save session history to .chat_history/ as JSON")
        table.add_row("/load", "<filename>", "Load saved session history from .chat_history/")
        table.add_row("/locks", "", "List all active concurrency locks in Redis")
        table.add_row("/doctor", "", "Run health checks on all dependent backend services")
        table.add_row("/dag", "[dag_id]", "Show ASCII visual topology tree of the last or specified DAG")
        table.add_row("/retry", "", "Reset suspended node state to GRAY and rerun the DAG")
        table.add_row("/bypass", "", "Force mark suspended node as completed (GREEN) and resume DAG")
        table.add_row("/patch", "<file> <content>", "Patch a local file and retry the suspended node")
        table.add_row("/exit, /quit", "", "Exit the interactive session")

        renderer.console.print(table)
        return True

    elif cmd == "/clear":
        session.clear()
        renderer.console.print("✨ [bold green]Chat history cleared successfully.[/bold green] (System prompt retained)")
        return True

    elif cmd == "/model":
        if not args:
            renderer.console.print(f"🤖 [bold yellow]Current Model:[/bold yellow] [cyan]{session.model}[/cyan]")
        else:
            new_model = args[0]
            session.model = new_model
            renderer.console.print(f"🤖 [bold green]Model switched to:[/bold green] [cyan]{new_model}[/cyan]")
        return True

    elif cmd == "/status":
        total_msgs = len(session.messages)
        estimated_tokens = session.estimate_tokens()
        
        renderer.console.print(Panel(
            f"[bold yellow]Session ID:[/bold yellow] {session.session_id}\n"
            f"[bold yellow]Model:[/bold yellow] {session.model}\n"
            f"[bold yellow]Tenant ID:[/bold yellow] {session.tenant_id}\n"
            f"[bold yellow]Total Messages:[/bold yellow] {total_msgs}\n"
            f"[bold yellow]Estimated Tokens:[/bold yellow] {estimated_tokens:,} / {session.max_context_tokens:,}\n"
            f"[bold yellow]Start Time:[/bold yellow] {session.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            title="Session Status",
            border_style="cyan"
        ))
        return True

    elif cmd == "/save":
        filename = args[0] if args else None
        try:
            filepath = session.save_to_disk(filename)
            renderer.console.print(f"💾 [bold green]Session saved successfully to:[/bold green] [cyan]{filepath.name}[/cyan]")
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to save session:[/bold red] {e}")
        return True

    elif cmd == "/load":
        if not args:
            renderer.console.print("❌ [bold red]Usage:[/bold red] /load <filename>")
            # List available saved sessions
            if HISTORY_DIR.exists():
                files = list(HISTORY_DIR.glob("*.json"))
                if files:
                    renderer.console.print("\n[bold yellow]Available Saved Sessions:[/bold yellow]")
                    for f in files:
                        renderer.console.print(f" - {f.name}")
                else:
                    renderer.console.print("No saved sessions found.")
            return True

        filename = args[0]
        if not filename.endswith(".json"):
            filename += ".json"
        filepath = HISTORY_DIR / filename
        if not filepath.exists():
            renderer.console.print(f"❌ [bold red]File not found:[/bold red] [cyan]{filename}[/cyan]")
            return True

        if session.load_from_disk(filepath):
            renderer.console.print(f"📂 [bold green]Session loaded successfully from:[/bold green] [cyan]{filename}[/cyan]")
        else:
            renderer.console.print(f"❌ [bold red]Failed to load session from file:[/bold red] [cyan]{filename}[/cyan]")
        return True

    elif cmd == "/locks":
        renderer.console.print("⏳ [bold yellow]Fetching concurrency locks from Redis...[/bold yellow]")
        try:
            from src.core.concurrency.lock_manager import lock_manager
            locks = await lock_manager.list_locks()
            if not locks:
                renderer.console.print("[green]No active locks found.[/green]")
                return True

            table = Table(title="Active Concurrency Locks", border_style="magenta")
            table.add_column("File Path", style="cyan")
            table.add_column("Holder Agent", style="magenta")
            table.add_column("Task ID", style="dim")
            table.add_column("Priority", justify="right")
            table.add_column("Acquired At", justify="center")
            table.add_column("TTL Left", justify="right")

            for l in locks:
                acq_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(l.acquired_at))
                now = time.time()
                elapsed = now - l.acquired_at
                ttl_left = max(0, int(l.ttl_sec - elapsed))
                table.add_row(
                    l.file_path,
                    l.holder_agent,
                    l.task_id or "-",
                    str(l.priority),
                    acq_time,
                    f"{ttl_left}s",
                )
            renderer.console.print(table)
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to fetch locks:[/bold red] {e}")
        return True

    elif cmd == "/dag":
        from src.cli.context import CLIContext, CLIMode
        from src.cli.main import API_BASE_URL
        from src.core.orchestrator.models import DAGDefinition
        
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        dag_id = args[0] if args else None
        dag_data = None
        
        renderer.console.print("⏳ [bold yellow]Retrieving DAG status...[/bold yellow]")
        
        try:
            if mode == CLIMode.REMOTE:
                async with ctx.get_http_client() as client:
                    if not dag_id:
                        resp = await client.get(f"{API_BASE_URL}/dags", timeout=5)
                        if resp.status_code == 200:
                            dags_list = resp.json()
                            if dags_list:
                                dags_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                                dag_id = dags_list[0]["dag_id"]
                                resp_dag = await client.get(f"{API_BASE_URL}/dags/{dag_id}", timeout=5)
                                if resp_dag.status_code == 200:
                                    dag_data = DAGDefinition.model_validate(resp_dag.json())
                    else:
                        resp_dag = await client.get(f"{API_BASE_URL}/dags/{dag_id}", timeout=5)
                        if resp_dag.status_code == 200:
                            dag_data = DAGDefinition.model_validate(resp_dag.json())
            else:
                from src.core.orchestrator.persistence import load_dags_from_disk
                async with ctx.get_db() as db_session:
                    tenant_id = await ctx.resolve_tenant_id(db_session)
                dags = load_dags_from_disk(tenant_id=tenant_id)
                if dags:
                    if not dag_id:
                        sorted_dags = sorted(dags.values(), key=lambda x: x.created_at, reverse=True)
                        dag_data = sorted_dags[0]
                    else:
                        dag_data = dags.get(dag_id)
                        
            if not dag_data:
                if dag_id:
                    renderer.console.print(f"❌ [bold red]DAG '{dag_id}' not found.[/bold red]")
                else:
                    renderer.console.print("❌ [bold red]No DAG executions found.[/bold red]")
                return True
                
            from collections import defaultdict
            children = defaultdict(list)
            for node in dag_data.nodes:
                for dep in node.dependencies:
                    children[dep].append(node.node_id)
                    
            roots = [n for n in dag_data.nodes if not n.dependencies]
            
            color_symbols = {
                "green": "🟢",
                "red": "🔴",
                "yellow": "⏳",
                "blue": "🔵",
                "gray": "⚪",
                "orange": "🟠",
                "suspended": "🟠",
            }
            
            lines = []
            lines.append(f"[bold cyan]DAG: {dag_data.name} ({dag_data.dag_id})[/bold cyan]")
            lines.append(f"Overall Status: [bold]{dag_data.status.upper()}[/bold] | Tier: {dag_data.routing_tier or 'N/A'}")
            lines.append("=" * 60)
            
            visited = set()
            
            def render_node(node_id: str, prefix: str = "", is_last: bool = True):
                node = dag_data.get_node(node_id)
                if not node:
                    return
                
                status_symbol = color_symbols.get(node.color.value if hasattr(node.color, "value") else node.color, "⚪")
                node_label = f"{status_symbol} [bold]{node.name}[/bold] ({node.node_id})"
                if node.role_id:
                    node_label += f" [dim]Role: {node.role_id}[/dim]"
                    
                marker = "└── " if is_last else "├── "
                lines.append(f"{prefix}{marker}{node_label}")
                
                node_children = children[node_id]
                new_prefix = prefix + ("    " if is_last else "│   ")
                
                if node_id not in visited:
                    visited.add(node_id)
                    for idx, child_id in enumerate(node_children):
                        render_node(
                            child_id,
                            new_prefix,
                            is_last=(idx == len(node_children) - 1)
                        )
                    visited.remove(node_id)
            
            if not roots:
                for node in dag_data.nodes:
                    status_symbol = color_symbols.get(node.color.value if hasattr(node.color, "value") else node.color, "⚪")
                    lines.append(f"{status_symbol} [bold]{node.name}[/bold] ({node.node_id})")
            else:
                for idx, root in enumerate(roots):
                    render_node(root.node_id, prefix="", is_last=(idx == len(roots) - 1))
            renderer.console.print(Panel("\n".join(lines), border_style="cyan", title="DAG Execution Graph"))
            
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to retrieve DAG information:[/bold red] {e}")
        return True

    elif cmd == "/doctor":
        renderer.console.print("⚕️ [bold cyan]Running System Doctor Checkups...[/bold cyan]")
        try:
            from src.cli.commands.doctor import (
                check_postgres,
                check_redis,
                check_opa,
                check_jaeger,
                check_socket_port,
                check_docker_environment
            )
            from src.config import settings
            import platform
            
            table = Table(show_header=True, header_style="bold magenta", border_style="dim")
            table.add_column("Resource / Component", style="cyan", width=30)
            table.add_column("Status", width=15)
            table.add_column("Diagnostics / Detail")

            # 1. Python
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            table.add_row("Python Version", "[green]✅ OK[/green]", f"{py_ver} ({platform.system()})")

            # 2. PostgreSQL
            pg_ok, pg_msg = await check_postgres()
            pg_status = "[green]✅ Connected[/green]" if pg_ok else "[red]❌ Offline[/red]"
            table.add_row("PostgreSQL", pg_status, pg_msg)

            # 3. Redis
            r_ok, r_msg = check_redis()
            r_status = "[green]✅ Connected[/green]" if r_ok else "[red]❌ Offline[/red]"
            table.add_row("Redis", r_status, r_msg)

            # 4. Milvus
            m_ok = check_socket_port(settings.milvus_host, settings.milvus_port)
            m_status = "[green]✅ Connected[/green]" if m_ok else "[red]❌ Offline[/red]"
            m_msg = f"Connected to Milvus at {settings.milvus_host}:{settings.milvus_port}" if m_ok else f"Failed to connect to Milvus at {settings.milvus_host}:{settings.milvus_port}"
            table.add_row("Milvus (Vector DB)", m_status, m_msg)

            # 5. OPA
            opa_ok, opa_msg = await check_opa()
            opa_status = "[green]✅ Connected[/green]" if opa_ok else ("[yellow]⚠️ Skipped[/yellow]" if not settings.opa_enabled else "[red]❌ Offline[/red]")
            table.add_row("Open Policy Agent (OPA)", opa_status, opa_msg)

            # 6. Jaeger
            jaeger_ok, jaeger_msg = await check_jaeger()
            jaeger_status = "[green]✅ Connected[/green]" if jaeger_ok else "[red]❌ Offline[/red]"
            table.add_row("Jaeger Tracing", jaeger_status, jaeger_msg)

            # 7. Docker
            docker_avail, docker_detail = check_docker_environment()
            docker_status = "[green]✅ Available[/green]" if docker_avail else "[red]❌ Missing[/red]"
            table.add_row("Docker CLI Engine", docker_status, docker_detail)

            renderer.console.print(table)
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to complete doctor diagnosis:[/bold red] {e}")
        return True

    elif cmd == "/retry":
        suspended = getattr(session, "active_suspended_node", None)
        if not suspended:
            renderer.console.print("❌ [bold red]No active suspended node found.[/bold red]")
            return True
            
        dag_id = suspended["dag_id"]
        node_id = suspended["node_id"]
        
        renderer.console.print(f"🔄 [bold yellow]Retrying node '{node_id}' in DAG '{dag_id}'...[/bold yellow]")
        
        from src.cli.context import CLIContext, CLIMode
        from src.cli.main import API_BASE_URL
        from src.core.orchestrator.models import NodeColor
        import asyncio
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        try:
            if mode == CLIMode.REMOTE:
                async with ctx.get_http_client() as client:
                    resp = await client.post(
                        f"{API_BASE_URL}/dags/{dag_id}/nodes/{node_id}/action",
                        json={"action": "retry"},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        renderer.console.print("🚀 [bold green]DAG execution resumed successfully in background (Remote).[/bold green]")
                        session.active_suspended_node = None
                    else:
                        renderer.console.print(f"❌ [bold red]Remote action failed {resp.status_code}:[/bold red] {resp.text}")
            else:
                # Local mode
                from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk
                from src.core.orchestrator.dag_engine import DAGEngine
                from src.core.skill.service import SkillService
                
                async with ctx.get_db() as db_session:
                    tenant_id = await ctx.resolve_tenant_id(db_session)
                    skill_svc = SkillService(db_session, tenant_id=tenant_id)
                    engine = DAGEngine(skill_svc)
                    
                    dags = load_dags_from_disk(tenant_id=tenant_id)
                    dag = dags.get(dag_id)
                    if not dag:
                        renderer.console.print(f"❌ [bold red]DAG '{dag_id}' not found locally.[/bold red]")
                        return True
                        
                    node = dag.get_node(node_id)
                    if not node:
                        renderer.console.print(f"❌ [bold red]Node '{node_id}' not found in DAG.[/bold red]")
                        return True
                        
                    node.color = NodeColor.GRAY
                    node.error = None
                    dag.status = "running"
                    save_dag_to_disk(dag, tenant_id=tenant_id)
                    
                    # Start execution in a background task
                    async def run_local_bg():
                        try:
                            async with ctx.get_db() as new_sess:
                                local_skill_svc = SkillService(new_sess, tenant_id=tenant_id)
                                local_engine = DAGEngine(local_skill_svc)
                                result = await local_engine.execute(dag)
                                save_dag_to_disk(result, tenant_id=tenant_id)
                        except Exception as bg_ex:
                            renderer.console.print(f"\n❌ [bold red]Local background execution failed:[/bold red] {bg_ex}")
                            
                    asyncio.create_task(run_local_bg())
                    renderer.console.print("🚀 [bold green]DAG execution resumed successfully in background (Local).[/bold green]")
                    session.active_suspended_node = None
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to retry node:[/bold red] {e}")
        return True

    elif cmd == "/bypass":
        suspended = getattr(session, "active_suspended_node", None)
        if not suspended:
            renderer.console.print("❌ [bold red]No active suspended node found.[/bold red]")
            return True
            
        dag_id = suspended["dag_id"]
        node_id = suspended["node_id"]
        
        renderer.console.print(f"⏭️ [bold yellow]Bypassing node '{node_id}' in DAG '{dag_id}'...[/bold yellow]")
        
        from src.cli.context import CLIContext, CLIMode
        from src.cli.main import API_BASE_URL
        from src.core.orchestrator.models import NodeColor
        import asyncio
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        try:
            if mode == CLIMode.REMOTE:
                async with ctx.get_http_client() as client:
                    resp = await client.post(
                        f"{API_BASE_URL}/dags/{dag_id}/nodes/{node_id}/action",
                        json={"action": "bypass"},
                        timeout=30
                    )
                    if resp.status_code == 200:
                        renderer.console.print("🚀 [bold green]DAG execution resumed successfully (Bypassed) in background (Remote).[/bold green]")
                        session.active_suspended_node = None
                    else:
                        renderer.console.print(f"❌ [bold red]Remote action failed {resp.status_code}:[/bold red] {resp.text}")
            else:
                # Local mode
                from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk
                from src.core.orchestrator.dag_engine import DAGEngine
                from src.core.skill.service import SkillService
                
                async with ctx.get_db() as db_session:
                    tenant_id = await ctx.resolve_tenant_id(db_session)
                    skill_svc = SkillService(db_session, tenant_id=tenant_id)
                    engine = DAGEngine(skill_svc)
                    
                    dags = load_dags_from_disk(tenant_id=tenant_id)
                    dag = dags.get(dag_id)
                    if not dag:
                        renderer.console.print(f"❌ [bold red]DAG '{dag_id}' not found locally.[/bold red]")
                        return True
                        
                    node = dag.get_node(node_id)
                    if not node:
                        renderer.console.print(f"❌ [bold red]Node '{node_id}' not found in DAG.[/bold red]")
                        return True
                        
                    node.color = NodeColor.GREEN
                    node.error = None
                    node.result = {"output": "Bypassed by user interactive intervention", "trace": {}}
                    dag.status = "running"
                    save_dag_to_disk(dag, tenant_id=tenant_id)
                    
                    # Run background task
                    async def run_local_bg():
                        try:
                            async with ctx.get_db() as new_sess:
                                local_skill_svc = SkillService(new_sess, tenant_id=tenant_id)
                                local_engine = DAGEngine(local_skill_svc)
                                result = await local_engine.execute(dag)
                                save_dag_to_disk(result, tenant_id=tenant_id)
                        except Exception as bg_ex:
                            renderer.console.print(f"\n❌ [bold red]Local background execution failed:[/bold red] {bg_ex}")
                            
                    asyncio.create_task(run_local_bg())
                    renderer.console.print("🚀 [bold green]DAG execution resumed successfully (Bypassed) in background (Local).[/bold green]")
                    session.active_suspended_node = None
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to bypass node:[/bold red] {e}")
        return True

    elif cmd == "/patch":
        suspended = getattr(session, "active_suspended_node", None)
        if not suspended:
            renderer.console.print("❌ [bold red]No active suspended node found.[/bold red]")
            return True
            
        if len(args) < 2:
            renderer.console.print("❌ [bold red]Usage:[/bold red] /patch <file_path> <content>")
            return True
            
        file_path = args[0]
        # Get everything after the file_path in user_input
        prefix_len = len(cmd) + 1 + len(file_path) + 1
        content = user_input[prefix_len:]
        
        dag_id = suspended["dag_id"]
        node_id = suspended["node_id"]
        
        renderer.console.print(f"📝 [bold yellow]Patching file '{file_path}' for node '{node_id}'...[/bold yellow]")
        
        from src.cli.context import CLIContext, CLIMode
        from src.cli.main import API_BASE_URL
        from src.core.orchestrator.models import NodeColor
        import asyncio
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        try:
            if mode == CLIMode.REMOTE:
                async with ctx.get_http_client() as client:
                    resp = await client.post(
                        f"{API_BASE_URL}/dags/{dag_id}/nodes/{node_id}/action",
                        json={
                            "action": "patch",
                            "file_path": file_path,
                            "content": content
                        },
                        timeout=30
                    )
                    if resp.status_code == 200:
                        renderer.console.print("🚀 [bold green]Patch applied and DAG execution resumed successfully (Remote).[/bold green]")
                        session.active_suspended_node = None
                    else:
                        renderer.console.print(f"❌ [bold red]Remote action failed {resp.status_code}:[/bold red] {resp.text}")
            else:
                # Local mode: apply patch locally first
                from src.config import settings
                workspace_path = Path(settings.resolved_workspace_path)
                target_path = Path(file_path)
                if not target_path.is_absolute():
                    target_path = workspace_path / target_path
                    
                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(content, encoding="utf-8")
                    renderer.console.print(f"📝 [bold green]Applied patch to file:[/bold green] [cyan]{file_path}[/cyan]")
                except Exception as e:
                    renderer.console.print(f"❌ [bold red]Failed to write patch file locally:[/bold red] {e}")
                    return True
                    
                # Retry node
                from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk
                from src.core.orchestrator.dag_engine import DAGEngine
                from src.core.skill.service import SkillService
                
                async with ctx.get_db() as db_session:
                    tenant_id = await ctx.resolve_tenant_id(db_session)
                    skill_svc = SkillService(db_session, tenant_id=tenant_id)
                    engine = DAGEngine(skill_svc)
                    
                    dags = load_dags_from_disk(tenant_id=tenant_id)
                    dag = dags.get(dag_id)
                    if not dag:
                        renderer.console.print(f"❌ [bold red]DAG '{dag_id}' not found locally.[/bold red]")
                        return True
                        
                    node = dag.get_node(node_id)
                    if not node:
                        renderer.console.print(f"❌ [bold red]Node '{node_id}' not found in DAG.[/bold red]")
                        return True
                        
                    node.color = NodeColor.GRAY
                    node.error = None
                    dag.status = "running"
                    save_dag_to_disk(dag, tenant_id=tenant_id)
                    
                    # Run background task
                    async def run_local_bg():
                        try:
                            async with ctx.get_db() as new_sess:
                                local_skill_svc = SkillService(new_sess, tenant_id=tenant_id)
                                local_engine = DAGEngine(local_skill_svc)
                                result = await local_engine.execute(dag)
                                save_dag_to_disk(result, tenant_id=tenant_id)
                        except Exception as bg_ex:
                            renderer.console.print(f"\n❌ [bold red]Local background execution failed:[/bold red] {bg_ex}")
                            
                    asyncio.create_task(run_local_bg())
                    renderer.console.print("🚀 [bold green]DAG execution resumed successfully in background (Local) after patch.[/bold green]")
                    session.active_suspended_node = None
        except Exception as e:
            renderer.console.print(f"❌ [bold red]Failed to patch/retry node:[/bold red] {e}")
        return True

    else:
        renderer.console.print(f"❌ [bold red]Unknown command:[/bold red] {cmd}. Type /help for all available commands.")
        return True
