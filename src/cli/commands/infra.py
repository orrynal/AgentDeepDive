"""Infrastructure management command group for AgentDeepDive CLI."""

import click
from rich.console import Console
from rich.table import Table
from src.cli.utils.docker_helper import run_compose_cmd, check_docker_environment

console = Console()

@click.group(name="infra")
def infra_group():
    """Manage Docker infrastructure services (PostgreSQL, Redis, Milvus, Jaeger)."""
    pass

@infra_group.command(name="up")
@click.option("--service", "-s", help="Start only a specific service (e.g. postgres, redis, milvus, jaeger).")
def infra_up(service: str | None):
    """Start Docker infrastructure services."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    args = ["up", "-d"]
    if service:
        args.append(service)
        console.print(f"[yellow]⏳ Starting service '{service}'...[/yellow]")
    else:
        console.print("[yellow]⏳ Starting all infrastructure services...[/yellow]")

    try:
        res = run_compose_cmd(args, stream=True)
        if res.returncode == 0:
            console.print("[green]✔ Services started successfully![/green]")
        else:
            console.print(f"[red]❌ Failed to start services. Return code: {res.returncode}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="down")
def infra_down():
    """Stop and remove Docker infrastructure containers (volumes are preserved)."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    console.print("[yellow]⏳ Stopping and removing infrastructure containers...[/yellow]")
    try:
        res = run_compose_cmd(["down"], stream=True)
        if res.returncode == 0:
            console.print("[green]✔ Services stopped and containers removed successfully![/green]")
            console.print("[dim]💡 Note: Named data volumes (postgres_data, redis_data, milvus_data) are preserved. Your database data is safe.[/dim]")
        else:
            console.print(f"[red]❌ Failed to stop services. Return code: {res.returncode}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="stop")
def infra_stop():
    """Stop Docker infrastructure containers without removing them."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    console.print("[yellow]⏳ Stopping infrastructure containers...[/yellow]")
    try:
        res = run_compose_cmd(["stop"], stream=True)
        if res.returncode == 0:
            console.print("[green]✔ Services stopped successfully![/green]")
        else:
            console.print(f"[red]❌ Failed to stop services. Return code: {res.returncode}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="start")
def infra_start():
    """Start stopped Docker infrastructure containers without recreation."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    console.print("[yellow]⏳ Starting stopped infrastructure containers...[/yellow]")
    try:
        res = run_compose_cmd(["start"], stream=True)
        if res.returncode == 0:
            console.print("[green]✔ Services started successfully![/green]")
        else:
            console.print(f"[red]❌ Failed to start services. Return code: {res.returncode}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="status")
def infra_status():
    """Show status of infrastructure services."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    try:
        res = run_compose_cmd(["ps", "--format", "json"])
        if res.returncode != 0:
            # Fallback to standard ps if JSON is not supported
            res = run_compose_cmd(["ps"])
            console.print(res.stdout)
            return

        import json
        # Parse JSON output. docker compose format might be a series of JSON objects (one per line) or a JSON array.
        lines = res.stdout.strip().split("\n")
        
        table = Table(title="Docker Infrastructure Status")
        table.add_column("Service", style="cyan")
        table.add_column("Container ID", style="dim")
        table.add_column("Status", style="bold")
        table.add_column("Ports")

        for line in lines:
            if not line.strip():
                continue
            try:
                # Docker Compose JSON output can have multiple objects on different lines
                data = json.loads(line)
                # Or sometimes Docker Compose returns a JSON array
                if isinstance(data, list):
                    items = data
                else:
                    items = [data]
                
                for item in items:
                    name = item.get("Service") or item.get("Name") or "Unknown"
                    cid = item.get("ID") or item.get("Project") or "-"
                    status = item.get("Status") or item.get("State") or "Unknown"
                    ports = item.get("Publishers") or item.get("Ports") or "-"
                    
                    # Normalize ports display if list
                    if isinstance(ports, list):
                        port_strs = []
                        for p in ports:
                            pub = p.get("PublishedPort")
                            proto = p.get("Protocol")
                            if pub:
                                port_strs.append(f"{pub}/{proto}")
                        ports = ", ".join(port_strs) or "-"

                    status_color = "green" if "running" in status.lower() or "up" in status.lower() else "red"
                    table.add_row(name, cid[:12], f"[{status_color}]{status}[/{status_color}]", str(ports))
            except Exception:
                pass
        
        if table.row_count > 0:
            console.print(table)
        else:
            console.print("[yellow]No infrastructure containers found. Run 'agentdeep infra up' to start them.[/yellow]")
            
    except Exception as e:
        # Fallback to plain text output if JSON parsing failed
        try:
            res = run_compose_cmd(["ps"])
            console.print(res.stdout)
        except Exception as ex:
            console.print(f"[red]❌ Error fetching status: {e} ({ex})[/red]")

@infra_group.command(name="logs")
@click.argument("service", required=False)
@click.option("--follow", "-f", is_flag=True, help="Follow log output.")
@click.option("--tail", "-t", default="all", help="Number of lines to show from the end of the logs.")
def infra_logs(service: str | None, follow: bool, tail: str):
    """View infrastructure logs."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    args = ["logs", "--tail", tail]
    if follow:
        args.append("-f")
    if service:
        args.append(service)

    try:
        run_compose_cmd(args, stream=True)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="reset")
@click.confirmation_option(prompt="Are you sure you want to reset all data volumes? This will erase all databases and logs!")
def infra_reset():
    """Reset infrastructure and erase all data volumes."""
    is_avail, err = check_docker_environment()
    if not is_avail:
        console.print(f"[red]❌ Error: {err}[/red]")
        return

    console.print("[red]⚠️ Resetting infrastructure services and volumes...[/red]")
    try:
        res = run_compose_cmd(["down", "-v"], stream=True)
        if res.returncode == 0:
            console.print("[green]✔ Services stopped and all volumes purged successfully![/green]")
        else:
            console.print(f"[red]❌ Failed to reset services. Return code: {res.returncode}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error running command: {e}[/red]")

@infra_group.command(name="worker")
@click.option("--loglevel", "-l", default="info", help="Celery log level (info, debug, warning, error).")
def infra_worker(loglevel: str):
    """Start Celery Worker locally for background async DAG execution."""
    import subprocess
    import sys
    from src.config import settings

    if not settings.celery_enabled:
        console.print("[yellow]⚠️ Warning: settings.celery_enabled is set to False (e.g. lightweight mode).[/yellow]")
    
    console.print(f"[yellow]⏳ Starting Celery Worker (broker: {settings.celery_broker_url})...[/yellow]")
    
    cmd = [
        sys.executable, "-m", "celery",
        "-A", "src.core.celery_app",
        "worker",
        "--loglevel", loglevel
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[green]✔ Celery Worker stopped successfully.[/green]")
    except Exception as e:
        console.print(f"[red]❌ Failed to start Celery Worker: {e}[/red]")

