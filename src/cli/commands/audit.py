"""Audit log management command group for AgentDeepDive CLI."""

import csv
import json
import os
import time
import click
import asyncio
from functools import wraps
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
from sqlalchemy import select, desc, delete
from src.database import async_session
from src.core.governance.models import AuditLogModel
from src.core.governance.audit import AUDIT_LOG_FILE, audit_logger
from src.cli.context import CLIContext

console = Console()

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

async def get_db_audit_logs(event_type: str | None, agent_id: str | None, limit: int, tenant_id: str) -> list[dict]:
    """Retrieve audit logs from the PostgreSQL database, filtered by tenant."""
    async with async_session() as session:
        query = select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_id).order_by(desc(AuditLogModel.timestamp))
        if event_type:
            query = query.where(AuditLogModel.event_type == event_type)
        if agent_id:
            query = query.where(AuditLogModel.agent_id == agent_id)
        query = query.limit(limit)
        
        result = await session.execute(query)
        return [item.to_dict() for item in result.scalars().all()]

def get_file_audit_logs(event_type: str | None, agent_id: str | None, limit: int, tenant_id: str) -> list[dict]:
    """Fall back to reading audit logs from the local JSONL log file, filtered by tenant."""
    if not os.path.exists(AUDIT_LOG_FILE):
        return []
        
    records = []
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    # Filter by tenant
                    if rec.get("tenant_id") != tenant_id:
                        continue
                    # Normalize structure to match model to_dict
                    ts_float = rec.get("timestamp")
                    if ts_float:
                        rec["timestamp"] = datetime.fromtimestamp(ts_float, tz=timezone.utc).isoformat()
                    
                    # Apply filters
                    if event_type and rec.get("event_type") != event_type:
                        continue
                    if agent_id and rec.get("agent_id") != agent_id:
                        continue
                        
                    records.append(rec)
                except Exception:
                    pass
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to read local audit file: {e}[/yellow]")

    # Sort by timestamp descending
    records.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return records[:limit]

async def fetch_audit_logs(event_type: str | None, agent_id: str | None, limit: int, tenant_id: str) -> tuple[list[dict], str]:
    """Fetch logs from DB with transparent fallback to local JSONL file."""
    try:
        logs = await get_db_audit_logs(event_type, agent_id, limit, tenant_id)
        return logs, "Database (Active)"
    except Exception as db_err:
        console.print(f"[yellow]⚠️ Database query failed ({db_err}). Falling back to local audit log file...[/yellow]")
        logs = get_file_audit_logs(event_type, agent_id, limit, tenant_id)
        return logs, f"Local Log File Fallback ({AUDIT_LOG_FILE})"

@click.group(name="audit")
def audit_group():
    """Query and export security & governance audit logs."""
    pass

@audit_group.command(name="list")
@click.option("--event-type", "-e", help="Filter by event type (e.g. tool_invoke, classification).")
@click.option("--agent", "-a", "agent_id", help="Filter by agent ID.")
@click.option("--limit", "-l", default=20, type=int, help="Maximum number of log entries to display.")
@coro
async def audit_list(event_type: str | None, agent_id: str | None, limit: int):
    """List recent governance audit logs with automatic database/file fallback."""
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)
        
    logs, source = await fetch_audit_logs(event_type, agent_id, limit, tenant_id)
    
    if not logs:
        console.print("[yellow]No audit logs found matching the criteria.[/yellow]")
        return

    table = Table(title=f"Security Audit Logs (Tenant: {tenant_id} | Source: {source})")
    table.add_column("Timestamp", style="cyan", justify="center")
    table.add_column("Event Type", style="magenta")
    table.add_column("Agent ID", style="bold green")
    table.add_column("Task ID", style="dim")
    table.add_column("Details Summary", width=60)

    for item in logs:
        ts = item.get("timestamp")
        # Format TS string
        if ts:
            try:
                # e.g., 2026-06-13T06:52:20+00:00 -> 06-13 06:52:20
                dt = datetime.fromisoformat(ts)
                ts_formatted = dt.strftime("%m-%d %H:%M:%S")
            except Exception:
                ts_formatted = str(ts)[:16]
        else:
            ts_formatted = "-"

        # Summarize details dict
        details = item.get("details") or {}
        details_str = json.dumps(details, ensure_ascii=False)
        if len(details_str) > 60:
            details_str = details_str[:57] + "..."

        table.add_row(
            ts_formatted,
            item.get("event_type") or "-",
            item.get("agent_id") or "-",
            item.get("task_id") or "-",
            details_str
        )

    console.print(table)

@audit_group.command(name="export")
@click.option("--event-type", "-e", help="Filter by event type.")
@click.option("--agent", "-a", "agent_id", help="Filter by agent ID.")
@click.option("--limit", "-l", default=1000, type=int, help="Maximum number of entries to export.")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Export file format.")
@click.option("--output", "-o", default="audit_export.csv", help="Output file path.")
@coro
async def audit_export(event_type: str | None, agent_id: str | None, limit: int, format: str, output: str):
    """Export audit logs to a CSV or JSON file."""
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)
        
    logs, source = await fetch_audit_logs(event_type, agent_id, limit, tenant_id)
    
    if not logs:
        console.print("[yellow]No audit logs found to export.[/yellow]")
        return

    console.print(f"[yellow]⏳ Exporting {len(logs)} logs from {source} to '{output}'...[/yellow]")
    
    try:
        if format == "json":
            with open(output, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
        else:
            # CSV export
            if not output.endswith(".csv") and output == "audit_export.csv":
                pass
            with open(output, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                # Header
                writer.writerow(["ID", "Tenant ID", "Timestamp", "Event Type", "Agent ID", "Task ID", "Details"])
                for item in logs:
                    writer.writerow([
                        item.get("id") or "-",
                        item.get("tenant_id") or "-",
                        item.get("timestamp") or "-",
                        item.get("event_type") or "-",
                        item.get("agent_id") or "-",
                        item.get("task_id") or "-",
                        json.dumps(item.get("details") or {})
                    ])
        console.print(f"[green]✔ Export completed successfully! Saved to '{output}'[/green]")
    except Exception as e:
        console.print(f"[red]❌ Error exporting logs: {e}[/red]")

@audit_group.command(name="stats")
@coro
async def audit_stats():
    """Display overall audit statistics and security classifications summary."""
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)
        
    # Retrieve last 1000 logs for stat calculation
    logs, source = await fetch_audit_logs(None, None, 1000, tenant_id)
    
    if not logs:
        console.print("[yellow]No audit logs available to calculate statistics.[/yellow]")
        return

    total = len(logs)
    event_types = {}
    agents = {}
    
    for item in logs:
        et = item.get("event_type") or "unknown"
        event_types[et] = event_types.get(et, 0) + 1
        
        ag = item.get("agent_id") or "unknown"
        agents[ag] = agents.get(ag, 0) + 1

    console.print(f"[bold cyan]Audit Log Statistics (Tenant: {tenant_id} | Sample: {total} records from {source})[/bold cyan]")
    console.print("-" * 60)

    # Event Type Breakdowns Table
    et_table = Table(title="Event Types Distribution")
    et_table.add_column("Event Type", style="magenta")
    et_table.add_column("Count", justify="right")
    et_table.add_column("Percentage", justify="right")
    
    for et, count in sorted(event_types.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total) * 100
        et_table.add_row(et, str(count), f"{pct:.1f}%")
        
    console.print(et_table)
    console.print()

    # Agent Event Distributions Table
    ag_table = Table(title="Top Active Agents in Logs")
    ag_table.add_column("Agent ID", style="bold green")
    ag_table.add_column("Count", justify="right")
    ag_table.add_column("Percentage", justify="right")
    
    for ag, count in sorted(agents.items(), key=lambda x: x[1], reverse=True)[:10]:
        pct = (count / total) * 100
        ag_table.add_row(ag, str(count), f"{pct:.1f}%")
        
    console.print(ag_table)


@audit_group.command(name="purge")
@click.option("--before", "-b", type=int, help="Purge logs older than N days.")
@click.option("--confirm", is_flag=True, help="Automatically confirm delete without prompting.")
@coro
async def audit_purge(before: int | None, confirm: bool):
    """Purge old audit logs from PostgreSQL and the local log file."""
    if before is None:
        console.print("[red]Error: Please specify the cutoff time with --before <days>.[/red]")
        return
        
    if before < 0:
        console.print("[red]Error: --before <days> must be a non-negative integer.[/red]")
        return

    import datetime
    from datetime import timezone
    cutoff = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=before)
    cutoff_str = cutoff.isoformat()
    
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)
    
    if not confirm:
        click.confirm(f"Are you sure you want to delete all audit logs for tenant {tenant_id} older than {before} days (before {cutoff_str})?", abort=True)
        
    console.print(f"[yellow]⏳ Purging logs for tenant {tenant_id} older than {before} days (before {cutoff_str})...[/yellow]")

    # 1. Purge from PostgreSQL if available
    db_purged = 0
    db_ok = False
    try:
        async with async_session() as session:
            stmt = delete(AuditLogModel).where(AuditLogModel.tenant_id == tenant_id).where(AuditLogModel.timestamp < cutoff)
            res = await session.execute(stmt)
            await session.commit()
            db_purged = res.rowcount
            db_ok = True
    except Exception as db_err:
        console.print(f"[yellow]⚠️ Database purge failed: {db_err}[/yellow]")

    # 2. Purge from local JSONL log file if present
    file_purged = 0
    file_ok = False
    if os.path.exists(AUDIT_LOG_FILE):
        temp_file = AUDIT_LOG_FILE + ".tmp"
        try:
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f, \
                 open(temp_file, "w", encoding="utf-8") as out:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if rec.get("tenant_id") == tenant_id:
                            ts_float = rec.get("timestamp")
                            if ts_float:
                                dt = datetime.datetime.fromtimestamp(ts_float, tz=timezone.utc)
                                if dt < cutoff:
                                    file_purged += 1
                                    continue
                        out.write(line)
                    except Exception:
                        out.write(line)
            os.replace(temp_file, AUDIT_LOG_FILE)
            file_ok = True
        except Exception as e:
            if os.path.exists(temp_file):
                os.remove(temp_file)
            console.print(f"[red]Failed to purge local log file: {e}[/red]")

    # Summary
    if db_ok:
        console.print(f"[green]✔ Successfully deleted {db_purged} records from PostgreSQL database.[/green]")
    if file_ok:
        console.print(f"[green]✔ Successfully deleted {file_purged} records from local log file ({AUDIT_LOG_FILE}).[/green]")


@audit_group.command(name="verify")
@coro
async def audit_verify():
    """Verify cryptographic integrity of database audit logs against the secure local backup."""
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)

    console.print(f"[yellow]⏳ Verifying audit trail integrity for tenant {tenant_id}...[/yellow]")
    
    try:
        res = await audit_logger.verify_audit_integrity(tenant_id)
        status = res["status"]
        db_count = res["database_count"]
        backup_count = res["backup_count"]
        
        console.print("-" * 60)
        if status == "healthy":
            console.print(f"[green]✔ Healthy[/green]: Audit trail is fully verified and secure.")
            console.print(f"  • Database Records: {db_count}")
            console.print(f"  • Secure Backup Records: {backup_count}")
        elif status == "tampered":
            console.print(f"[red]❌ Tampered[/red]: Audit trail validation failed (tampering detected)!")
            console.print(f"  • Database Records: {db_count}")
            console.print(f"  • Secure Backup Records: {backup_count}")
            if res.get("tampered_ids"):
                console.print(f"  • Broken Link/Tampered Record IDs: {', '.join(res['tampered_ids'])}")
            else:
                console.print("  • Detected record deletion (sequence count mismatch)")
            console.print("[yellow]💡 Tip: Run 'agentdeep audit recover' to restore the audit logs from the secure local backup.[/yellow]")
        elif status == "corrupted_backup":
            console.print(f"[bold red]💥 Corrupted Backup[/bold red]: Secure local backup file has signature mismatches (unauthorized filesystem write)!")
            console.print(f"  • Database Records: {db_count}")
            console.print(f"  • Secure Backup Records: {backup_count}")
            console.print("[bold red]🚨 Alert: Manual administrator audit intervention is required immediately.[/bold red]")
        else:
            console.print(f"[red]Error[/red]: {res.get('description', 'Unknown error during verification.')}")
    except Exception as e:
        console.print(f"[red]❌ Verification command execution failed: {e}[/red]")


@audit_group.command(name="recover")
@click.option("--confirm", is_flag=True, help="Automatically confirm recovery without prompting.")
@coro
async def audit_recover(confirm: bool):
    """Perform self-healing to restore database audit logs from the HMAC-signed local secure backup."""
    ctx = CLIContext()
    async with ctx.get_db() as session:
        tenant_id = await ctx.resolve_tenant_id(session)
        
    if not confirm:
        click.confirm(f"Are you sure you want to perform self-healing and overwrite the database audit trail for tenant {tenant_id} using the secure local backup?", abort=True)
        
    console.print(f"[yellow]⏳ Executing self-healing recovery for tenant {tenant_id}...[/yellow]")
    
    try:
        res = await audit_logger.recover_audit_from_backup(tenant_id)
        if res["success"]:
            console.print(f"[green]✔ Success[/green]: {res['message']}")
        else:
            console.print(f"[red]❌ Recovery failed[/red]: {res['message']}")
    except Exception as e:
        console.print(f"[red]❌ Recovery command execution failed: {e}[/red]")
