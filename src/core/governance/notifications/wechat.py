import json
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_wechat_notification(payload: dict):
    """Asynchronously send approval request notification to WeChat/企业微信."""
    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    args_str = json.dumps(payload["arguments"], ensure_ascii=False, indent=2)
    if len(args_str) > 1000:
        args_str = args_str[:1000] + "\n... (truncated)"

    base_url = settings.app_external_url or "http://localhost:8000"

    # 1. Use Webhook if configured (e.g. Group Bot Webhook)
    if settings.wechat_webhook_url:
        markdown_text = (
            f"## 🛡️ AgentDeepDive HITL 审批申请 (L3)\n"
            f"**审批 ID**: `{approval_id}`\n"
            f"**任务 ID**: `{task_id}`\n"
            f"**执行工具**: `{tool_name}`\n"
            f"**参数明细**:\n```json\n{args_str}\n```\n\n"
            f"请点击下方链接进行审批操作:\n"
            f"👉 [✅ 批准并放行]({base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')})\n"
            f"👉 [❌ 驳回并终止]({base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')})"
        )
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    settings.wechat_webhook_url,
                    json={"msgtype": "markdown", "markdown": {"content": markdown_text}},
                    timeout=10
                )
                if resp.status_code not in (200, 201):
                    logger.error("Failed to send WeChat Webhook notification", status=resp.status_code, text=resp.text)
        except Exception as ex:
            logger.error("Error sending WeChat Webhook notification", error=str(ex))
        return

    # 2. Use Enterprise WeChat API (Corp Application Send Message)
    corp_id = settings.wechat_corp_id
    corp_secret = settings.wechat_corp_secret
    agent_id = settings.wechat_agent_id
    if not corp_id or not corp_secret or not agent_id:
        return

    try:
        async with httpx.AsyncClient() as client:
            # Get Access Token
            token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={corp_secret}"
            token_resp = await client.get(token_url, timeout=5)
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                logger.error("Failed to fetch WeChat access token", data=token_data)
                return

            # Send template_card message
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
            card_payload = {
                "touser": "@all",
                "msgtype": "template_card",
                "agentid": agent_id,
                "template_card": {
                    "card_type": "button_interaction",
                    "source": {"desc": "AgentDeepDive"},
                    "main_title": {"title": "🛡️ HITL Approval Request (L3)"},
                    "horizontal_content_list": [
                        {"keyname": "Approval ID", "value": approval_id},
                        {"keyname": "Task ID", "value": task_id},
                        {"keyname": "Tool Name", "value": tool_name}
                    ],
                    "button_list": [
                        {
                            "text": "✅ Approve",
                            "style": 1,
                            "type": 1,  # Redirect link
                            "url": f"{base_url}/api/v1/approvals/{approval_id}/approve_direct?token={payload.get('approve_token', '')}"
                        },
                        {
                            "text": "❌ Reject",
                            "style": 2,
                            "type": 1,  # Redirect link
                            "url": f"{base_url}/api/v1/approvals/{approval_id}/reject_direct?token={payload.get('reject_token', '')}"
                        }
                    ]
                }
            }
            resp = await client.post(send_url, json=card_payload, timeout=10)
            if resp.status_code not in (200, 201):
                logger.error("Failed to send WeChat application message", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending WeChat application message", error=str(ex))
