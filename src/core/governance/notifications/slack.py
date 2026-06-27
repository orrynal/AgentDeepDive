import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_slack_notification(payload: dict):
    """Asynchronously send approval request notification to Slack Webhook using Block Kit."""
    webhook_url = settings.slack_webhook_url
    if not webhook_url:
        return
        
    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    agent_id = payload.get("agent_id", "unknown")
    priority = payload.get("priority", 50)
    
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "🛡️ *AgentDeepDive HITL Approval Request (L3)*"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"⏳ *Status:* Pending Review  |  *Priority:* {priority}"
                }
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"🆔 *Approval ID:*\n`{approval_id}`"
                },
                {
                    "type": "mrkdwn",
                    "text": f"📋 *Task ID:*\n`{task_id}`"
                },
                {
                    "type": "mrkdwn",
                    "text": f"🤖 *Agent ID:*\n`{agent_id}`"
                },
                {
                    "type": "mrkdwn",
                    "text": f"🛠️ *Tool Name:*\n`{tool_name}`"
                }
            ]
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📝 *Arguments:*\n```json\n{json.dumps(payload['arguments'], ensure_ascii=False, indent=2)}\n```"
            }
        }
    ]
    
    # Append diff block if present
    if payload.get("diff"):
        diff_text = payload["diff"]
        # Truncate if diff is too large for Slack's 3000 char block limit
        if len(diff_text) > 2000:
            diff_text = diff_text[:2000] + "\n... (truncated)"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔍 *File Diff:*\n```diff\n{diff_text}\n```"
            }
        })
        
    # Add Actions
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Approve"
                },
                "style": "primary",
                "value": f"approve:{approval_id}",
                "action_id": "approve_action"
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "❌ Reject"
                },
                "style": "danger",
                "value": f"reject:{approval_id}",
                "action_id": "reject_action"
            }
        ]
    })
    
    try:
        async with httpx.AsyncClient() as client:
            # Wrap blocks in attachments to render a beautiful left color border
            resp = await client.post(webhook_url, json={
                "attachments": [
                    {
                        "color": "#FF8C00",  # Dark orange for pending review
                        "blocks": blocks
                    }
                ]
            }, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send Slack notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending Slack notification", error=str(ex))
