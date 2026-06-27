import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_qq_notification(payload: dict):
    """Asynchronously send approval request notification to QQ Channel."""
    appid = settings.qq_bot_appid
    token = settings.qq_bot_token
    channel_id = settings.qq_channel_id
    if not appid or not token or not channel_id:
        return

    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    args_str = json.dumps(payload["arguments"], ensure_ascii=False, indent=2)
    if len(args_str) > 1000:
        args_str = args_str[:1000] + "\n... (truncated)"

    base_url = settings.app_external_url or "http://localhost:8000"

    url = f"https://api.sgroup.qq.com/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {appid}.{token}"}
    
    qq_payload = {
        "markdown": {
            "content": (
                f"🛡️ **AgentDeepDive HITL 审批**\n\n"
                f"- 审批 ID: `{approval_id}`\n"
                f"- 任务 ID: `{task_id}`\n"
                f"- 工具名称: `{tool_name}`\n\n"
                f"**参数明细**:\n```json\n{args_str}\n```"
            )
        },
        "keyboard": {
            "content": {
                "rows": [
                    {
                        "buttons": [
                            {
                                "id": "1",
                                "render_data": {"label": "✅ Approve", "style": 1},
                                "action": {"type": 0, "permission": {"type": 2}, "data": f"{base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}"}
                            },
                            {
                                "id": "2",
                                "render_data": {"label": "❌ Reject", "style": 0},
                                "action": {"type": 0, "permission": {"type": 2}, "data": f"{base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"}
                            }
                        ]
                    }
                ]
            }
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=qq_payload, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send QQ notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending QQ notification", error=str(ex))
