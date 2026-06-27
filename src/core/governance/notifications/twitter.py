import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_twitter_notification(payload: dict):
    """Asynchronously send approval request notification to X / Twitter DM."""
    token = settings.twitter_bearer_token
    admin_userid = settings.twitter_admin_userid
    if not token or not admin_userid:
        return

    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    base_url = settings.app_external_url or "http://localhost:8000"

    text = (
        f"🛡️ AgentDeepDive HITL Approval (L3)\n\n"
        f"• Approval ID: {approval_id}\n"
        f"• Task ID: {task_id}\n"
        f"• Tool: {tool_name}\n\n"
        f"Choose an option:\n"
        f"Approve: {base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}\n"
        f"Reject: {base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"
    )

    url = f"https://api.twitter.com/2/dm_conversations/with/{admin_userid}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json={"message": {"text": text}}, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send Twitter DM notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending Twitter DM notification", error=str(ex))
