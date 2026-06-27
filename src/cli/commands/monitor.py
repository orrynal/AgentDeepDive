"""Real-time terminal monitoring dashboard for AgentDeepDive CLI."""

import asyncio
import datetime
import json
import os
import select
import sys
import time
from datetime import timezone
from functools import wraps

import click
import httpx
from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from src.cli.context import CLIContext, CLIMode
from src.core.concurrency.lock_manager import lock_manager
from src.core.governance.models import AuditLogModel
from src.database import async_session

console = Console()

def layout_has_node(layout: Layout, name: str) -> bool:
    try:
        layout[name]
        return True
    except KeyError:
        return False

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

# Standard termios/tty for unix non-blocking keyboard input
try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False


async def get_system_health(ctx: CLIContext) -> dict:
    """Check health and ping response times of services."""
    health = {
        "api": "Disconnected",
        "api_ms": None,
        "postgres": "Disconnected",
        "redis": "Disconnected",
        "milvus": "Disconnected",
        "opa": "Disconnected"
    }

    # 1. API Health
    health_url = ctx.api_url.replace("/api/v1", "/health")
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(health_url)
            if resp.status_code == 200:
                health["api"] = "Connected"
                health["api_ms"] = int((time.time() - t0) * 1000)
    except Exception:
        pass

    # 2. PostgreSQL Health
    try:
        from sqlalchemy import text
        async with ctx.get_db() as conn:
            await conn.execute(text("SELECT 1"))
            health["postgres"] = "Connected"
    except Exception:
        pass

    # 3. Redis Health
    try:
        r = ctx.get_async_redis()
        await r.ping()
        health["redis"] = "Connected"
    except Exception:
        pass

    # 4. Milvus Health
    try:
        # Check connection using standard pyamilvus client
        from pymilvus import connections
        if connections.has_connection("default"):
            health["milvus"] = "Connected"
        else:
            connections.connect("default", host="localhost", port="19530", timeout=1.0)
            health["milvus"] = "Connected"
    except Exception:
        pass

    # 5. OPA Health
    try:
        opa_url = "http://localhost:8181/v1/policies"
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(opa_url)
            if resp.status_code == 200:
                health["opa"] = "Connected"
    except Exception:
        pass

    return health


async def get_active_locks() -> list:
    """Fetch active locks from distributed lock manager."""
    try:
        return await lock_manager.list_locks()
    except Exception:
        return []


async def get_agent_pool_status(ctx: CLIContext, is_remote: bool) -> dict:
    """Fetch concurrency pool and agent status."""
    status = {
        "max_concurrency": 10,
        "active_count": 0,
        "agents": []
    }

    if is_remote:
        # Fetch from remote API endpoint
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                resp = await client.get(f"{ctx.api_url.replace('/api/v1', '')}/health/pool")
                if resp.status_code == 200:
                    res = resp.json()
                    status["max_concurrency"] = res.get("max_concurrency", 10)
                    status["active_count"] = res.get("active_count", 0)
                    active_agents = res.get("active_agents", {})
                    for agent_id, task_id in active_agents.items():
                        status["agents"].append({
                            "agent_id": agent_id,
                            "task_id": task_id,
                            "status": "RUNNING",
                            "last_hb": "N/A"
                        })
                    return status
        except Exception:
            pass

    # Local mode or fallback: Scan Redis keys
    try:
        r = ctx.get_async_redis()
        keys = await r.keys("agentdeep:heartbeat:*")
        now = time.time()
        status["max_concurrency"] = 10
        active_cnt = 0
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            agent_id = key.replace("agentdeep:heartbeat:", "")
            val = await r.get(key)
            if val:
                try:
                    ts = float(val)
                    elapsed = now - ts
                    if elapsed < 15.0:
                        active_cnt += 1
                        status["agents"].append({
                            "agent_id": agent_id,
                            "task_id": "Unknown (Local Connect)",
                            "status": "RUNNING",
                            "last_hb": f"{elapsed:.1f}s ago"
                        })
                    else:
                        status["agents"].append({
                            "agent_id": agent_id,
                            "task_id": "-",
                            "status": "STALE/ZOMBIE",
                            "last_hb": f"{elapsed:.1f}s ago"
                        })
                except ValueError:
                    pass
        status["active_count"] = active_cnt
    except Exception:
        pass

    return status


async def get_recent_audits(ctx: CLIContext) -> list:
    """Fetch latest audit log entries for display."""
    try:
        from sqlalchemy import select, desc
        async with async_session() as session:
            query = select(AuditLogModel).order_by(desc(AuditLogModel.timestamp)).limit(6)
            result = await session.execute(query)
            return [item.to_dict() for item in result.scalars().all()]
    except Exception:
        # Local JSONL file fallback
        from src.cli.commands.audit import get_file_audit_logs
        return get_file_audit_logs(None, None, 6)


async def get_scheduler_tasks(ctx: CLIContext, is_remote: bool) -> list:
    """Fetch registered scheduled tasks and their execution status."""
    if is_remote:
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                resp = await client.get(f"{ctx.api_url}/schedules", headers=headers, timeout=1.5)
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return []

    # Local mode: Direct query database and scheduler manager
    from sqlalchemy import select
    from src.core.scheduler.models import ScheduledTaskModel
    from src.core.scheduler.manager import scheduler_manager
    try:
        async with ctx.get_db() as session:
            tenant_id = await ctx.resolve_tenant_id(session)
            result = await session.execute(
                select(ScheduledTaskModel).where(ScheduledTaskModel.tenant_id == tenant_id)
            )
            tasks = []
            for t in result.scalars().all():
                d = t.to_dict()
                scheduler = getattr(scheduler_manager, "scheduler", None)
                job = None
                if scheduler and hasattr(scheduler, "get_job") and type(scheduler).__name__ not in ("Mock", "MagicMock", "AsyncMock"):
                    try:
                        job = scheduler.get_job(str(t.id))
                    except Exception:
                        pass
                if job and job.next_run_time:
                    d["next_run_time"] = job.next_run_time.isoformat()
                else:
                    d["next_run_time"] = None
                tasks.append(d)
            return tasks
    except Exception:
        return []


def make_layout(show_locks: bool = True, show_audits: bool = True, show_schedules: bool = True) -> Layout:
    """Initialize the layout framework."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )

    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right")
    )

    # Left column panels
    left_layouts = [Layout(name="system_status", ratio=1)]
    if show_locks:
        left_layouts.append(Layout(name="active_locks", ratio=2))
    layout["left"].split_column(*left_layouts)

    # Right column panels
    right_layouts = [Layout(name="agent_pool", ratio=1)]
    if show_schedules:
        right_layouts.append(Layout(name="scheduler_tasks", ratio=2))
    if show_audits:
        right_layouts.append(Layout(name="recent_audits", ratio=2))
    layout["right"].split_column(*right_layouts)

    return layout


async def keyboard_input_loop(q: asyncio.Queue):
    """Read keystrokes in a separate loop without blocking asyncio."""
    if not HAS_TERMIOS or not sys.stdin.isatty():
        # Fallback for non-TTY
        while True:
            await asyncio.sleep(1.0)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            # Check if stdin is readable (timeout 0.1s)
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if rlist:
                key = sys.stdin.read(1)
                await q.put(key)
                if key == 'q':
                    break
            await asyncio.sleep(0.02)
    except Exception:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@click.command(name="monitor")
@click.option("--interval", "-i", default=2.0, type=float, help="Refresh interval in seconds.")
@click.pass_context
@coro
async def monitor_command(click_ctx, interval: float):
    """Start the real-time terminal monitoring dashboard."""
    # Suppress SQLAlchemy log noise that ruins TUI rendering
    import logging
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    ctx = click_ctx.obj or CLIContext()
    
    # Enable Unix screen buffer alternative
    console.print("[yellow]Starting dashboard...[/yellow]")
    
    key_queue = asyncio.Queue()
    asyncio.create_task(keyboard_input_loop(key_queue))

    show_locks = True
    show_audits = True
    show_schedules = True
    
    # State tracking
    mode = ctx.resolved_mode
    is_remote = (mode == CLIMode.REMOTE)

    # Initialize layout
    layout = make_layout(show_locks, show_audits, show_schedules)

    schedules = []
    status_msg = ""
    status_msg_expires = 0.0

    with Live(layout, refresh_per_second=4, screen=True) as live:
        while True:
            # Check message expiration
            if status_msg and time.time() > status_msg_expires:
                status_msg = ""

            # 1. Check keyboard queue
            while not key_queue.empty():
                key = key_queue.get_nowait()
                if key == 'q':
                    return
                elif key == 'r':
                    # Force immediate refresh
                    pass
                elif key == 'l':
                    show_locks = not show_locks
                    layout = make_layout(show_locks, show_audits, show_schedules)
                    live.update(layout)
                elif key == 'a':
                    show_audits = not show_audits
                    layout = make_layout(show_locks, show_audits, show_schedules)
                    live.update(layout)
                elif key == 's':
                    show_schedules = not show_schedules
                    layout = make_layout(show_locks, show_audits, show_schedules)
                    live.update(layout)
                elif key.isdigit() and '1' <= key <= '9':
                    idx = int(key) - 1
                    if schedules and 0 <= idx < len(schedules):
                        task = schedules[idx]
                        task_id = task.get("id")
                        task_desc = task.get("task_description")
                        task_name = task.get("name")
                        if is_remote:
                            try:
                                async with ctx.get_http_client() as client:
                                    headers = ctx.get_auth_headers()
                                    resp = await client.post(
                                        f"{ctx.api_url}/schedules/{task_id}/trigger",
                                        headers=headers,
                                        timeout=2.0
                                    )
                                    if resp.status_code == 200:
                                        status_msg = f"✔ Triggered '{task_name}'"
                                    else:
                                        status_msg = f"❌ Failed: {resp.text[:30]}"
                            except Exception as trigger_err:
                                status_msg = f"❌ Conn error: {str(trigger_err)[:30]}"
                        else:
                            try:
                                from src.core.scheduler.manager import execute_scheduled_task
                                asyncio.create_task(execute_scheduled_task(task_desc, task_id))
                                status_msg = f"✔ Triggered '{task_name}'"
                            except Exception as trigger_err:
                                status_msg = f"❌ Local error: {str(trigger_err)[:30]}"
                        status_msg_expires = time.time() + 4.0

            # 2. Gather data
            mode = await ctx.detect_mode_async()
            is_remote = (mode == CLIMode.REMOTE)
            
            health_task = asyncio.create_task(get_system_health(ctx))
            locks_task = asyncio.create_task(get_active_locks())
            pool_task = asyncio.create_task(get_agent_pool_status(ctx, is_remote))
            audits_task = asyncio.create_task(get_recent_audits(ctx))
            schedules_task = asyncio.create_task(get_scheduler_tasks(ctx, is_remote))
            
            health, locks, pool_info, audits, schedules = await asyncio.gather(
                health_task, locks_task, pool_task, audits_task, schedules_task
            )

            # 3. Build Header Panel
            time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mode_color = "green" if is_remote else "yellow"
            header_table = Table.grid(expand=True)
            header_table.add_column(justify="left", ratio=1)
            header_table.add_column(justify="right", ratio=1)
            header_table.add_row(
                f"[bold cyan]🤖 AgentDeepDive System Real-time Monitor[/bold cyan]",
                f"[dim]Time:[/dim] {time_str}  |  [dim]Mode:[/dim] [{mode_color}]{mode.upper()}[/{mode_color}]"
            )
            layout["header"].update(Panel(header_table, border_style="blue"))

            # 4. Build System Status Panel
            if layout_has_node(layout, "system_status"):
                status_table = Table(show_header=True, expand=True, box=None)
                status_table.add_column("Service/Component", style="cyan")
                status_table.add_column("Status", justify="right")
                
                def fmt_status(val, extra=""):
                    return f"[green]✔ Active{extra}[/green]" if val == "Connected" else "[red]✘ Offline[/red]"
                
                api_extra = f" ({health['api_ms']}ms)" if health["api_ms"] is not None else ""
                status_table.add_row("API Gateway Service", fmt_status(health["api"], api_extra))
                status_table.add_row("PostgreSQL Database", fmt_status(health["postgres"]))
                status_table.add_row("Redis Cache/Broker", fmt_status(health["redis"]))
                status_table.add_row("Milvus Vector Store", fmt_status(health["milvus"]))
                status_table.add_row("Open Policy Agent (OPA)", fmt_status(health["opa"]))
                
                layout["system_status"].update(Panel(status_table, title="🔌 Connection Health Status", border_style="cyan"))

            # 5. Build Active Locks Panel
            if layout_has_node(layout, "active_locks"):
                locks_table = Table(show_header=True, expand=True)
                locks_table.add_column("Resource/File Key", style="cyan")
                locks_table.add_column("Holder Agent", style="magenta")
                locks_table.add_column("Priority", justify="right")
                locks_table.add_column("TTL Left", justify="right")

                if not locks:
                    layout["active_locks"].update(Panel(Align.center("[dim]No active concurrency locks registered.[/dim]", vertical="middle"), title="🔒 Distributed Locks Registry", border_style="magenta"))
                else:
                    for l in locks:
                        now = time.time()
                        elapsed = now - l.acquired_at
                        ttl_left = max(0, int(l.ttl_sec - elapsed))
                        locks_table.add_row(
                            l.file_path,
                            l.holder_agent,
                            str(l.priority),
                            f"{ttl_left}s"
                        )
                    layout["active_locks"].update(Panel(locks_table, title="🔒 Distributed Locks Registry", border_style="magenta"))

            # 6. Build Agent Pool Panel
            if layout_has_node(layout, "agent_pool"):
                pool_table = Table(show_header=True, expand=True, box=None)
                pool_table.add_column("Stat/Metric", style="cyan")
                pool_table.add_column("Value", justify="right")

                pool_table.add_row("Max Concurrency", str(pool_info["max_concurrency"]))
                pool_table.add_row("Active Worker Slots", f"[bold yellow]{pool_info['active_count']}[/bold yellow]")
                
                layout["agent_pool"].update(Panel(pool_table, title="👥 Agent Concurrency Pool Status", border_style="yellow"))

            # 6.5. Build Scheduler Tasks Panel
            if layout_has_node(layout, "scheduler_tasks"):
                sched_table = Table(show_header=True, expand=True)
                sched_table.add_column("#", style="bold yellow", justify="center")
                sched_table.add_column("Task Name", style="cyan")
                sched_table.add_column("Cron Expr", style="magenta")
                sched_table.add_column("Last Run", justify="right")
                sched_table.add_column("Next Run", justify="right")
                sched_table.add_column("Status", justify="center")

                if not schedules:
                    layout["scheduler_tasks"].update(Panel(Align.center("[dim]No scheduled tasks registered.[/dim]", vertical="middle"), title="⏰ Background Scheduler Status", border_style="blue"))
                else:
                    for idx, t in enumerate(schedules):
                        # Format last run time
                        last_run = t.get("last_run_time")
                        if last_run:
                            try:
                                dt = datetime.datetime.fromisoformat(last_run)
                                last_run_str = dt.strftime("%H:%M:%S")
                            except Exception:
                                last_run_str = str(last_run)[:16]
                        else:
                            last_run_str = "-"

                        # Format next run time
                        next_run = t.get("next_run_time")
                        if next_run:
                            try:
                                dt = datetime.datetime.fromisoformat(next_run)
                                next_run_str = dt.strftime("%H:%M:%S")
                            except Exception:
                                next_run_str = str(next_run)[:16]
                        else:
                            next_run_str = "-"

                        # Format status
                        is_active = t.get("is_active", True)
                        run_status = t.get("last_run_status")
                        
                        if not is_active:
                            status_str = "[red]Inactive[/red]"
                        elif run_status == "RUNNING":
                            status_str = "[yellow]Running[/yellow]"
                        elif run_status == "SUCCESS":
                            status_str = "[green]Success[/green]"
                        elif run_status == "FAILED":
                            status_str = "[red]Failed[/red]"
                        else:
                            status_str = "[green]Active[/green]"

                        sched_table.add_row(
                            str(idx + 1),
                            t.get("name") or "-",
                            t.get("cron_expression") or "-",
                            last_run_str,
                            next_run_str,
                            status_str
                        )
                    layout["scheduler_tasks"].update(Panel(sched_table, title="⏰ Background Scheduler Status", border_style="blue"))

            # 7. Build Active Agents details or Audit log panel
            if layout_has_node(layout, "recent_audits"):
                audit_table = Table(show_header=True, expand=True)
                audit_table.add_column("Time", style="cyan")
                audit_table.add_column("Event Type", style="magenta")
                audit_table.add_column("Agent ID", style="bold green")
                audit_table.add_column("Summary Details")

                for log in audits:
                    ts = log.get("timestamp")
                    if ts:
                        try:
                            dt = datetime.datetime.fromisoformat(ts)
                            ts_formatted = dt.strftime("%H:%M:%S")
                        except Exception:
                            ts_formatted = str(ts)[:16]
                    else:
                        ts_formatted = "-"
                    
                    details = log.get("details") or {}
                    details_str = json.dumps(details, ensure_ascii=False)
                    if len(details_str) > 40:
                        details_str = details_str[:37] + "..."

                    audit_table.add_row(
                        ts_formatted,
                        log.get("event_type") or "-",
                        log.get("agent_id") or "-",
                        details_str
                    )
                layout["recent_audits"].update(Panel(audit_table, title="🛡️ Recent Governance Audits", border_style="green"))

            # 8. Build Footer Panel
            footer_text = (
                "[bold]Controls:[/bold] [bold cyan][q][/bold cyan] Quit  |  "
                "[bold cyan][r][/bold cyan] Refresh  |  "
                "[bold cyan][1-9][/bold cyan] Trigger Task  |  "
                f"[bold cyan][l][/bold cyan] Toggle Locks ({'ON' if show_locks else 'OFF'})  |  "
                f"[bold cyan][s][/bold cyan] Toggle Schedules ({'ON' if show_schedules else 'OFF'})  |  "
                f"[bold cyan][a][/bold cyan] Toggle Audits ({'ON' if show_audits else 'OFF'})"
            )
            if status_msg:
                footer_text = f"[bold green]{status_msg}[/bold green]  |  " + footer_text
            layout["footer"].update(Panel(Align.center(footer_text, vertical="middle"), border_style="blue"))

            # Sleep or wait for interval / key press
            await asyncio.sleep(interval)
