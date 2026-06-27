import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_dingtalk_notification(payload: dict):
    """Asynchronously send approval request notification to DingTalk Webhook using ActionCards."""
    webhook_url = settings.dingtalk_webhook_url
    if not webhook_url:
        return
        
    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    
    text = (
        f"### 🔔 AgentDeepDive Approval Request (L3)\n\n"
        f"- **Approval ID**: `{approval_id}`\n"
        f"- **Task ID**: `{task_id}`\n"
        f"- **Tool**: `{tool_name}`\n\n"
        f"**Arguments**:\n```json\n{json.dumps(payload['arguments'], ensure_ascii=False, indent=2)}\n```\n\n"
    )
    
    if payload.get("diff"):
        diff_text = payload["diff"]
        if len(diff_text) > 2000:
            diff_text = diff_text[:2000] + "\n... (truncated)"
        text += f"**File Diff**:\n```diff\n{diff_text}\n```\n\n"
        
    text += "Please review and choose an action:"
    
    # Actions redirecting to GET endpoints on external host
    base_url = settings.app_external_url or "http://localhost:8000"
    btns = [
        {
            "title": "✅ Approve",
            "actionURL": f"{base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}"
        },
        {
            "title": "❌ Reject",
            "actionURL": f"{base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"
        }
    ]
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json={
                "msgtype": "actionCard",
                "actionCard": {
                    "title": "AgentDeepDive Approval Request (L3)",
                    "text": text,
                    "btnOrientation": "1",
                    "btns": btns
                }
            }, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send DingTalk notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending DingTalk notification", error=str(ex))
