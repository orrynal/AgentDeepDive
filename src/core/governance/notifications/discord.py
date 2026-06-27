import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_discord_notification(payload: dict):
    """Asynchronously send approval request notification to Discord Channel."""
    bot_token = settings.discord_bot_token
    channel_id = settings.discord_channel_id
    if not bot_token or not channel_id:
        return

    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    args_str = json.dumps(payload["arguments"], ensure_ascii=False, indent=2)
    if len(args_str) > 1000:
        args_str = args_str[:1000] + "\n... (truncated)"

    embed = {
        "title": "🛡️ AgentDeepDive HITL Approval (L3)",
        "description": f"**Task ID:** `{task_id}`\n**Tool:** `{tool_name}`",
        "color": 16747520, # Orange
        "fields": [
            {"name": "Approval ID", "value": f"`{approval_id}`", "inline": True},
            {"name": "Priority", "value": str(payload.get("priority", 50)), "inline": True}
        ]
    }
    if payload.get("diff"):
        diff_text = payload["diff"]
        if len(diff_text) > 1000:
            diff_text = diff_text[:1000] + "\n... (truncated)"
        embed["fields"].append({"name": "File Diff", "value": f"```diff\n{diff_text}\n```", "inline": False})
    else:
        embed["fields"].append({"name": "Arguments", "value": f"```json\n{args_str}\n```", "inline": False})

    # Actions redirecting to GET endpoints on external host
    base_url = settings.app_external_url or "http://localhost:8000"
    components = [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "label": "✅ Approve",
                    "style": 5,  # Link button
                    "url": f"{base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}"
                },
                {
                    "type": 2,
                    "label": "❌ Reject",
                    "style": 5,  # Link button
                    "url": f"{base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"
                }
            ]
        }
    ]

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bot {bot_token}"},
                json={"embeds": [embed], "components": components},
                timeout=10
            )
            if resp.status_code not in (200, 201):
                logger.error("Failed to send Discord notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending Discord notification", error=str(ex))
