import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_feishu_notification(payload: dict):
    """Asynchronously send approval request notification to Feishu/Lark Webhook using Interactive Cards."""
    webhook_url = settings.feishu_webhook_url
    if not webhook_url:
        return
        
    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    agent_id = payload.get("agent_id", "unknown")
    priority = payload.get("priority", 50)
    
    card_elements = [
        {
            "tag": "column_set",
            "flex_mode": "stretch",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"🆔 **Approval ID**\n`{approval_id}`"
                        }
                    ]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"📋 **Task ID**\n`{task_id}`"
                        }
                    ]
                }
            ]
        },
        {
            "tag": "column_set",
            "flex_mode": "stretch",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"🤖 **Agent ID**\n`{agent_id}`"
                        }
                    ]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"🛠️ **Tool Name**\n`{tool_name}`"
                        }
                    ]
                }
            ]
        },
        {
            "tag": "column_set",
            "flex_mode": "stretch",
            "columns": [
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": "⏳ **Status**\nPending Review"
                        }
                    ]
                },
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": f"⚠️ **Priority**\n`{priority}`"
                        }
                    ]
                }
            ]
        },
        {
            "tag": "hr"
        },
        {
            "tag": "markdown",
            "content": f"📝 **Arguments**:\n```json\n{json.dumps(payload['arguments'], ensure_ascii=False, indent=2)}\n```"
        }
    ]
    
    # Append diff block if present
    if payload.get("diff"):
        diff_text = payload["diff"]
        if len(diff_text) > 2000:
            diff_text = diff_text[:2000] + "\n... (truncated)"
        card_elements.append({
            "tag": "markdown",
            "content": f"🔍 **File Diff**:\n```diff\n{diff_text}\n```"
        })
        
    # Add Actions
    card_elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "✅ Approve"
                },
                "type": "primary",
                "value": {
                    "action": "approve",
                    "approval_id": approval_id
                }
            },
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "❌ Reject"
                },
                "type": "danger",
                "value": {
                    "action": "reject",
                    "approval_id": approval_id
                }
            }
        ]
    })
    
    card = {
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🛡️ AgentDeepDive HITL Approval (L3)"
            },
            "template": "orange"  # Warm template matching pending review state
        },
        "elements": card_elements
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json={"msg_type": "interactive", "card": card}, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send Feishu notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending Feishu notification", error=str(ex))
