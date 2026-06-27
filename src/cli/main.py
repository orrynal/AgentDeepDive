"""AgentDeepDive CLI - developer's primary interaction interface."""

import asyncio
import click
import httpx
from rich.console import Console
from rich.table import Table

console = Console()
API_BASE_URL = "http://localhost:8000/api/v1"


class LazyGroup(click.Group):
    def list_commands(self, ctx):
        lazy_cmds = ["doctor", "infra", "db", "lock", "audit", "opa", "monitor", "auth", "chat", "schedule"]
        standard_cmds = super().list_commands(ctx)
        return sorted(list(set(lazy_cmds + standard_cmds)))

    def get_command(self, ctx, name):
        # Determine if we are printing top-level help to avoid heavy imports
        import sys
        import os
        lazy_cmds = ["doctor", "infra", "db", "lock", "audit", "opa", "monitor", "auth", "chat", "schedule"]
        is_test = ("pytest" in sys.modules or "unittest" in sys.modules) and not os.getenv("AGENTDEEP_TESTING_LAZY_HELP")
        has_subcommand = any(arg in sys.argv for arg in lazy_cmds)
        if not is_test and not has_subcommand and name in lazy_cmds:
            lazy_help_map = {
                "doctor": "Diagnose local environment health and service dependencies.",
                "infra": "Manage Docker infrastructure services (PostgreSQL, Redis, Milvus, Jaeger).",
                "db": "Manage database migrations using Alembic.",
                "lock": "Manage file concurrency locks and preemption.",
                "audit": "Query and export security & governance audit logs.",
                "opa": "Manage OPA (Open Policy Agent) Rego security guardrails.",
                "monitor": "Start the real-time terminal monitoring dashboard.",
                "auth": "Authenticate and manage multi-tenant user sessions.",
                "chat": "Start an interactive Chat REPL session (conversational agent shell).",
                "schedule": "Manage cron schedules for background tasks."
            }
            return click.Command(name, help=lazy_help_map.get(name, ""))

        if name == "doctor":
            from src.cli.commands.doctor import doctor_cmd
            return doctor_cmd
        elif name == "infra":
            from src.cli.commands.infra import infra_group
            return infra_group
        elif name == "db":
            from src.cli.commands.db import db_group
            return db_group
        elif name == "lock":
            from src.cli.commands.lock import lock_group
            return lock_group
        elif name == "audit":
            from src.cli.commands.audit import audit_group
            return audit_group
        elif name == "opa":
            from src.cli.commands.opa import OPA_group
            return OPA_group
        elif name == "monitor":
            from src.cli.commands.monitor import monitor_command
            return monitor_command
        elif name == "auth":
            from src.cli.commands.auth import auth_group
            return auth_group
        elif name == "chat":
            from src.cli.commands.chat import chat_cmd
            return chat_cmd
        elif name == "schedule":
            from src.cli.commands.schedule import schedule_group
            return schedule_group
        return super().get_command(ctx, name)


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(cls=LazyGroup, context_settings=CONTEXT_SETTINGS)
@click.option("--tenant", "-t", default=None, help="Tenant ID or name override")
@click.option("--local", is_flag=True, help="Force LOCAL direct-connect mode")
@click.option("--remote", is_flag=True, help="Force REMOTE API-based mode")
@click.option("--lightweight", "-l", is_flag=True, help="Force LIGHTWEIGHT mode (zero-container, SQLite, FAISS, local locks)")
@click.version_option(version="0.1.0-alpha", prog_name="agentdeep")
def cli(tenant, local, remote, lightweight):
    """AgentDeepDive - Multi-Agent Orchestration Platform"""
    from src.cli.context import CLIContext
    from src.config import settings
    if tenant:
        CLIContext.tenant_override = tenant
    if lightweight:
        settings.system_mode = "lightweight"
        CLIContext.mode_override = "local"
    elif local:
        CLIContext.mode_override = "local"
    elif remote:
        CLIContext.mode_override = "remote"



from src.cli.context import CLIContext, CLIMode


@cli.command()
@click.option("--channels", "-c", is_flag=True, help="Check connection and configuration status of third-party integration channels")
def status(channels):
    """Show system status and connectivity."""
    async def check():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        if channels:
            table = Table(title="AgentDeepDive Third-Party Integrations Status")
            table.add_column("Integration Channel", style="cyan")
            table.add_column("Connection Status", style="bold")
            table.add_column("Configuration Detail")
            
            console.print("⏳ [bold yellow]Diagnosing third-party integration channels...[/bold yellow]")
            from src.config import settings
            
            results = []
            
            async def check_telegram(client):
                token = settings.telegram_bot_token
                chat_id = settings.telegram_chat_id
                if not token:
                    return "Telegram Bot", "[dim]⚪ Unconfigured[/dim]", "Missing TELEGRAM_BOT_TOKEN"
                try:
                    resp = await client.get(f"https://api.telegram.org/bot{token}/getMe", timeout=3.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        username = data.get("result", {}).get("username", "Unknown")
                        chat_info = f" (Chat ID: {chat_id})" if chat_id else " (No Chat ID)"
                        return "Telegram Bot", "[green]🟢 Connected[/green]", f"Bot: @{username}{chat_info}"
                    else:
                        return "Telegram Bot", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "Telegram Bot", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_discord(client):
                token = settings.discord_bot_token
                channel_id = settings.discord_channel_id
                if not token:
                    return "Discord Bot", "[dim]⚪ Unconfigured[/dim]", "Missing DISCORD_BOT_TOKEN"
                try:
                    resp = await client.get(
                        "https://discord.com/api/v10/users/@me",
                        headers={"Authorization": f"Bot {token}"},
                        timeout=3.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        username = data.get("username", "Unknown")
                        disc = data.get("discriminator", "0000")
                        channel_info = f" (Channel: {channel_id})" if channel_id else " (No Channel ID)"
                        return "Discord Bot", "[green]🟢 Connected[/green]", f"User: {username}#{disc}{channel_info}"
                    else:
                        return "Discord Bot", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "Discord Bot", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_wechat(client):
                corp_id = settings.wechat_corp_id
                corp_secret = settings.wechat_corp_secret
                webhook = settings.wechat_webhook_url
                if webhook:
                    return "WeChat (WeCom)", "[green]🟢 Webhook Ready[/green]", f"URL: {webhook[:30]}..."
                if not corp_id or not corp_secret:
                    return "WeChat (WeCom)", "[dim]⚪ Unconfigured[/dim]", "Missing Corp ID/Secret or Webhook"
                try:
                    token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={corp_secret}"
                    resp = await client.get(token_url, timeout=3.0)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("errcode") == 0:
                            return "WeChat (WeCom)", "[green]🟢 Connected (App)[/green]", f"Agent ID: {settings.wechat_agent_id}"
                        else:
                            return "WeChat (WeCom)", "[red]🔴 Auth Failed[/red]", data.get("errmsg", "")[:40]
                    else:
                        return "WeChat (WeCom)", f"[red]🔴 Error ({resp.status_code})[/red]", ""
                except Exception as e:
                    return "WeChat (WeCom)", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_slack(client):
                url = settings.slack_webhook_url
                if not url:
                    return "Slack Webhook", "[dim]⚪ Unconfigured[/dim]", "Missing SLACK_WEBHOOK_URL"
                return "Slack Webhook", "[green]🟢 Webhook Ready[/green]", f"URL: {url[:30]}..."

            async def check_feishu(client):
                url = settings.feishu_webhook_url
                if not url:
                    return "Feishu Webhook", "[dim]⚪ Unconfigured[/dim]", "Missing FEISHU_WEBHOOK_URL"
                return "Feishu Webhook", "[green]🟢 Webhook Ready[/green]", f"URL: {url[:30]}..."

            async def check_dingtalk(client):
                url = settings.dingtalk_webhook_url
                if not url:
                    return "DingTalk Webhook", "[dim]⚪ Unconfigured[/dim]", "Missing DINGTALK_WEBHOOK_URL"
                return "DingTalk Webhook", "[green]🟢 Webhook Ready[/green]", f"URL: {url[:30]}..."

            async def check_whatsapp(client):
                token = settings.whatsapp_token
                phone_id = settings.whatsapp_phone_id
                if not token or not phone_id:
                    return "WhatsApp", "[dim]⚪ Unconfigured[/dim]", "Missing token or phone ID"
                try:
                    resp = await client.get(
                        f"https://graph.facebook.com/v17.0/{phone_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=3.0
                    )
                    if resp.status_code == 200:
                        return "WhatsApp", "[green]🟢 Connected[/green]", f"Phone ID: {phone_id}"
                    else:
                        return "WhatsApp", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "WhatsApp", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_qq(client):
                appid = settings.qq_bot_appid
                token = settings.qq_bot_token
                if not appid or not token:
                    return "QQ Bot", "[dim]⚪ Unconfigured[/dim]", "Missing AppID or Token"
                return "QQ Bot", "[green]🟢 Configured[/green]", f"AppID: {appid}"

            async def check_twitter(client):
                token = settings.twitter_bearer_token
                if not token:
                    return "Twitter (X)", "[dim]⚪ Unconfigured[/dim]", "Missing Bearer Token"
                return "Twitter (X)", "[green]🟢 Configured[/green]", "Token present"

            async def check_notion(client):
                token = settings.notion_integration_token
                if not token:
                    return "Notion", "[dim]⚪ Unconfigured[/dim]", "Missing Integration Token"
                try:
                    resp = await client.get(
                        "https://api.notion.com/v1/users/me",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Notion-Version": "2022-06-28"
                        },
                        timeout=3.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        name = data.get("name", "Workspace Bot")
                        return "Notion", "[green]🟢 Connected[/green]", f"User: {name}"
                    else:
                        return "Notion", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "Notion", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_supabase(client):
                url = settings.supabase_url
                key = settings.supabase_key
                if not url or not key:
                    return "Supabase", "[dim]⚪ Unconfigured[/dim]", "Missing URL or Service Key"
                try:
                    resp = await client.get(f"{url}/rest/v1/", headers={"apikey": key}, timeout=3.0)
                    if resp.status_code in (200, 404):
                        return "Supabase", "[green]🟢 Connected[/green]", f"REST API URL: {url[:30]}..."
                    else:
                        return "Supabase", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "Supabase", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async def check_airtable(client):
                key = settings.airtable_api_key
                base_id = settings.airtable_base_id
                if not key:
                    return "Airtable", "[dim]⚪ Unconfigured[/dim]", "Missing API Key"
                try:
                    resp = await client.get(
                        "https://api.airtable.com/v0/meta/bases",
                        headers={"Authorization": f"Bearer {key}"},
                        timeout=3.0
                    )
                    if resp.status_code == 200:
                        return "Airtable", "[green]🟢 Connected[/green]", f"Authorized (Base ID: {base_id or 'Not specified'})"
                    else:
                        return "Airtable", f"[red]🔴 Error ({resp.status_code})[/red]", resp.text[:40]
                except Exception as e:
                    return "Airtable", "[red]🔴 Offline/Timeout[/red]", str(e)[:40]

            async with httpx.AsyncClient() as client:
                tasks = [
                    check_telegram(client),
                    check_discord(client),
                    check_wechat(client),
                    check_slack(client),
                    check_feishu(client),
                    check_dingtalk(client),
                    check_whatsapp(client),
                    check_qq(client),
                    check_twitter(client),
                    check_notion(client),
                    check_supabase(client),
                    check_airtable(client)
                ]
                results = await asyncio.gather(*tasks)

            for name, status_str, detail in results:
                table.add_row(name, status_str, detail)

            console.print(table)
            return

        table = Table(title="AgentDeepDive System Status")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Detail")

        table.add_row("CLI Mode", "[cyan]自适应检测[/cyan]", f"Resolved: {mode.value.upper()}")

        if mode == CLIMode.REMOTE:
            # Check API server health
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get("http://localhost:8000/health", timeout=3)
                    data = resp.json()
                    table.add_row("API Server", "[green]✅ Online[/green]", data.get("version", ""))
            except Exception:
                table.add_row("API Server", "[red]❌ Offline[/red]", "Cannot connect to :8000")

            # Check sub-services readiness
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get("http://localhost:8000/health/ready", timeout=5)
                    data = resp.json()
                    for svc, st in data.get("checks", {}).items():
                        icon = "[green]✅[/green]" if st == "ok" else "[red]❌[/red]"
                        table.add_row(f"  └─ {svc}", icon, st)
            except Exception:
                pass
        else:
            table.add_row("API Server", "[red]❌ Offline[/red]", "Running in LOCAL direct-connect mode")
            # Directly check Postgres and Redis
            from src.cli.commands.doctor import check_postgres, check_redis
            pg_ok, pg_msg = await check_postgres()
            pg_icon = "[green]✅ Online[/green]" if pg_ok else "[red]❌ Offline[/red]"
            table.add_row("  └─ postgres", pg_icon, pg_msg)

            r_ok, r_msg = check_redis()
            r_icon = "[green]✅ Online[/green]" if r_ok else "[red]❌ Offline[/red]"
            table.add_row("  └─ redis", r_icon, r_msg)

        console.print(table)

    asyncio.run(check())


@cli.command()
@click.argument("task_description")
@click.option("--model", default=None, help="LLM model override")
@click.option("--context", default="", help="Additional context data")
@click.option("--skill", "skill_id", default=None, help="Explicit Skill ID (auto-routed if omitted)")
@click.option("--lightweight", "-l", is_flag=True, help="Force LIGHTWEIGHT mode (zero-container, SQLite, FAISS, local locks)")
def run(task_description: str, model: str | None, context: str, skill_id: str | None, lightweight: bool):
    """Submit a task for immediate Agent execution (Phase 1)."""
    async def execute():
        if lightweight:
            from src.config import settings
            settings.system_mode = "lightweight"
            CLIContext.mode_override = "local"
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        
        console.print(f"[yellow]⏳ Submitting task (Mode: {mode.value.upper()}):[/yellow] {task_description}")
        
        if mode == CLIMode.REMOTE:
            payload = {
                "description": task_description,
                "context": context,
            }
            if model:
                payload["model"] = model
            if skill_id:
                payload["skill_id"] = skill_id

            try:
                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/tasks/execute", json=payload, timeout=600)
                    if resp.status_code != 200:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
                        return

                    res = resp.json()
                    console.print(f"\n[green]✔ Task Completed:[/green] {res['task_id']}")
                    console.print(f"Status: {res['status']}")
                    console.print(f"Skill Used: {res['skill_used']}")
                    
                    if res.get("error"):
                        console.print(f"[red]Error:[/red] {res['error']}")
                    else:
                        console.print("\n[bold]Output:[/bold]")
                        console.print(res.get("result"))

                    # Print trace summary
                    trace = res.get("trace")
                    if trace:
                        console.print(f"\n[dim]Trace ID: {trace['trace_id']} | Tokens In: {trace['total_tokens_input']} | Tokens Out: {trace['total_tokens_output']}[/dim]")

            except Exception as e:
                console.print(f"[red]Execution failed:[/red] {e}")
        else:
            # Local Direct-Connect mode
            from uuid import uuid4
            from src.core.agent.executor import AgentExecutor
            from src.core.skill.router import SkillRouter
            from src.core.skill.service import SkillService
            from src.core.memory.rag_manager import rag_manager

            task_id = f"task-{uuid4().hex[:12]}"
            
            try:
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                    if skill_id:
                        svc = SkillService(session, tenant_id=tenant_id)
                        skill_obj = await svc.get_by_id(skill_id)
                        if not skill_obj:
                            console.print(f"[red]Error: Skill '{skill_id}' not found locally.[/red]")
                            return
                    else:
                        router = SkillRouter(
                            session,
                            embedder=rag_manager.embedder,
                            milvus_client=rag_manager.client,
                            tenant_id=tenant_id,
                        )
                        matches = await router.route(task_description, top_k=1)
                        if not matches:
                            console.print("[red]Error: No matching Skill found locally. Register a skill or specify --skill explicitly.[/red]")
                            return
                        skill_obj = matches[0]

                    executor = AgentExecutor(model=model)
                    res = await executor.execute(
                        task_id=task_id,
                        task_description=task_description,
                        skill=skill_obj,
                        context=context,
                    )
                    
                    console.print(f"\n[green]✔ Task Completed (Local):[/green] {task_id}")
                    console.print(f"Status: {res['status']}")
                    console.print(f"Skill Used: {skill_obj.get('skill_id')}")
                    
                    if res.get("error"):
                        console.print(f"[red]Error:[/red] {res['error']}")
                    else:
                        console.print("\n[bold]Output:[/bold]")
                        console.print(res.get("result"))

                    trace = res.get("trace")
                    if trace:
                        console.print(f"\n[dim]Trace ID: {trace['trace_id']} | Tokens In: {trace['total_tokens_input']} | Tokens Out: {trace['total_tokens_output']}[/dim]")

            except Exception as e:
                console.print(f"[red]Local execution failed:[/red] {e}")

    asyncio.run(execute())



@cli.group()
def skill():
    """Manage Skills."""
    pass


@skill.command("list")
def skill_list():
    """List all registered Skills."""
    async def fetch():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/skills", timeout=5)
                    skills = resp.json()

                    if not skills:
                        console.print("[dim]No skills registered yet.[/dim]")
                        return

                    table = Table(title="Registered Skills")
                    table.add_column("Skill ID", style="cyan")
                    table.add_column("Name")
                    table.add_column("Version")
                    table.add_column("Risk", style="yellow")
                    table.add_column("Tags")

                    for s in skills:
                        table.add_row(
                            s["skill_id"],
                            s["name"],
                            s["version"],
                            s["risk_level"],
                            ", ".join(s.get("tags", [])),
                        )
                    console.print(table)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.skill.service import SkillService
            try:
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                    svc = SkillService(session, tenant_id=tenant_id)
                    skills = await svc.list_all(active_only=True)
                    if not skills:
                        console.print("[dim]No skills registered yet locally.[/dim]")
                        return

                    table = Table(title="Registered Skills (Local)")
                    table.add_column("Skill ID", style="cyan")
                    table.add_column("Name")
                    table.add_column("Version")
                    table.add_column("Risk", style="yellow")
                    table.add_column("Tags")

                    for s in skills:
                        table.add_row(
                            s["skill_id"],
                            s["name"],
                            s["version"],
                            s["risk_level"],
                            ", ".join(s.get("tags", [])),
                        )
                    console.print(table)
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(fetch())


@skill.command("register")
@click.option("--file", "-f", type=click.Path(exists=True), required=False, help="Path to the local skill.yaml file")
@click.option("--url", "-u", type=str, required=False, help="URL to a remote skill.yaml file (e.g., from skills.sh)")
def skill_register(file: str | None, url: str | None):
    """Register (install) a new Skill from a local file or remote URL."""
    async def run():
        import yaml
        if not file and not url:
            console.print("[red]Error: Must specify either --file (-f) or --url (-u).[/red]")
            return

        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()

        if mode == CLIMode.REMOTE:
            try:
                if file:
                    with open(file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                else:
                    console.print(f"[yellow]⏳ Fetching remote skill definition from:[/yellow] {url}")
                    async with ctx.get_http_client() as client:
                        resp_get = await client.get(url, timeout=15)
                        if resp_get.status_code != 200:
                            console.print(f"[red]Error fetching remote URL {resp_get.status_code}:[/red] {resp_get.text}")
                            return
                        data = yaml.safe_load(resp_get.text)

                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/skills", json=data, timeout=10)
                    if resp.status_code == 201:
                        console.print(f"[green]✔ Skill '{data.get('skill_id')}' successfully registered![/green]")
                    elif resp.status_code == 409:
                        console.print(f"[yellow]Skill '{data.get('skill_id')}' already exists. Use PUT API to modify it.[/yellow]")
                    else:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error registering skill:[/red] {e}")
        else:
            from src.core.skill.service import SkillService
            try:
                if file:
                    with open(file, "r", encoding="utf-8") as f:
                        raw_data = yaml.safe_load(f)
                else:
                    console.print(f"[yellow]⏳ Fetching remote skill definition from:[/yellow] {url}")
                    async with ctx.get_http_client() as client:
                        resp_get = await client.get(url, timeout=15)
                        if resp_get.status_code != 200:
                            console.print(f"[red]Error fetching remote URL {resp_get.status_code}:[/red] {resp_get.text}")
                            return
                        raw_data = yaml.safe_load(resp_get.text)

                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                    svc = SkillService(session, tenant_id=tenant_id)
                    existing = await svc.get_by_id(raw_data.get("skill_id"))
                    if existing:
                        console.print(f"[yellow]Skill '{raw_data.get('skill_id')}' already exists locally. Updating...[/yellow]")
                        await svc.update(raw_data.get("skill_id"), raw_data)
                        await session.commit()
                        console.print(f"[green]✔ Skill '{raw_data.get('skill_id')}' successfully updated locally![/green]")
                    else:
                        await svc.create(raw_data)
                        await session.commit()
                        console.print(f"[green]✔ Skill '{raw_data.get('skill_id')}' successfully registered locally![/green]")
            except Exception as e:
                console.print(f"[red]Error registering skill (Local):[/red] {e}")

    asyncio.run(run())


@skill.command("delete")
@click.argument("skill_id")
def skill_delete(skill_id: str):
    """Deactivate/remove a registered Skill."""
    async def run():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.delete(f"{API_BASE_URL}/skills/{skill_id}", timeout=5)
                    if resp.status_code == 204:
                        console.print(f"[green]✔ Skill '{skill_id}' successfully deactivated/deleted.[/green]")
                    else:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error deleting skill:[/red] {e}")
        else:
            from src.core.skill.service import SkillService
            try:
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                    svc = SkillService(session, tenant_id=tenant_id)
                    success = await svc.delete(skill_id)
                    await session.commit()
                    if success:
                        console.print(f"[green]✔ Skill '{skill_id}' successfully deleted locally.[/green]")
                    else:
                        console.print(f"[red]Error: Skill '{skill_id}' not found locally.[/red]")
            except Exception as e:
                console.print(f"[red]Error deleting skill (Local):[/red] {e}")

    asyncio.run(run())


@skill.command("show")
@click.argument("skill_id")
def skill_show(skill_id: str):
    """Show details of a specific Skill."""
    async def run():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/skills/{skill_id}", timeout=5)
                    if resp.status_code == 200:
                        import yaml
                        s = resp.json()
                        console.print(yaml.dump(s, allow_unicode=True, default_flow_style=False))
                    else:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error fetching skill details:[/red] {e}")
        else:
            from src.core.skill.service import SkillService
            import yaml
            try:
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                    svc = SkillService(session, tenant_id=tenant_id)
                    s = await svc.get_by_id(skill_id)
                    if s:
                        console.print(yaml.dump(s, allow_unicode=True, default_flow_style=False))
                    else:
                        console.print(f"[red]Error: Skill '{skill_id}' not found locally.[/red]")
            except Exception as e:
                console.print(f"[red]Error fetching skill (Local):[/red] {e}")

    asyncio.run(run())


@cli.group()
def dag():
    """Manage DAG orchestrations (Phase 2)."""
    pass


@dag.command("split")
@click.argument("task_description")
@click.option("--lightweight", "-l", is_flag=True, help="Force LIGHTWEIGHT mode (zero-container, SQLite, FAISS, local locks)")
def dag_split(task_description: str, lightweight: bool):
    """Auto-decompose a complex task into a DAG."""
    async def split():
        if lightweight:
            from src.config import settings
            settings.system_mode = "lightweight"
            CLIContext.mode_override = "local"
        console.print(f"[yellow]⏳ Decomposing task into DAG...[/yellow]")
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/dags/auto-split", json={"description": task_description}, timeout=60)
                    if resp.status_code != 200:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
                        return

                    res = resp.json()
                    console.print(f"\n[green]✔ DAG Created:[/green] {res['dag_id']}")
                    console.print(f"Name: {res['name']}")
                    
                    table = Table(title="DAG Nodes")
                    table.add_column("Node ID", style="cyan")
                    table.add_column("Name")
                    table.add_column("Skill ID")
                    table.add_column("Dependencies")

                    for node in res["nodes"]:
                        table.add_row(
                            node["node_id"],
                            node["name"],
                            node["skill_id"],
                            ", ".join(node["dependencies"]) or "(none)"
                        )
                    console.print(table)
                    console.print(f"\n[bold]Run command to execute:[/bold] agentdeep dag execute {res['dag_id']}")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.orchestrator.task_splitter import split_task
            from src.core.orchestrator.persistence import save_dag_to_disk
            try:
                dag = await split_task(task_description)
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                save_dag_to_disk(dag, tenant_id=tenant_id)
                console.print(f"\n[green]✔ DAG Created (Local):[/green] {dag.dag_id}")
                console.print(f"Name: {dag.name}")
                
                table = Table(title="DAG Nodes")
                table.add_column("Node ID", style="cyan")
                table.add_column("Name")
                table.add_column("Skill ID")
                table.add_column("Dependencies")

                for node in dag.nodes:
                    table.add_row(
                        node.node_id,
                        node.name,
                        node.skill_id,
                        ", ".join(node.dependencies) or "(none)"
                    )
                console.print(table)
                console.print(f"\n[bold]Run command to execute:[/bold] agentdeep dag execute {dag.dag_id}")
            except Exception as e:
                console.print(f"[red]Error splitting task (Local):[/red] {e}")

    asyncio.run(split())


@dag.command("execute")
@click.argument("dag_id", required=False)
@click.option("--file", "-f", type=click.Path(exists=True), help="Load DAG definition from a YAML file first")
@click.option("--model", "-m", default=None, help="LLM model override for all nodes in the DAG")
@click.option("--lightweight", "-l", is_flag=True, help="Force LIGHTWEIGHT mode (zero-container, SQLite, FAISS, local locks)")
def dag_execute(dag_id: str | None, file: str | None, model: str | None, lightweight: bool):
    """Start asynchronous execution of a DAG."""
    async def run_dag():
        nonlocal dag_id
        if lightweight:
            from src.config import settings
            settings.system_mode = "lightweight"
            CLIContext.mode_override = "local"
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            async with ctx.get_http_client() as client:
                # If a YAML file is provided, read and register it first
                if file:
                    import yaml
                    try:
                        with open(file, "r", encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                        
                        # Post to API to create the DAG
                        resp = await client.post(f"{API_BASE_URL}/dags", json=data, timeout=10)
                        if resp.status_code != 200:
                            console.print(f"[red]Error creating DAG from file {resp.status_code}:[/red] {resp.text}")
                            return
                        res_create = resp.json()
                        dag_id = res_create["dag_id"]
                        console.print(f"[green]✔ DAG registered from file. ID:[/green] {dag_id}")
                    except Exception as ex:
                        console.print(f"[red]Error parsing or registering DAG YAML file:[/red] {ex}")
                        return

                if not dag_id:
                    console.print("[red]Error: Must provide either DAG_ID or --file option.[/red]")
                    return

                console.print(f"[yellow]⏳ Launching DAG execute...[/yellow] {dag_id}")
                console.print("[dim]💡 提示: 执行过程中如果遇到 Agent 需要人工审批 (L3)，该命令会保持挂起状态。[/dim]")
                console.print("[dim]   请在等待期间打开一个新的终端窗口，运行 'python3 src/cli/main.py approval list' 进行审批。[/dim]\n")
                
                payload = {}
                if model:
                    payload["model"] = model

                try:
                    resp = await client.post(f"{API_BASE_URL}/dags/{dag_id}/execute", json=payload, timeout=600)
                    if resp.status_code != 200:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
                        return

                    res = resp.json()
                    console.print(f"\n[green]✔ DAG Executed/Status updated:[/green] {res['dag_id']}")
                    console.print(f"Status: {res['status']}")
                    
                    # Check summary
                    summary = res.get("summary", {})
                    console.print(f"Distribution: {summary.get('color_distribution')}")
                    console.print(f"[bold]Run command to monitor:[/bold] python3 src/cli/main.py dag status {dag_id}")
                except Exception as e:
                    console.print(f"[red]Error execution:[/red] {e}")
        else:
            from src.core.orchestrator.persistence import load_dags_from_disk, save_dag_to_disk
            from src.core.orchestrator.dag_engine import DAGEngine
            from src.core.skill.service import SkillService
            
            async with ctx.get_db() as session:
                tenant_id = await ctx.resolve_tenant_id(session)
            dags = load_dags_from_disk(tenant_id=tenant_id)
            
            # If a YAML file is provided, read and register it first locally
            if file:
                import yaml
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    
                    from src.core.orchestrator.models import DAGNode, DAGEdge, DAGDefinition
                    import uuid
                    nodes = [DAGNode(**n) for n in data.get("nodes", [])]
                    edges = [DAGEdge(**e) for e in data.get("edges", [])]
                    dag = DAGDefinition(
                        dag_id=data.get("dag_id") or f"dag-{uuid.uuid4().hex[:8]}",
                        name=data["name"],
                        description=data.get("description", ""),
                        nodes=nodes,
                        edges=edges,
                    )
                    save_dag_to_disk(dag, tenant_id=tenant_id)
                    dag_id = dag.dag_id
                    console.print(f"[green]✔ DAG registered locally from file. ID:[/green] {dag_id}")
                except Exception as ex:
                    console.print(f"[red]Error parsing or registering DAG YAML file locally:[/red] {ex}")
                    return

            if not dag_id:
                console.print("[red]Error: Must provide either DAG_ID or --file option.[/red]")
                return

            dag = dags.get(dag_id) if not file else dag
            if not dag:
                console.print(f"[red]Error: DAG '{dag_id}' not found locally.[/red]")
                return
            if dag.status == "running":
                console.print(f"[red]Error: DAG is already running locally.[/red]")
                return

            console.print(f"[yellow]⏳ Launching DAG execute (Local)...[/yellow] {dag_id}")
            
            try:
                async with ctx.get_db() as session:
                    skill_svc = SkillService(session, tenant_id=tenant_id)
                    engine = DAGEngine(skill_svc)
                    result = await engine.execute(dag, model_override=model)
                    save_dag_to_disk(result, tenant_id=tenant_id)
                    
                    console.print(f"\n[green]✔ DAG Executed/Status updated (Local):[/green] {result.dag_id}")
                    console.print(f"Status: {result.status}")
                    console.print(f"[bold]Run command to check status:[/bold] agentdeep dag status {dag_id}")
            except Exception as e:
                console.print(f"[red]Local execution failed:[/red] {e}")

    asyncio.run(run_dag())


@dag.command("status")
@click.argument("dag_id")
def dag_status(dag_id: str):
    """Show detailed node status of a running/completed DAG."""
    async def get_status():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/dags/{dag_id}", timeout=5)
                    if resp.status_code != 200:
                        console.print(f"[red]Error {resp.status_code}:[/red] {resp.text}")
                        return

                    res = resp.json()
                    console.print(f"\n[bold]DAG ID:[/bold] {res['dag_id']}")
                    console.print(f"Name: {res['name']}")
                    console.print(f"Overall Status: {res['status']}")

                    table = Table(title="Node Execution Summary")
                    table.add_column("Node ID", style="cyan")
                    table.add_column("Name")
                    table.add_column("Skill ID")
                    table.add_column("Status")
                    table.add_column("Output Status")
                    table.add_column("Error")

                    color_map = {
                        "green": "[green]🟢 Completed[/green]",
                        "red": "[red]🔴 Failed[/red]",
                        "yellow": "[yellow]⏳ Running[/yellow]",
                        "blue": "[blue]🔵 Scheduled[/blue]",
                        "gray": "[dim]⚪ Pending[/dim]",
                        "orange": "[orange]🟠 Pending Approval[/orange]",
                    }

                    for n in res["nodes"]:
                        status_lbl = color_map.get(n["color"], n["color"])
                        out_lbl = "[green]✔ Output Ready[/green]" if n.get("has_result") else "[dim]No Output[/dim]"
                        err_lbl = f"[red]{n.get('error')[:60]}[/red]" if n.get("error") else ""
                        table.add_row(
                            n["node_id"],
                            n["name"],
                            n["skill_id"],
                            status_lbl,
                            out_lbl,
                            err_lbl
                        )
                    console.print(table)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.orchestrator.persistence import load_dags_from_disk
            try:
                async with ctx.get_db() as session:
                    tenant_id = await ctx.resolve_tenant_id(session)
                dags = load_dags_from_disk(tenant_id=tenant_id)
                res = dags.get(dag_id)
                if not res:
                    console.print(f"[red]Error: DAG '{dag_id}' not found locally.[/red]")
                    return

                console.print(f"\n[bold]DAG ID (Local):[/bold] {res.dag_id}")
                console.print(f"Name: {res.name}")
                console.print(f"Overall Status: {res.status}")

                table = Table(title="Node Execution Summary")
                table.add_column("Node ID", style="cyan")
                table.add_column("Name")
                table.add_column("Skill ID")
                table.add_column("Status")
                table.add_column("Output Status")
                table.add_column("Error")

                color_map = {
                    "green": "[green]🟢 Completed[/green]",
                    "red": "[red]🔴 Failed[/red]",
                    "yellow": "[yellow]⏳ Running[/yellow]",
                    "blue": "[blue]🔵 Scheduled[/blue]",
                    "gray": "[dim]⚪ Pending[/dim]",
                    "orange": "[orange]🟠 Pending Approval[/orange]",
                }

                for n in res.nodes:
                    status_lbl = color_map.get(n.color.value, n.color.value)
                    out_lbl = "[green]✔ Output Ready[/green]" if n.result else "[dim]No Output[/dim]"
                    err_lbl = f"[red]{n.error[:60]}[/red]" if n.error else ""
                    table.add_row(
                        n.node_id,
                        n.name,
                        n.skill_id,
                        status_lbl,
                        out_lbl,
                        err_lbl
                    )
                console.print(table)
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(get_status())


@cli.command()
def budget():
    """Fetch current token usage and dollar spend summary."""
    async def fetch_summary():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/budget/summary", timeout=5)
                    res = resp.json()

                    table = Table(title="Token Budget Usage Summary")
                    table.add_column("Metric", style="cyan")
                    table.add_column("Value")

                    table.add_row("Monthly Limit", f"${res.get('monthly_limit_usd', 0.0):.2f}")
                    table.add_row("Total Spent", f"[bold yellow]${res.get('spent_usd', 0.0):.4f}[/bold yellow]")
                    table.add_row("Remaining Budget", f"[bold green]${res.get('remaining_usd', 0.0):.4f}[/bold green]")
                    
                    console.print(table)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.budget.manager import budget_manager
            try:
                res = await budget_manager.get_summary()
                table = Table(title="Token Budget Usage Summary (Local)")
                table.add_column("Metric", style="cyan")
                table.add_column("Value")

                table.add_row("Monthly Limit", f"${res.get('monthly_limit_usd', 0.0):.2f}")
                table.add_row("Total Spent", f"[bold yellow]${res.get('spent_usd', 0.0):.4f}[/bold yellow]")
                table.add_row("Remaining Budget", f"[bold green]${res.get('remaining_usd', 0.0):.4f}[/bold green]")
                
                console.print(table)
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(fetch_summary())


@cli.command()
def pool():
    """Fetch current active agents and their task allocation from the pool."""
    async def fetch_pool():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/health/pool", timeout=5)
                    res = resp.json()

                    table = Table(title="Agent Concurrency Pool Status")
                    table.add_column("Property", style="cyan")
                    table.add_column("Value")

                    table.add_row("Max Concurrency Limit", str(res.get("max_concurrency", 10)))
                    table.add_row("Currently Active Count", f"[bold yellow]{res.get('active_count', 0)}[/bold yellow]")

                    console.print(table)

                    active_agents = res.get("active_agents", {})
                    if active_agents:
                        active_table = Table(title="Active Agent Allocations")
                        active_table.add_column("Agent ID / Skill", style="cyan")
                        active_table.add_column("Running Task ID", style="magenta")

                        for agent_id, task_id in active_agents.items():
                            active_table.add_row(agent_id, task_id)
                        console.print(active_table)
                    else:
                        console.print("[dim]No active agents currently running in the pool.[/dim]")
            except Exception as e:
                console.print(f"[red]Error fetching pool status:[/red] {e}")
        else:
            from src.core.agent.pool import agent_pool
            try:
                active = await agent_pool.get_active_agents()
                table = Table(title="Agent Concurrency Pool Status (Local)")
                table.add_column("Property", style="cyan")
                table.add_column("Value")

                table.add_row("Max Concurrency Limit", str(agent_pool.max_concurrency))
                table.add_row("Currently Active Count", f"[bold yellow]{len(active)}[/bold yellow]")

                console.print(table)

                if active:
                    active_table = Table(title="Active Agent Allocations")
                    active_table.add_column("Agent ID / Skill", style="cyan")
                    active_table.add_column("Running Task ID", style="magenta")

                    for agent_id, task_id in active.items():
                        active_table.add_row(agent_id, task_id)
                    console.print(active_table)
                else:
                    console.print("[dim]No active agents currently running in the pool.[/dim]")
            except Exception as e:
                console.print(f"[red]Error fetching pool status (Local):[/red] {e}")

    asyncio.run(fetch_pool())


@cli.group()
def approval():
    """Manage human-in-the-loop approvals (Phase 3)."""
    pass


@approval.command("list")
def approval_list():
    """List all pending approval requests."""
    async def fetch():
        import json
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.get(f"{API_BASE_URL}/approvals/pending", timeout=5)
                    res = resp.json()

                    if not res:
                        console.print("[dim]No pending approvals.[/dim]")
                        return

                    table = Table(title="Pending Human Approvals")
                    table.add_column("Approval ID", style="cyan")
                    table.add_column("Task ID")
                    table.add_column("Tool")
                    table.add_column("Arguments")

                    for item in res:
                        table.add_row(
                            item["approval_id"],
                            item["task_id"],
                            item["tool_name"],
                            json.dumps(item["arguments"], ensure_ascii=False)[:60] + "..."
                        )
                    console.print(table)
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.governance.approval import approval_manager
            try:
                res = await approval_manager.get_pending_approvals()
                if not res:
                    console.print("[dim]No pending approvals.[/dim]")
                    return

                table = Table(title="Pending Human Approvals (Local)")
                table.add_column("Approval ID", style="cyan")
                table.add_column("Task ID")
                table.add_column("Tool")
                table.add_column("Arguments")

                for item in res:
                    table.add_row(
                        item["approval_id"],
                        item["task_id"],
                        item["tool_name"],
                        json.dumps(item["arguments"], ensure_ascii=False)[:60] + "..."
                    )
                console.print(table)
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(fetch())


@approval.command("approve")
@click.argument("approval_id")
def approval_approve(approval_id: str):
    """Approve a pending request."""
    async def run_action():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/approvals/{approval_id}/action", json={"action": "approve"}, timeout=10)
                    if resp.status_code == 200:
                        console.print(f"[green]✔ Approved:[/green] {approval_id}")
                    else:
                        console.print(f"[red]Failed ({resp.status_code}):[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.governance.approval import approval_manager
            try:
                await approval_manager.approve(approval_id)
                console.print(f"[green]✔ Approved (Local):[/green] {approval_id}")
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(run_action())


@approval.command("reject")
@click.argument("approval_id")
def approval_reject(approval_id: str):
    """Reject a pending request."""
    async def run_action():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/approvals/{approval_id}/action", json={"action": "reject"}, timeout=10)
                    if resp.status_code == 200:
                        console.print(f"[red]✘ Rejected:[/red] {approval_id}")
                    else:
                        console.print(f"[red]Failed ({resp.status_code}):[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.core.governance.approval import approval_manager
            try:
                await approval_manager.reject(approval_id)
                console.print(f"[red]✘ Rejected (Local):[/red] {approval_id}")
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(run_action())


@cli.group()
def evolution():
    """Self-evolution flywheel commands (Phase 4)."""
    pass


@evolution.command("evaluate")
@click.option("--task-id", required=True, help="ID of the task to evaluate.")
@click.option("--task-desc", required=True, help="Description of the task.")
@click.option("--skill-id", required=True, help="ID of the skill used.")
@click.option("--output", required=True, help="Output string of the agent.")
@click.option("--error", default=None, help="Optional error message during task execution.")
def evolution_evaluate(task_id: str, task_desc: str, skill_id: str, output: str, error: str | None):
    """Evaluate trace output, diagnose failure, and auto-patch skill YAML if needed."""
    async def run_eval():
        ctx = CLIContext(api_url=API_BASE_URL)
        mode = await ctx.detect_mode_async()
        if mode == CLIMode.REMOTE:
            try:
                payload = {
                    "task_id": task_id,
                    "task_description": task_desc,
                    "skill_id": skill_id,
                    "trace_steps": [],
                    "agent_output": output,
                    "error_message": error,
                }
                async with ctx.get_http_client() as client:
                    resp = await client.post(f"{API_BASE_URL}/evolution/evaluate", json=payload, timeout=30)
                    if resp.status_code == 200:
                        res = resp.json()
                        console.print(f"[bold green]✔ Evaluation Completed[/bold green]")
                        console.print(f"Consensus Score: [bold yellow]{res['score'] * 100:.1f} / 100.0[/bold yellow]")
                        console.print(f"Rule Score: {res['evaluation']['rule_score'] * 100:.1f} / 100.0")
                        console.print(f"Judge A: {res['evaluation']['judge_a_score'] * 100:.1f} / 100.0")
                        console.print(f"Judge B: {res['evaluation']['judge_b_score'] * 100:.1f} / 100.0")
                        console.print(f"Feedback: [italic dim]{res['evaluation']['feedback']}[/italic dim]")
                        console.print(f"Needs Optimization: {res['needs_optimization']}")
                        
                        if res['diagnostics']:
                            console.print("\n[bold red]Diagnostics Report:[/bold red]")
                            console.print(f"Category: {res['diagnostics']['failure_category']}")
                            console.print(f"Reason: {res['diagnostics']['reason']}")
                            console.print(f"Recommendation: {res['diagnostics']['recommendation']}")
                            
                        console.print(f"Auto-Patched Skill: {res['optimized']}")
                    else:
                        console.print(f"[red]Failed ({resp.status_code}):[/red] {resp.text}")
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")
        else:
            from src.evolution.evaluator import evaluator
            from src.evolution.diagnostics import diagnostics_engine
            from src.evolution.optimizer import skill_optimizer
            from src.core.evolution.ab_manager import ab_manager

            try:
                # 1. Run multi-judge evaluation
                eval_res = await evaluator.evaluate_trace(
                    task_description=task_desc,
                    skill_name=skill_id,
                    trace_steps=[],
                    agent_output=output
                )

                score = eval_res["score"]
                needs_opt = score < 0.6 or error is not None

                diagnostic_res = None
                optimized = False
                variant_info = None

                if needs_opt:
                    diagnostic_res = diagnostics_engine.diagnose(
                        trace_error=error,
                        total_tokens=2000,
                        max_tokens=16000,
                        eval_result=eval_res
                    )

                    try:
                        async with ctx.get_db() as session:
                            new_prompt = await skill_optimizer.generate_optimized_prompt(
                                skill_id=skill_id,
                                diagnostic=diagnostic_res
                            )
                            if new_prompt:
                                variant = await ab_manager.fork_grey_skill(
                                    parent_skill_id=skill_id,
                                    new_prompt=new_prompt,
                                    session=session
                                )
                                if variant:
                                    await session.commit()
                                    optimized = True
                                    variant_info = {
                                        "variant_id": variant.get("skill_id"),
                                        "version": variant.get("version")
                                    }
                    except Exception as db_err:
                        console.print(f"[yellow]Warning: DB fork failed ({db_err}). Falling back to local disk patch...[/yellow]")
                        optimized = await skill_optimizer.optimize_skill(
                            skill_id=skill_id,
                            diagnostic=diagnostic_res
                        )

                console.print(f"[bold green]✔ Evaluation Completed (Local)[/bold green]")
                console.print(f"Consensus Score: [bold yellow]{score * 100:.1f} / 100.0[/bold yellow]")
                console.print(f"Rule Score: {eval_res['rule_score'] * 100:.1f} / 100.0")
                console.print(f"Judge A: {eval_res['judge_a_score'] * 100:.1f} / 100.0")
                console.print(f"Judge B: {eval_res['judge_b_score'] * 100:.1f} / 100.0")
                console.print(f"Feedback: [italic dim]{eval_res['feedback']}[/italic dim]")
                console.print(f"Needs Optimization: {needs_opt}")
                
                if diagnostic_res:
                    console.print("\n[bold red]Diagnostics Report:[/bold red]")
                    console.print(f"Category: {diagnostic_res['failure_category']}")
                    console.print(f"Reason: {diagnostic_res['reason']}")
                    console.print(f"Recommendation: {diagnostic_res['recommendation']}")
                    
                if variant_info:
                    console.print(f"Auto-Patched Skill (Forked Beta): {variant_info['variant_id']} (v{variant_info['version']})")
                else:
                    console.print(f"Auto-Patched Skill (Disk Optimized): {optimized}")
            except Exception as e:
                console.print(f"[red]Error (Local):[/red] {e}")

    asyncio.run(run_eval())


@cli.group()
def config():
    """Manage model configurations dynamically (Phase 5)."""
    pass


@config.command("show")
def config_show():
    """Show current LLM model configuration from settings and .env."""
    from src.config import settings
    table = Table(title="Model Configurations")
    table.add_column("Setting / Variable", style="cyan")
    table.add_column("Current Configured Value", style="green")
    
    table.add_row("Default Model (AGENTDEEP_DEFAULT_MODEL)", settings.default_model)
    table.add_row("Fallback Model (AGENTDEEP_FALLBACK_MODEL)", settings.fallback_model)
    table.add_row("Local Model (AGENTDEEP_LOCAL_MODEL)", settings.local_model)
    table.add_row("Agnes Default Model (AGENTDEEP_AGNES_DEFAULT_MODEL)", settings.agnes_default_model)
    
    console.print(table)


@config.command("set")
@click.argument("key", type=click.Choice(["default_model", "fallback_model", "local_model", "agnes_default_model"]))
@click.argument("value")
def config_set(key: str, value: str):
    """Set and save a default model configuration permanently in .env file."""
    import os
    from pathlib import Path
    _project_root = Path(__file__).resolve().parent.parent.parent
    env_file = _project_root / ".env"
    env_key = f"AGENTDEEP_{key.upper()}"
    lines = []
    found = False

    # Read existing .env if it exists
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(f"{env_key}="):
                    lines.append(f"{env_key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    
    if not found:
        lines.append(f"{env_key}={value}\n")

    # Write back to .env
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)

    console.print(f"[green]✔ Successfully configured {env_key} to '{value}' in {env_file.name}![/green]")
    console.print("[yellow]💡 Note: Please restart the API server (uvicorn) to apply the new default model configuration.[/yellow]")


@cli.command()
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell: str):
    """Generate shell autocompletion command scripts."""
    if shell == "bash":
        console.print('eval "$(_AGENTDEEP_COMPLETE=bash_source agentdeep)"')
    elif shell == "zsh":
        console.print('eval "$(_AGENTDEEP_COMPLETE=zsh_source agentdeep)"')
    elif shell == "fish":
        console.print('_AGENTDEEP_COMPLETE=fish_source agentdeep | source')


if __name__ == "__main__":
    cli()
