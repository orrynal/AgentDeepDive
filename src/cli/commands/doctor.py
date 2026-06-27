"""Doctor diagnosis command for AgentDeepDive CLI."""

import os
import sys
import platform
import socket
import httpx
import click
import asyncio
from rich.console import Console
from rich.table import Table
from src.cli.utils.docker_helper import check_docker_environment
console = Console()

async def check_postgres() -> tuple[bool, str]:
    """Test connection to PostgreSQL database."""
    from src.config import settings
    from src.database import engine
    try:
        # Resolve connection using sqlalchemy engine
        async with engine.connect() as conn:
            # Simple select query to test connection
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
            return True, f"Connected to postgresql://{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    except Exception as e:
        return False, f"Failed to connect to database: {e}"

def check_redis() -> tuple[bool, str]:
    """Test connection to Redis server."""
    from src.config import settings
    from src.core.redis_pool import get_redis_client
    try:
        client = get_redis_client()
        if client.ping():
            return True, f"Connected to redis://{settings.redis_host}:{settings.redis_port}"
        return False, "Ping failed"
    except Exception as e:
        return False, f"Failed to connect: {e}"

def check_socket_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a host:port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

async def check_opa() -> tuple[bool, str]:
    """Test connection to Open Policy Agent (OPA)."""
    from src.config import settings
    if not settings.opa_enabled:
        return True, "OPA is disabled in config (Skipped)"

    url = f"{settings.opa_url}/v1/policies"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return True, f"Connected to OPA at {settings.opa_url}"
            return False, f"OPA responded with status code: {resp.status_code}"
    except Exception as e:
        return False, f"Failed to reach OPA at {settings.opa_url}: {e}"

async def check_jaeger() -> tuple[bool, str]:
    """Test Jaeger HTTP port."""
    # Find port from OTLP endpoint or default to 16686 (UI)
    # settings.otlp_endpoint is e.g. "http://localhost:4317"
    # UI is usually at localhost:16686
    ui_url = "http://localhost:16686"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(ui_url)
            if resp.status_code == 200:
                return True, f"Jaeger UI is online at {ui_url}"
            return False, f"Jaeger responded with status code: {resp.status_code}"
    except Exception as e:
        return False, f"Failed to reach Jaeger UI: {e}"

@click.command(name="doctor")
def doctor_cmd():
    """Diagnose local environment health and service dependencies."""
    from src.config import settings
    console.print("[bold cyan]AgentDeepDive System Doctor[/bold cyan]")
    console.print("=" * 60)

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Resource / Component", style="cyan", width=30)
    table.add_column("Status", width=15)
    table.add_column("Diagnostics / Detail")

    # 1. Python Version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    table.add_row("Python Version", "[green]✅ OK[/green]", f"{py_ver} ({platform.system()})")

    # Run async checks in loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # 2. PostgreSQL
    if settings.system_mode == "lightweight":
        pg_status = "[yellow]⚠️ Skipped[/yellow]"
        pg_msg = "Using local SQLite database in lightweight mode"
        pg_ok = True
    else:
        pg_ok, pg_msg = loop.run_until_complete(check_postgres())
        pg_status = "[green]✅ Connected[/green]" if pg_ok else "[red]❌ Offline[/red]"
    table.add_row("PostgreSQL", pg_status, pg_msg)

    # 3. Redis
    if settings.system_mode == "lightweight":
        r_status = "[yellow]⚠️ Skipped[/yellow]"
        r_msg = "Using local FileLock manager in lightweight mode"
        r_ok = True
    else:
        r_ok, r_msg = check_redis()
        r_status = "[green]✅ Connected[/green]" if r_ok else "[red]❌ Offline[/red]"
    table.add_row("Redis", r_status, r_msg)

    # 4. Milvus
    if settings.system_mode == "lightweight":
        m_status = "[yellow]⚠️ Skipped[/yellow]"
        m_msg = "Using local persistent vector JSON memory in lightweight mode"
        m_ok = True
    else:
        milvus_port = settings.milvus_port
        m_ok = check_socket_port(settings.milvus_host, milvus_port)
        m_status = "[green]✅ Connected[/green]" if m_ok else "[red]❌ Offline[/red]"
        m_msg = f"Connected to Milvus at {settings.milvus_host}:{milvus_port}" if m_ok else f"Failed to connect to Milvus at {settings.milvus_host}:{milvus_port}"
    table.add_row("Milvus (Vector DB)", m_status, m_msg)

    # 5. OPA
    if settings.system_mode == "lightweight":
        opa_status = "[yellow]⚠️ Skipped[/yellow]"
        opa_msg = "Using local Python AST & regex rules in lightweight mode"
        opa_ok = True
    else:
        opa_ok, opa_msg = loop.run_until_complete(check_opa())
        opa_status = "[green]✅ Connected[/green]" if opa_ok else ("[yellow]⚠️ Skipped[/yellow]" if not settings.opa_enabled else "[red]❌ Offline[/red]")
    table.add_row("Open Policy Agent (OPA)", opa_status, opa_msg)

    # 6. Jaeger
    if settings.system_mode == "lightweight":
        jaeger_status = "[yellow]⚠️ Skipped[/yellow]"
        jaeger_msg = "OTLP Jaeger tracing disabled or skipped in lightweight mode"
        jaeger_ok = True
    else:
        jaeger_ok, jaeger_msg = loop.run_until_complete(check_jaeger())
        jaeger_status = "[green]✅ Connected[/green]" if jaeger_ok else "[red]❌ Offline[/red]"
    table.add_row("Jaeger Tracing", jaeger_status, jaeger_msg)

    # 7. Docker compose files
    from src.cli.utils.docker_helper import get_docker_compose_path
    compose_path = get_docker_compose_path()
    compose_exists = os.path.exists(compose_path)
    compose_status = "[green]✅ Found[/green]" if compose_exists else "[red]❌ Missing[/red]"
    compose_msg = f"docker-compose.yml at {compose_path}" if compose_exists else f"Expected docker-compose.yml at {compose_path}"
    table.add_row("Docker Compose File", compose_status, compose_msg)

    # 8. Docker Environment
    docker_avail, docker_detail = check_docker_environment()
    docker_status = "[green]✅ Available[/green]" if docker_avail else "[red]❌ Missing[/red]"
    table.add_row("Docker CLI Engine", docker_status, docker_detail)

    # 9. .env Check
    env_exists = os.path.exists(".env")
    env_status = "[green]✅ Present[/green]" if env_exists else "[yellow]⚠️ Missing[/yellow]"
    env_msg = ".env configuration file is present" if env_exists else "No .env file found in project root; using defaults"
    table.add_row(".env File", env_status, env_msg)

    console.print(table)
    
    # Summary of Doctor run
    total_checks = 9
    success_count = sum([1 for x in [True, pg_ok, r_ok, m_ok, opa_ok, jaeger_ok, compose_exists, docker_avail, env_exists] if x])
    
    console.print("=" * 60)
    if success_count == total_checks:
        console.print(f"[bold green]✔ All {success_count}/{total_checks} health checks passed successfully![/bold green]")
    else:
        console.print(f"[bold yellow]⚠️ {success_count}/{total_checks} checks passed. Please start missing services or check settings.[/bold yellow]")
