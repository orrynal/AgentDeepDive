"""Authentication command group for AgentDeepDive CLI."""

import click
import httpx
import asyncio
from functools import wraps
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.cli.context import CLIContext, CLIMode

console = Console()
API_BASE_URL = "http://localhost:8000/api/v1"

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.group(name="auth")
def auth_group():
    """Authenticate and manage multi-tenant user sessions."""
    pass

@auth_group.command(name="register")
@click.option("--tenant", "-t", "tenant_name", required=True, help="Tenant organization name")
@click.option("--username", "-u", required=True, help="Admin username")
@click.option("--password", "-p", help="Admin password")
@coro
async def auth_register(tenant_name: str, username: str, password: str | None):
    """Register a new tenant organization and its admin user."""
    if not password:
        password = click.prompt("Enter admin password", hide_input=True)

    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    if mode != CLIMode.REMOTE:
        console.print("[red]❌ Error: Tenant registration requires the remote API Server to be online.[/red]")
        return

    payload = {
        "tenant_name": tenant_name,
        "username": username,
        "password": password
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{API_BASE_URL}/auth/register", json=payload, timeout=10)
            if resp.status_code == 201:
                res = resp.json()
                console.print(f"[green]✔ Successfully registered tenant '{tenant_name}' and user '{username}'![/green]")
                console.print(f"Tenant ID: [cyan]{res['tenant']['id']}[/cyan]")
                console.print("[yellow]💡 You can now log in using: agentdeep auth login[/yellow]")
            else:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ Registration failed ({resp.status_code}): {detail}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]")


@auth_group.command(name="login")
@click.option("--username", "-u", required=True, help="Username")
@click.option("--password", "-p", help="Password")
@coro
async def auth_login(username: str, password: str | None):
    """Log in to get a JWT token for remote actions."""
    if not password:
        password = click.prompt("Enter password", hide_input=True)

    ctx = CLIContext(api_url=API_BASE_URL)
    mode = await ctx.detect_mode_async()
    if mode != CLIMode.REMOTE:
        console.print("[red]❌ Error: User login requires the remote API Server to be online.[/red]")
        return

    payload = {
        "username": username,
        "password": password
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{API_BASE_URL}/auth/login", json=payload, timeout=10)
            if resp.status_code == 200:
                res = resp.json()
                token = res["access_token"]
                tenant_id = res["tenant_id"]
                role = res["role"]

                ctx.save_auth(token, username, tenant_id, role)
                console.print(f"[green]✔ Successfully logged in as '{username}'![/green]")
                console.print(f"Tenant ID: [cyan]{tenant_id}[/cyan] | Role: [magenta]{role}[/magenta]")
            else:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                console.print(f"[red]❌ Login failed ({resp.status_code}): {detail}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Connection failed: {e}[/red]")


@auth_group.command(name="logout")
def auth_logout():
    """Clear local authentication session."""
    ctx = CLIContext()
    ctx.clear_auth()
    console.print("[green]✔ Successfully logged out. Local credentials cleared.[/green]")


@auth_group.command(name="me")
@coro
async def auth_me():
    """Show details of the current logged-in user."""
    ctx = CLIContext(api_url=API_BASE_URL)
    auth = ctx.load_auth()
    if not auth:
        console.print("[yellow]Not currently logged in. Run 'agentdeep auth login' to authenticate.[/yellow]")
        return

    mode = await ctx.detect_mode_async()
    if mode == CLIMode.REMOTE:
        try:
            async with httpx.AsyncClient() as client:
                headers = ctx.get_auth_headers()
                resp = await client.get(f"{API_BASE_URL}/auth/me", headers=headers, timeout=5)
                if resp.status_code == 200:
                    user_data = resp.json()
                    table = Table(title="Active Session Profile (Remote)", show_header=False)
                    table.add_row("Username", user_data["username"])
                    table.add_row("Tenant ID", user_data["tenant_id"])
                    table.add_row("Role", user_data["role"])
                    console.print(table)
                    return
                else:
                    console.print(f"[yellow]⚠️ Failed to verify session with server ({resp.status_code}). Showing local cache...[/yellow]")
        except Exception as e:
            console.print(f"[yellow]⚠️ Server connection failed ({e}). Showing local cache...[/yellow]")

    # Cached version if server is down or unverified
    table = Table(title="Cached Session Profile (Local / Offline)", show_header=False)
    table.add_row("Username", auth.get("username", "-"))
    table.add_row("Tenant ID", auth.get("tenant_id", "-"))
    table.add_row("Role", auth.get("role", "-"))
    table.add_row("JWT Token", f"{auth.get('access_token', '')[:15]}... [dim](stored local)[/dim]")
    console.print(table)
