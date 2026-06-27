"""Database migration command group for AgentDeepDive CLI."""

import sys
import subprocess
import os
import click
from rich.console import Console

console = Console()

def run_alembic(args: list[str]) -> subprocess.CompletedProcess:
    """Run alembic command using the current Python executable."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cmd = [sys.executable, "-m", "alembic"] + args
    return subprocess.run(cmd, cwd=root, capture_output=True, text=True)

@click.group(name="db")
def db_group():
    """Manage database migrations using Alembic."""
    pass

@db_group.command(name="migrate")
def db_migrate():
    """Apply all pending migrations to the database (upgrade to head)."""
    console.print("[yellow]⏳ Running database migrations...[/yellow]")
    res = run_alembic(["upgrade", "head"])
    if res.returncode == 0:
        console.print(res.stdout)
        console.print("[green]✔ Database migrations applied successfully![/green]")
    else:
        console.print(f"[red]❌ Database migration failed with exit code {res.returncode}[/red]")
        console.print(res.stderr)

@db_group.command(name="current")
def db_current():
    """Display the current revision of the database."""
    res = run_alembic(["current"])
    if res.returncode == 0:
        console.print(res.stdout)
    else:
        console.print(f"[red]❌ Failed to retrieve current database version.[/red]")
        console.print(res.stderr)

@db_group.command(name="history")
def db_history():
    """List migration history."""
    res = run_alembic(["history"])
    if res.returncode == 0:
        console.print(res.stdout)
    else:
        console.print(f"[red]❌ Failed to retrieve migration history.[/red]")
        console.print(res.stderr)

@db_group.command(name="revision")
@click.option("--message", "-m", required=True, help="Description of the migration revision.")
@click.option("--autogenerate", is_flag=True, default=True, help="Autogenerate migration based on model changes.")
def db_revision(message: str, autogenerate: bool):
    """Generate a new migration script."""
    console.print(f"[yellow]⏳ Generating new migration revision: '{message}'...[/yellow]")
    args = ["revision"]
    if autogenerate:
        args.append("--autogenerate")
    args.extend(["-m", message])
    
    res = run_alembic(args)
    if res.returncode == 0:
        console.print(res.stdout)
        console.print("[green]✔ Migration revision script created successfully![/green]")
    else:
        console.print(f"[red]❌ Failed to create revision script.[/red]")
        console.print(res.stderr)
