"""Response rendering utilities for AgentDeepDive Interactive Terminal."""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
import sys

class StreamResult:
    """Carries the collected output from a streamed response."""
    
    def __init__(self, full_content: str, tool_calls: list = None):
        self.full_content = full_content
        self.tool_calls = tool_calls or []
        self.has_tool_calls = len(self.tool_calls) > 0

class StreamRenderer:
    """Handles rendering LiteLLM streaming tokens and tools invocation notifications."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def print_banner(self, model: str, tenant_id: str, mode: str):
        """Render the welcome session banner."""
        banner_text = Text()
        banner_text.append("╭─ ", style="cyan")
        banner_text.append("AgentDeepDive Interactive Terminal ", style="bold cyan")
        banner_text.append("────────────────────────╮\n", style="cyan")
        banner_text.append("│  ", style="cyan")
        banner_text.append("Model: ", style="bold yellow")
        banner_text.append(f"{model:<15}", style="yellow")
        banner_text.append("Tenant: ", style="bold green")
        banner_text.append(f"{tenant_id:<15}", style="green")
        banner_text.append("Mode: ", style="bold blue")
        banner_text.append(f"{mode:<10}", style="blue")
        banner_text.append("│\n", style="cyan")
        banner_text.append("│  Type ", style="cyan")
        banner_text.append("/help", style="bold green")
        banner_text.append(" for list of commands, ", style="cyan")
        banner_text.append("/exit", style="bold red")
        banner_text.append(" to exit session.          │\n", style="cyan")
        banner_text.append("╰────────────────────────────────────────────────────────────╯", style="cyan")
        self.console.print(banner_text)

    def print_tool_start(self, tool_name: str, arguments: dict):
        """Print when a tool execution starts."""
        self.console.print(f"\n🔧 [bold blue]Calling tool:[/bold blue] [cyan]{tool_name}[/cyan]")
        if arguments:
            import json
            arg_str = json.dumps(arguments, indent=2, ensure_ascii=False)
            self.console.print(Panel(arg_str, title="Arguments", border_style="dim blue"))

    def print_tool_success(self, tool_name: str, result_summary: str):
        """Print when a tool execution completes successfully."""
        self.console.print(f"✅ [bold green]Tool completed:[/bold green] [cyan]{tool_name}[/cyan]")
        if result_summary:
            # Shorten output to avoid terminal flooding
            summary = result_summary[:800] + "\n... (truncated)" if len(result_summary) > 800 else result_summary
            self.console.print(Panel(summary, title="Result", border_style="dim green"))

    def print_tool_error(self, tool_name: str, error_msg: str):
        """Print when a tool execution fails."""
        self.console.print(f"❌ [bold red]Tool failed:[/bold red] [cyan]{tool_name}[/cyan]", style="red")
        self.console.print(Panel(error_msg, title="Error Details", border_style="red"))

    async def stream_and_collect(self, response_stream) -> StreamResult:
        """Stream response chunks from LiteLLM and render text in real-time."""
        full_content = ""
        # Store structured tool call parts
        tool_calls_map = {}

        # We print raw text character-by-character to sys.stdout for immediate visual feedback
        sys.stdout.write("AI Agent: ")
        sys.stdout.flush()

        async for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            
            # 1. Handle content streaming
            if delta.content:
                sys.stdout.write(delta.content)
                sys.stdout.flush()
                full_content += delta.content

            # 2. Handle tool calls delta
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc.id or "",
                            "type": "function",
                            "function": {
                                "name": tc.function.name or "",
                                "arguments": tc.function.arguments or ""
                            }
                        }
                    else:
                        if tc.id:
                            tool_calls_map[idx]["id"] = tc.id
                        if tc.function.name:
                            tool_calls_map[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tool_calls_map[idx]["function"]["arguments"] += tc.function.arguments

        sys.stdout.write("\n")
        sys.stdout.flush()

        # Convert tool calls map back to list
        tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            # Construct a dummy object matching standard LiteLLM structure
            from pydantic import BaseModel
            class FunctionObj(BaseModel):
                name: str
                arguments: str
            class ToolCallObj(BaseModel):
                id: str
                type: str
                function: FunctionObj
            
            tc_data = tool_calls_map[idx]
            tool_calls.append(ToolCallObj(
                id=tc_data["id"],
                type=tc_data["type"],
                function=FunctionObj(
                    name=tc_data["function"]["name"],
                    arguments=tc_data["function"]["arguments"]
                )
            ))

        return StreamResult(full_content=full_content, tool_calls=tool_calls)

    def print_markdown(self, markdown_text: str):
        """Render full formatted markdown at the end of streaming or session load."""
        self.console.print(Markdown(markdown_text))
