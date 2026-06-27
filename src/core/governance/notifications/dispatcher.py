"""Unified notification dispatcher for workflow status updates and alerts."""

import html
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()


async def dispatch_workflow_notification(
    event_type: str,
    dag_id: str,
    node_id: str | None = None,
    error: str | None = None,
    tenant_id: str | None = None,
    timestamp: str | None = None,
):
    """Dispatch a workflow event alert (e.g. suspended, failed) to all configured notification channels."""
    title = f"⚠️ AgentDeepDive Workflow Alert: {event_type.replace('workflow.', '').upper()}"
    details = (
        f"📋 **DAG ID:** `{dag_id}`\n"
        f"🤖 **Node ID:** `{node_id or 'N/A'}`\n"
        f"🏢 **Tenant ID:** `{tenant_id or 'default'}`\n"
        f"⏰ **Time:** `{timestamp or 'N/A'}`"
    )
    if error:
        details += f"\n❌ **Error Detail:**\n```\n{error}\n```"

    logger.info("Dispatching workflow notification", event_type=event_type, dag_id=dag_id)

    # ── Channel 1: Slack ──────────────────────────────────────────────────
    if settings.slack_webhook_url:
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{title}*"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": details
                }
            }
        ]
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(settings.slack_webhook_url, json={
                    "attachments": [
                        {
                            "color": "#FF0000" if "failed" in event_type else "#FF8C00",
                            "blocks": blocks
                        }
                    ]
                }, timeout=10)
                if resp.status_code not in (200, 201):
                    logger.error("Slack alert response error", status_code=resp.status_code, text=resp.text)
        except Exception as e:
            logger.error("Failed to send Slack alert", error=str(e))

    # ── Channel 2: Telegram ───────────────────────────────────────────────
    if settings.telegram_bot_token and settings.telegram_chat_id:
        tg_text = (
            f"<b>{title}</b>\n\n"
            f"• <b>DAG ID</b>: <code>{dag_id}</code>\n"
            f"• <b>Node ID</b>: <code>{node_id or 'N/A'}</code>\n"
            f"• <b>Tenant ID</b>: <code>{tenant_id or 'default'}</code>\n"
            f"• <b>Time</b>: <code>{timestamp or 'N/A'}</code>\n"
        )
        if error:
            tg_text += f"• <b>Error</b>: <pre><code>{html.escape(error)}</code></pre>"
        
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={
                    "chat_id": settings.telegram_chat_id,
                    "text": tg_text,
                    "parse_mode": "HTML"
                }, timeout=10)
                if resp.status_code != 200:
                    logger.error("Telegram alert response error", status_code=resp.status_code, text=resp.text)
        except Exception as e:
            logger.error("Failed to send Telegram alert", error=str(e))

    # ── Channel 3: Feishu / Lark ──────────────────────────────────────────
    if settings.feishu_webhook_url:
        card = {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": "red" if "failed" in event_type else "orange"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": details
                }
            ]
        }
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(settings.feishu_webhook_url, json={
                    "msg_type": "interactive",
                    "card": card
                }, timeout=10)
                if resp.status_code not in (200, 201):
                    logger.error("Feishu alert response error", status_code=resp.status_code, text=resp.text)
        except Exception as e:
            logger.error("Failed to send Feishu alert", error=str(e))

    # ── Channel 4: DingTalk ────────────────────────────────────────────────
    if settings.dingtalk_webhook_url:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(settings.dingtalk_webhook_url, json={
                    "msgtype": "markdown",
                    "markdown": {
                        "title": title,
                        "text": f"### {title}\n\n{details}"
                    }
                }, timeout=10)
                if resp.status_code not in (200, 201):
                    logger.error("DingTalk alert response error", status_code=resp.status_code, text=resp.text)
        except Exception as e:
            logger.error("Failed to send DingTalk alert", error=str(e))

    # ── Channel 5: Discord ────────────────────────────────────────────────
    if settings.discord_bot_token and settings.discord_channel_id:
        embed = {
            "title": title,
            "description": details,
            "color": 16711680 if "failed" in event_type else 16747520
        }
        url = f"https://discord.com/api/v10/channels/{settings.discord_channel_id}/messages"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bot {settings.discord_bot_token}"},
                    json={"embeds": [embed]},
                    timeout=10
                )
                if resp.status_code not in (200, 201):
                    logger.error("Discord alert response error", status_code=resp.status_code, text=resp.text)
        except Exception as e:
            logger.error("Failed to send Discord alert", error=str(e))
