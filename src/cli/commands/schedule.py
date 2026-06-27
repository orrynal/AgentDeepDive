"""Scheduling command group for AgentDeepDive CLI."""

import click
import httpx
import asyncio
from functools import wraps
from rich.console import Console
from rich.table import Table

from src.cli.context import CLIContext, CLIMode

import sys
console = Console(width=120 if not sys.stdout.isatty() else None)
API_BASE_URL = "http://localhost:8000/api/v1"

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group(name="schedule")
def schedule_group():
    """Manage cron schedules for background tasks."""
    pass

@schedule_group.command(name="list")
@coro
async def schedule_list():
    """List all registered scheduled tasks."""
    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    if mode == CLIMode.REMOTE:
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                resp = await client.get(f"{API_BASE_URL}/schedules", headers=headers, timeout=10)
                if resp.status_code == 200:
                    tasks = resp.json()
                    _print_schedules_table(tasks, "Remote")
                else:
                    console.print(f"[red]❌ Failed to retrieve schedules ({resp.status_code}): {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
    else:
        # Local direct database query
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
                    job = scheduler_manager.scheduler.get_job(str(t.id))
                    if job and job.next_run_time:
                        d["next_run_time"] = job.next_run_time.isoformat()
                    else:
                        d["next_run_time"] = None
                    tasks.append(d)
                _print_schedules_table(tasks, "Local")
        except Exception as e:
            console.print(f"[red]❌ Local database error: {e}[/red]")

def _print_schedules_table(tasks: list[dict], mode_str: str):
    if not tasks:
        console.print(f"[dim]No scheduled tasks registered yet ({mode_str}).[/dim]")
        return

    table = Table(title=f"Scheduled Background Tasks ({mode_str})")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold", no_wrap=True)
    table.add_column("Cron Expression", style="magenta", no_wrap=True)
    table.add_column("Last Run", justify="right", no_wrap=True)
    table.add_column("Next Run", justify="right", no_wrap=True)
    table.add_column("Status", style="bold", no_wrap=True)
    table.add_column("Task Description")

    for t in tasks:
        # Format last run
        last_run = t.get("last_run_time")
        last_run_str = last_run[:19].replace("T", " ") if last_run else "-"

        # Format next run
        next_run = t.get("next_run_time")
        next_run_str = next_run[:19].replace("T", " ") if next_run else "-"

        # Format status
        is_active = t.get("is_active", True)
        run_status = t.get("last_run_status")
        
        if not is_active:
            status_str = "[red]🔴 Inactive[/red]"
        elif run_status == "RUNNING":
            status_str = "[yellow]🟡 Running[/yellow]"
        elif run_status == "SUCCESS":
            status_str = "[green]🟢 Success[/green]"
        elif run_status == "FAILED":
            status_str = "[red]🔴 Failed[/red]"
        else:
            status_str = "[green]🟢 Active[/green]"

        table.add_row(
            t["id"],
            t["name"],
            t["cron_expression"],
            last_run_str,
            next_run_str,
            status_str,
            t["task_description"]
        )
    console.print(table)


@schedule_group.command(name="add")
@click.option("--name", "-n", required=True, help="Unique name of the schedule")
@click.option("--cron", "-c", required=True, help="Standard cron expression (e.g., '0 * * * *')")
@click.option("--task", "-t", "task_description", required=True, help="Task description to execute on schedule")
@coro
async def schedule_add(name: str, cron: str, task_description: str):
    """Register a new scheduled task."""
    # Basic validation of cron expression
    from apscheduler.triggers.cron import CronTrigger
    try:
        CronTrigger.from_crontab(cron)
    except Exception as e:
        console.print(f"[red]❌ Invalid cron expression '{cron}': {e}[/red]")
        return

    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    if mode == CLIMode.REMOTE:
        payload = {
            "name": name,
            "cron_expression": cron,
            "task_description": task_description,
            "is_active": True
        }
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                resp = await client.post(f"{API_BASE_URL}/schedules", json=payload, headers=headers, timeout=10)
                if resp.status_code in (200, 201):
                    res = resp.json()
                    console.print(f"[green]✔ Successfully registered scheduled task '{name}' remotely![/green]")
                    console.print(f"Schedule ID: [cyan]{res['id']}[/cyan]")
                else:
                    console.print(f"[red]❌ Registration failed ({resp.status_code}): {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
    else:
        # Local direct database insertion
        from sqlalchemy import select
        from src.core.scheduler.models import ScheduledTaskModel
        from src.core.scheduler.manager import scheduler_manager
        try:
            async with ctx.get_db() as session:
                tenant_id = await ctx.resolve_tenant_id(session)
                
                # Check uniqueness
                result = await session.execute(
                    select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.name == name
                    )
                )
                if result.scalar_one_or_none():
                    console.print(f"[red]❌ Schedule with name '{name}' already exists.[/red]")
                    return
                
                task = ScheduledTaskModel(
                    tenant_id=tenant_id,
                    name=name,
                    task_description=task_description,
                    cron_expression=cron,
                    is_active=True
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                
                scheduler_manager.register_task(task)
                console.print(f"[green]✔ Successfully registered scheduled task '{name}' locally![/green]")
                console.print(f"Schedule ID: [cyan]{task.id}[/cyan]")
        except Exception as e:
            console.print(f"[red]❌ Database operation failed: {e}[/red]")


@schedule_group.command(name="delete")
@click.argument("schedule_id_or_name")
@coro
async def schedule_delete(schedule_id_or_name: str):
    """Delete a scheduled task by ID or Name."""
    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    
    # Try parsing UUID
    import uuid
    is_uuid = False
    try:
        uuid_val = uuid.UUID(schedule_id_or_name)
        is_uuid = True
    except ValueError:
        pass

    if mode == CLIMode.REMOTE:
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                
                target_id = schedule_id_or_name
                if not is_uuid:
                    # Look up by name first
                    resp_list = await client.get(f"{API_BASE_URL}/schedules", headers=headers, timeout=10)
                    if resp_list.status_code == 200:
                        matched = [t for t in resp_list.json() if t["name"] == schedule_id_or_name]
                        if not matched:
                            console.print(f"[red]❌ Schedule with name '{schedule_id_or_name}' not found.[/red]")
                            return
                        target_id = matched[0]["id"]
                    else:
                        console.print(f"[red]❌ Failed to fetch schedules: {resp_list.text}[/red]")
                        return
                
                resp = await client.delete(f"{API_BASE_URL}/schedules/{target_id}", headers=headers, timeout=10)
                if resp.status_code == 200:
                    console.print(f"[green]✔ Successfully deleted scheduled task '{schedule_id_or_name}' remotely.[/green]")
                else:
                    console.print(f"[red]❌ Delete failed ({resp.status_code}): {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
    else:
        # Local direct database delete
        from sqlalchemy import select
        from src.core.scheduler.models import ScheduledTaskModel
        from src.core.scheduler.manager import scheduler_manager
        try:
            async with ctx.get_db() as session:
                tenant_id = await ctx.resolve_tenant_id(session)
                
                if is_uuid:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.id == uuid_val
                    )
                else:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.name == schedule_id_or_name
                    )
                
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()
                if not task:
                    console.print(f"[red]❌ Schedule '{schedule_id_or_name}' not found locally.[/red]")
                    return
                
                task_id_str = str(task.id)
                scheduler_manager.remove_task(task_id_str)
                await session.delete(task)
                await session.commit()
                console.print(f"[green]✔ Successfully deleted scheduled task '{schedule_id_or_name}' locally.[/green]")
        except Exception as e:
            console.print(f"[red]❌ Database operation failed: {e}[/red]")


@schedule_group.command(name="toggle")
@click.argument("schedule_id_or_name")
@click.option("--active/--inactive", default=None, required=True, help="Enable or disable the schedule")
@coro
async def schedule_toggle(schedule_id_or_name: str, active: bool):
    """Enable or disable a scheduled task."""
    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    
    import uuid
    is_uuid = False
    try:
        uuid_val = uuid.UUID(schedule_id_or_name)
        is_uuid = True
    except ValueError:
        pass

    if mode == CLIMode.REMOTE:
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                
                target_id = schedule_id_or_name
                if not is_uuid:
                    # Look up by name first
                    resp_list = await client.get(f"{API_BASE_URL}/schedules", headers=headers, timeout=10)
                    if resp_list.status_code == 200:
                        matched = [t for t in resp_list.json() if t["name"] == schedule_id_or_name]
                        if not matched:
                            console.print(f"[red]❌ Schedule with name '{schedule_id_or_name}' not found.[/red]")
                            return
                        target_id = matched[0]["id"]
                    else:
                        console.print(f"[red]❌ Failed to fetch schedules: {resp_list.text}[/red]")
                        return
                
                payload = {"is_active": active}
                resp = await client.put(f"{API_BASE_URL}/schedules/{target_id}", json=payload, headers=headers, timeout=10)
                if resp.status_code == 200:
                    status_str = "enabled" if active else "disabled"
                    console.print(f"[green]✔ Successfully {status_str} scheduled task '{schedule_id_or_name}' remotely.[/green]")
                else:
                    console.print(f"[red]❌ Update failed ({resp.status_code}): {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
    else:
        # Local direct database update
        from sqlalchemy import select
        from src.core.scheduler.models import ScheduledTaskModel
        from src.core.scheduler.manager import scheduler_manager
        try:
            async with ctx.get_db() as session:
                tenant_id = await ctx.resolve_tenant_id(session)
                
                if is_uuid:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.id == uuid_val
                    )
                else:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.name == schedule_id_or_name
                    )
                
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()
                if not task:
                    console.print(f"[red]❌ Schedule '{schedule_id_or_name}' not found locally.[/red]")
                    return
                
                task.is_active = active
                await session.commit()
                
                if active:
                    scheduler_manager.register_task(task)
                else:
                    scheduler_manager.remove_task(str(task.id))
                    
                status_str = "enabled" if active else "disabled"
                console.print(f"[green]✔ Successfully {status_str} scheduled task '{schedule_id_or_name}' locally.[/green]")
        except Exception as e:
            console.print(f"[red]❌ Database operation failed: {e}[/red]")


@schedule_group.command(name="trigger")
@click.argument("schedule_id_or_name")
@click.option("--force", "-f", is_flag=True, help="Force execution, bypassing the resource circuit breaker.")
@coro
async def schedule_trigger(schedule_id_or_name: str, force: bool):
    """Trigger a scheduled task immediately in the background."""
    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    
    import uuid
    is_uuid = False
    try:
        uuid_val = uuid.UUID(schedule_id_or_name)
        is_uuid = True
    except ValueError:
        pass

    if mode == CLIMode.REMOTE:
        try:
            async with ctx.get_http_client() as client:
                headers = ctx.get_auth_headers()
                
                target_id = schedule_id_or_name
                if not is_uuid:
                    # Look up by name first
                    resp_list = await client.get(f"{API_BASE_URL}/schedules", headers=headers, timeout=10)
                    if resp_list.status_code == 200:
                        matched = [t for t in resp_list.json() if t["name"] == schedule_id_or_name]
                        if not matched:
                            console.print(f"[red]❌ Schedule with name '{schedule_id_or_name}' not found.[/red]")
                            return
                        target_id = matched[0]["id"]
                    else:
                        console.print(f"[red]❌ Failed to fetch schedules: {resp_list.text}[/red]")
                        return
                
                resp = await client.post(
                    f"{API_BASE_URL}/schedules/{target_id}/trigger",
                    params={"force": force},
                    headers=headers,
                    timeout=10
                )
                if resp.status_code == 200:
                    console.print(f"[green]✔ Successfully triggered scheduled task '{schedule_id_or_name}' remotely in background.[/green]")
                else:
                    console.print(f"[red]❌ Trigger failed ({resp.status_code}): {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]❌ Connection failed: {e}[/red]")
    else:
        # Local direct database lookup and trigger
        from sqlalchemy import select
        from src.core.scheduler.models import ScheduledTaskModel
        from src.core.scheduler.manager import execute_scheduled_task
        from src.core.governance.circuit_breaker import resource_circuit_breaker
        try:
            async with ctx.get_db() as session:
                tenant_id = await ctx.resolve_tenant_id(session)
                
                if is_uuid:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.id == uuid_val
                    )
                else:
                    stmt = select(ScheduledTaskModel).where(
                        ScheduledTaskModel.tenant_id == tenant_id,
                        ScheduledTaskModel.name == schedule_id_or_name
                    )
                
                result = await session.execute(stmt)
                task = result.scalar_one_or_none()
                if not task:
                    console.print(f"[red]❌ Schedule '{schedule_id_or_name}' not found locally.[/red]")
                    return
                
                # Check circuit breaker locally
                allowed, reason = await resource_circuit_breaker.allow_execution(
                    task.task_description, str(task.id), is_manual=True, force=force
                )
                if not allowed:
                    console.print(f"[red]❌ Circuit Breaker blocked manual trigger: {reason}[/red]")
                    return
                
                # Execute asynchronously
                asyncio.create_task(execute_scheduled_task(task.task_description, str(task.id), force=force))
                console.print(f"[green]✔ Successfully triggered scheduled task '{schedule_id_or_name}' locally in background.[/green]")
                # Yield to let the task start executing
                await asyncio.sleep(0.1)
        except Exception as e:
            console.print(f"[red]❌ Database operation failed: {e}[/red]")


