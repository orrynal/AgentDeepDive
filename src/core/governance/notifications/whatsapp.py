import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_whatsapp_notification(payload: dict):
    """Asynchronously send approval request notification to WhatsApp."""
    token = settings.whatsapp_token
    phone_id = settings.whatsapp_phone_id
    admin_phone = settings.whatsapp_admin_phone
    if not token or not phone_id or not admin_phone:
        return

    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    base_url = settings.app_external_url or "http://localhost:8000"

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    
    whatsapp_payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": admin_phone,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {
                "type": "text",
                "text": "🛡️ AgentDeepDive HITL Approval"
            },
            "body": {
                "text": f"Approval ID: {approval_id}\nTask ID: {task_id}\nTool: {tool_name}\n\nPlease click direct links to resolve."
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"approve:{approval_id}",
                            "title": "Approve"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"reject:{approval_id}",
                            "title": "Reject"
                        }
                    }
                ]
            }
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=whatsapp_payload, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send WhatsApp interactive notification", status=resp.status_code, text=resp.text)
            
            fallback_text = (
                f"🔗 Click to direct action:\n"
                f"Approve: {base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}\n"
                f"Reject: {base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"
            )
            await client.post(
                url,
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": admin_phone,
                    "type": "text",
                    "text": {"body": fallback_text}
                },
                timeout=10
            )
    except Exception as ex:
        logger.error("Error sending WhatsApp notification", error=str(ex))
