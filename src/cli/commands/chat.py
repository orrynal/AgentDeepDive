"""Chat REPL interactive terminal command for AgentDeepDive CLI."""

import click
import asyncio
from functools import wraps
from rich.console import Console

from src.cli.context import CLIContext
from src.cli.chat.session import ChatSession
from src.cli.chat.renderer import StreamRenderer
from src.cli.chat.repl import run_repl

console = Console()

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

@click.command(name="chat")
@click.option("--model", "-m", help="Override default LLM model for the chat session")
@click.option("--tenant", "-t", help="Override active tenant ID or tenant name")
@click.option("--max-tokens", type=int, default=100000, help="Maximum context token budget")
@click.option("--lightweight", "-l", is_flag=True, help="Force LIGHTWEIGHT mode (zero-container, SQLite, FAISS, local locks)")
@coro
async def chat_cmd(model: str | None, tenant: str | None, max_tokens: int, lightweight: bool):
    """Start an interactive Chat REPL session (conversational agent shell)."""
    ctx = CLIContext()
    
    if tenant:
        CLIContext.tenant_override = tenant

    if lightweight:
        from src.config import settings
        settings.system_mode = "lightweight"
        CLIContext.mode_override = "local"

    # Resolve tenant_id from context
    async with ctx.get_db() as db_session:
        tenant_id = await ctx.resolve_tenant_id(db_session)

    # Initialize chat session and renderer
    chat_session = ChatSession(model=model, tenant_id=tenant_id, max_context_tokens=max_tokens)
    renderer = StreamRenderer(console)

    # Start REPL event loop
    await run_repl(chat_session, renderer)
