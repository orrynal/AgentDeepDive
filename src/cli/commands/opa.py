"""OPA (Open Policy Agent) governance command group for AgentDeepDive CLI."""

import json
import os
import re
import urllib.request
import click
import httpx
from rich.console import Console
from rich.syntax import Syntax
from src.config import settings

console = Console()

@click.group(name="opa")
def OPA_group():
    """Manage OPA (Open Policy Agent) Rego security guardrails."""
    pass

@OPA_group.command(name="status")
def OPA_status():
    """Check Open Policy Agent (OPA) server connection and policies."""
    console.print(f"OPA Enabled in Config: {'[green]Yes[/green]' if settings.opa_enabled else '[red]No[/red]'}")
    console.print(f"OPA Server URL: {settings.opa_url}")
    console.print("-" * 50)
    
    if not settings.opa_enabled:
        return

    url = f"{settings.opa_url.rstrip('/')}/v1/policies"
    if not (url.startswith("http://") or url.startswith("https://")):
        console.print("[red]❌ Invalid URL protocol scheme[/red]")
        return
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:  # nosec B310
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                policies = data.get("result", [])
                
                console.print(f"[green]✔ Successfully connected to OPA server![/green]")
                console.print(f"Active policies count: {len(policies)}")
                
                for p in policies:
                    pid = p.get("id")
                    console.print(f" - [cyan]{pid}[/cyan]")
            else:
                console.print(f"[red]❌ OPA returned status code: {resp.status}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Failed to connect to OPA server: {e}[/red]")

@OPA_group.command(name="push")
def OPA_push():
    """Force push the local Rego guardrails policy to OPA."""
    policy_path = os.path.abspath(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "core",
            "governance",
            "policies",
            "guardrails.rego"
        )
    )

    if not os.path.exists(policy_path):
        console.print(f"[red]❌ Local Rego policy file not found at: {policy_path}[/red]")
        return

    console.print(f"[yellow]Reading policy from: {policy_path}...[/yellow]")
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            policy_content = f.read()
            
        url = f"{settings.opa_url.rstrip('/')}/v1/policies/guardrails"
        if not (url.startswith("http://") or url.startswith("https://")):
            console.print("[red]❌ Invalid URL protocol scheme[/red]")
            return
        console.print(f"[yellow]Pushing to OPA endpoint: {url}...[/yellow]")
        
        req = urllib.request.Request(
            url,
            data=policy_content.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:  # nosec B310
            if resp.status in [200, 201]:
                console.print("[green]✔ Guardrail policy uploaded to OPA successfully![/green]")
            else:
                console.print(f"[red]❌ Failed to push policy. OPA response: {resp.status}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Error pushing policy: {e}[/red]")

@OPA_group.command(name="test")
@click.option("--policy", "-p", "policy_file", help="Path to local Rego policy file. Defaults to production policy.")
@click.option("--input-file", "-i", help="Path to JSON file containing mock input.")
@click.option("--input-str", "-s", help="Inline JSON string containing mock input.")
def OPA_test(policy_file: str | None, input_file: str | None, input_str: str | None):
    """Test a Rego policy against a mock input in OPA without applying it."""
    # 1. Resolve policy path
    if not policy_file:
        policy_file = os.path.abspath(
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "core",
                "governance",
                "policies",
                "guardrails.rego"
            )
        )
        
    if not os.path.exists(policy_file):
        console.print(f"[red]❌ Policy file not found: {policy_file}[/red]")
        return
        
    # 2. Parse mock input
    mock_input = None
    if input_file:
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                mock_input = json.load(f)
        except Exception as e:
            console.print(f"[red]❌ Failed to parse JSON input file: {e}[/red]")
            return
    elif input_str:
        try:
            mock_input = json.loads(input_str)
        except Exception as e:
            console.print(f"[red]❌ Failed to parse inline JSON input string: {e}[/red]")
            return
    else:
        # Default mock input representing shell rm -rf /
        mock_input = {
            "tool_name": "shell_exec",
            "arguments": {
                "command": "rm -rf /"
            },
            "workspace_path": settings.resolved_workspace_path,
            "whitelist_enabled": False,
            "whitelist_commands": [],
            "parsed_command": {
                "ast_risk": None
            }
        }
        console.print("[yellow]No input provided. Testing default dangerous payload (rm -rf /)...[/yellow]")

    # Ensure "input" is top-level key
    if "input" not in mock_input:
        mock_input = {"input": mock_input}

    # 3. Read policy and modify package name to isolate the test
    try:
        with open(policy_file, "r", encoding="utf-8") as f:
            rego_content = f.read()
            
        test_rego = re.sub(r"\bpackage\s+guardrails\b", "package guardrails_test", rego_content)
        
        opa_url = settings.opa_url.rstrip("/")
        put_url = f"{opa_url}/v1/policies/guardrails_test"
        eval_url = f"{opa_url}/v1/data/guardrails_test/risk_level"
        
        if not (put_url.startswith("http://") or put_url.startswith("https://")):
            console.print("[red]❌ Invalid OPA URL protocol scheme[/red]")
            return
        if not (eval_url.startswith("http://") or eval_url.startswith("https://")):
            console.print("[red]❌ Invalid OPA URL protocol scheme[/red]")
            return

        console.print("[yellow]Uploading test policy to OPA...[/yellow]")
        req = urllib.request.Request(
            put_url,
            data=test_rego.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="PUT"
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec B310
            if resp.status not in [200, 201]:
                raise Exception(f"OPA returned HTTP {resp.status} on upload")
                
        # 4. Evaluate input
        console.print(f"[yellow]Evaluating input against policy...[/yellow]")
        
        eval_req = urllib.request.Request(
            eval_url,
            data=json.dumps(mock_input).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        decision = None
        with urllib.request.urlopen(eval_req, timeout=2.0) as resp:  # nosec B310
            if resp.status == 200:
                result = json.loads(resp.read().decode("utf-8"))
                decision = result.get("result")
                
        # 5. Cleanup test policy
        console.print("[yellow]Cleaning up test policy...[/yellow]")
        del_req = urllib.request.Request(put_url, method="DELETE")
        with urllib.request.urlopen(del_req, timeout=2.0):  # nosec B310
            pass
            
        if decision:
            color = "red" if decision == "L4" else ("yellow" if decision == "L3" else "green")
            console.print(f"[bold green]✔ Evaluation complete![/bold green]")
            console.print(f"Mock Input: {json.dumps(mock_input['input'])}")
            console.print(f"Evaluated Risk Level: [{color}]{decision}[/{color}]")
        else:
            console.print("[red]❌ OPA returned no decision result. Check Rego rules definition.[/red]")

    except Exception as e:
        console.print(f"[red]❌ OPA test failed: {e}[/red]")
