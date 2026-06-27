import json
import html
import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()

async def send_telegram_notification(payload: dict):
    """Asynchronously send approval request notification to Telegram chat using HTML format."""
    approval_id = payload["approval_id"]
    task_id = payload["task_id"]
    tool_name = payload["tool_name"]
    args_html = html.escape(json.dumps(payload["arguments"], ensure_ascii=False, indent=2))
    
    text = (
        f"🔔 <b>AgentDeepDive Approval Request (L3)</b>\n\n"
        f"• <b>Approval ID</b>: <code>{approval_id}</code>\n"
        f"• <b>Task ID</b>: <code>{task_id}</code>\n"
        f"• <b>Tool</b>: <code>{tool_name}</code>\n"
        f"• <b>Arguments</b>:\n<pre><code class=\"language-json\">{args_html}</code></pre>\n\n"
        f"Please review and select an action below:"
    )
    
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
                {"text": "❌ Reject", "callback_data": f"reject:{approval_id}"}
            ]
        ]
    }
    
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": reply_markup
            }, timeout=10)
            if resp.status_code != 200:
                logger.error("Failed to send Telegram notification", status=resp.status_code, text=resp.text)
    except Exception as ex:
        logger.error("Error sending Telegram notification", error=str(ex))
