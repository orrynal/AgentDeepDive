"""Lock management command group for AgentDeepDive CLI."""

import time
import click
import asyncio
from functools import wraps
from rich.console import Console
from rich.table import Table
from src.core.concurrency.lock_manager import lock_manager
from src.core.redis_pool import get_async_redis_client

console = Console()

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group(name="lock")
def lock_group():
    """Manage file concurrency locks and preemption."""
    pass

@lock_group.command(name="list")
@coro
async def lock_list():
    """List all active concurrency locks."""
    console.print("[yellow]⏳ Fetching active locks from Redis...[/yellow]")
    try:
        locks = await lock_manager.list_locks()
        if not locks:
            console.print("[green]No active locks found.[/green]")
            return

        table = Table(title="Active Concurrency Locks")
        table.add_column("File Path", style="cyan")
        table.add_column("Holder Agent", style="magenta")
        table.add_column("Task ID", style="dim")
        table.add_column("Priority", justify="right")
        table.add_column("Acquired At", justify="center")
        table.add_column("TTL Left", justify="right")

        for l in locks:
            # Format acquired_at timestamp to local time
            acq_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(l.acquired_at))
            
            # Calculate remaining TTL
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
        console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error listing locks: {e}[/red]")

@lock_group.command(name="show")
@click.argument("file_path")
@coro
async def lock_show(file_path: str):
    """Show details of a specific lock."""
    try:
        info = await lock_manager.get_lock_info(file_path)
        if not info:
            console.print(f"[yellow]No active lock found for file: '{file_path}'[/yellow]")
            return

        acq_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(info.acquired_at))
        now = time.time()
        elapsed = now - info.acquired_at
        ttl_left = max(0, int(info.ttl_sec - elapsed))

        table = Table(show_header=False, title=f"Lock Details: {file_path}")
        table.add_row("File Path", info.file_path)
        table.add_row("Holder Agent", info.holder_agent)
        table.add_row("Task ID", info.task_id or "-")
        table.add_row("Priority", str(info.priority))
        table.add_row("Acquired At", acq_time)
        table.add_row("TTL Left", f"{ttl_left}s / {info.ttl_sec}s")
        table.add_row("Version", info.version)

        console.print(table)
    except Exception as e:
        console.print(f"[red]❌ Error showing lock details: {e}[/red]")

@lock_group.command(name="release")
@click.argument("file_path")
@click.argument("agent_id")
@click.confirmation_option(prompt="Are you sure you want to force release this lock?")
@coro
async def lock_release(file_path: str, agent_id: str):
    """Force release a lock on a file."""
    try:
        next_holder = await lock_manager.release(file_path, agent_id)
        if next_holder:
            console.print(f"[green]✔ Lock released and promoted to next agent in queue: {next_holder}[/green]")
        else:
            console.print(f"[green]✔ Lock released successfully.[/green]")
    except Exception as e:
        console.print(f"[red]❌ Error releasing lock: {e}[/red]")

@lock_group.command(name="clean")
@click.option("--stale", is_flag=True, help="Clean locks held by crashed/inactive agents (based on heartbeat).")
@click.option("--agent", "agent_id", help="Clean all locks held by a specific agent.")
@click.confirmation_option(prompt="Are you sure you want to clean up matching locks?")
@coro
async def lock_clean(stale: bool, agent_id: str | None):
    """Clean up active locks based on criteria."""
    if not stale and not agent_id:
        console.print("[red]Error: Must specify either --stale or --agent <agent_id>[/red]")
        return

    try:
        if agent_id:
            console.print(f"[yellow]⏳ Releasing all locks held by agent '{agent_id}'...[/yellow]")
            await lock_manager.release_all_for_agent(agent_id)
            console.print(f"[green]✔ Locks held by agent '{agent_id}' cleaned successfully.[/green]")
            return

        if stale:
            console.print("[yellow]⏳ Scanning for stale locks (crashed or timed-out heartbeats)...[/yellow]")
            r = get_async_redis_client()
            locks = await lock_manager.list_locks()
            cleaned_count = 0
            
            for l in locks:
                # Check agent heartbeat in Redis
                hb_key = f"agentdeep:heartbeat:{l.holder_agent}"
                hb_val = await r.get(hb_key)
                
                is_stale = False
                if not hb_val:
                    is_stale = True
                else:
                    try:
                        hb_ts = float(hb_val)
                        if time.time() - hb_ts > 15.0: # Heartbeat timeout threshold (15s)
                            is_stale = True
                    except ValueError:
                        is_stale = True

                if is_stale:
                    console.print(f"[red]⚠️ Stale lock detected on '{l.file_path}' (Agent '{l.holder_agent}' heartbeat missing/expired)[/red]")
                    await lock_manager.release(l.file_path, l.holder_agent)
                    cleaned_count += 1
            
            if cleaned_count > 0:
                console.print(f"[green]✔ Cleaned {cleaned_count} stale lock(s).[/green]")
            else:
                console.print("[green]No stale locks found.[/green]")

    except Exception as e:
        console.print(f"[red]❌ Error cleaning locks: {e}[/red]")
