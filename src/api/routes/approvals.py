from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from src.core.governance.approval import approval_manager
from src.core.crypto.wechat import WeChatMsgCrypt
from src.api.security import verify_api_key
from src.config import settings
import structlog
import hmac
import hashlib
import base64
import struct

logger = structlog.get_logger()

from src.core.auth.models import UserModel
from src.core.auth.security import get_current_user
from src.core.governance.approval import APPROVAL_KEY_PREFIX
import json

router = APIRouter()


class ApprovalActionRequest(BaseModel):
    action: str  # "approve" or "reject"
    arguments: dict | None = None


class ApprovalDirectRequest(BaseModel):
    arguments: dict | None = None


@router.get("/approvals/pending", response_model=list[dict])
async def get_pending_approvals(user: UserModel = Depends(get_current_user)):
    """List all pending approval requests."""
    all_approvals = await approval_manager.get_pending_approvals()
    return [
        appr for appr in all_approvals 
        if (appr.get("tenant_id") or "00000000-0000-0000-0000-000000000000") == user.tenant_id
    ]


@router.post("/approvals/diagnose/{channel}", response_model=dict)
async def diagnose_webhook_connection(channel: str, user: UserModel = Depends(get_current_user)):
    """Trigger a mock notification to the specified approval channel to test connectivity."""
    if user.role not in ("admin", "developer"):
        raise HTTPException(403, "Permission denied")

    normalized_channel = channel.lower()
    import time
    
    mock_payload = {
        "approval_id": "test-diag-123",
        "task_id": "diag-task",
        "agent_id": "diag-agent",
        "tool_name": "diagnose_webhook_connection",
        "arguments": {
            "test_message": "This is a connectivity diagnostic notification from AgentDeepDive.",
            "timestamp": time.time()
        },
        "priority": 10,
        "created_at": time.time(),
        "diff": "--- a/test_diagnostics\n+++ b/test_diagnostics\n@@ -1,1 +1,1 @@\n-offline\n+online"
    }

    if normalized_channel == "telegram":
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise HTTPException(400, "Telegram is not configured in settings")
        try:
            await approval_manager._send_telegram_notification(mock_payload)
            return {"status": "success", "message": "Telegram diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"Telegram connection test failed: {str(ex)}")

    elif normalized_channel == "slack":
        if not settings.slack_webhook_url:
            raise HTTPException(400, "Slack webhook url is not configured in settings")
        try:
            await approval_manager._send_slack_notification(mock_payload)
            return {"status": "success", "message": "Slack diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"Slack connection test failed: {str(ex)}")

    elif normalized_channel in ("feishu", "lark"):
        if not settings.feishu_webhook_url:
            raise HTTPException(400, "Feishu webhook url is not configured in settings")
        try:
            await approval_manager._send_feishu_notification(mock_payload)
            return {"status": "success", "message": "Feishu diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"Feishu connection test failed: {str(ex)}")

    elif normalized_channel == "dingtalk":
        if not settings.dingtalk_webhook_url:
            raise HTTPException(400, "DingTalk webhook url is not configured in settings")
        try:
            await approval_manager._send_dingtalk_notification(mock_payload)
            return {"status": "success", "message": "DingTalk diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"DingTalk connection test failed: {str(ex)}")

    elif normalized_channel == "discord":
        if not settings.discord_bot_token or not settings.discord_channel_id:
            raise HTTPException(400, "Discord is not configured in settings")
        try:
            await approval_manager._send_discord_notification(mock_payload)
            return {"status": "success", "message": "Discord diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"Discord connection test failed: {str(ex)}")

    elif normalized_channel == "wechat":
        if not settings.wechat_webhook_url and not (settings.wechat_corp_id and settings.wechat_corp_secret):
            raise HTTPException(400, "WeChat is not configured in settings")
        try:
            await approval_manager._send_wechat_notification(mock_payload)
            return {"status": "success", "message": "WeChat diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"WeChat connection test failed: {str(ex)}")

    elif normalized_channel == "qq":
        if not settings.qq_bot_appid or not settings.qq_bot_token or not settings.qq_channel_id:
            raise HTTPException(400, "QQ Bot is not configured in settings")
        try:
            await approval_manager._send_qq_notification(mock_payload)
            return {"status": "success", "message": "QQ Bot diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"QQ Bot connection test failed: {str(ex)}")

    elif normalized_channel in ("twitter", "x"):
        if not settings.twitter_bearer_token or not settings.twitter_admin_userid:
            raise HTTPException(400, "Twitter/X is not configured in settings")
        try:
            await approval_manager._send_twitter_notification(mock_payload)
            return {"status": "success", "message": "Twitter/X diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"Twitter/X connection test failed: {str(ex)}")

    elif normalized_channel == "whatsapp":
        if not settings.whatsapp_token or not settings.whatsapp_phone_id or not settings.whatsapp_admin_phone:
            raise HTTPException(400, "WhatsApp is not configured in settings")
        try:
            await approval_manager._send_whatsapp_notification(mock_payload)
            return {"status": "success", "message": "WhatsApp diagnostic message sent"}
        except Exception as ex:
            raise HTTPException(502, f"WhatsApp connection test failed: {str(ex)}")

    else:
        raise HTTPException(400, f"Unsupported channel: '{channel}'. Supported channels: telegram, slack, feishu, dingtalk, discord, wechat, qq, twitter, whatsapp")


@router.post("/approvals/{approval_id}/action", response_model=dict)
async def take_approval_action(approval_id: str, body: ApprovalActionRequest, user: UserModel = Depends(get_current_user)):
    """Approve or reject a pending approval request."""
    if user.role not in ("admin", "developer"):
        raise HTTPException(403, "Permission denied")

    # Verify the approval belongs to the user's tenant if it exists in Redis
    r = await approval_manager._get_redis()
    data_str = await r.get(f"{APPROVAL_KEY_PREFIX}{approval_id}")
    if data_str:
        payload = json.loads(data_str)
        if (payload.get("tenant_id") or "00000000-0000-0000-0000-000000000000") != user.tenant_id:
            raise HTTPException(404, "Approval request not found")

    if body.action == "approve":
        await approval_manager.approve(approval_id, body.arguments)
        return {"status": "ok", "message": f"Request {approval_id} approved"}
    elif body.action == "reject":
        await approval_manager.reject(approval_id)
        return {"status": "ok", "message": f"Request {approval_id} rejected"}
    else:
        raise HTTPException(400, "Action must be either 'approve' or 'reject'")


@router.post("/approvals/{approval_id}/{action}", response_model=dict)
async def take_approval_action_direct(
    approval_id: str,
    action: str,
    body: ApprovalDirectRequest = ApprovalDirectRequest(),
    user: UserModel = Depends(get_current_user)
):
    """Approve or reject a pending approval request directly via URL path (compatible with frontend fetch status)."""
    if user.role not in ("admin", "developer"):
        raise HTTPException(403, "Permission denied")

    # Verify the approval belongs to the user's tenant if it exists in Redis
    r = await approval_manager._get_redis()
    data_str = await r.get(f"{APPROVAL_KEY_PREFIX}{approval_id}")
    if data_str:
        payload = json.loads(data_str)
        if (payload.get("tenant_id") or "00000000-0000-0000-0000-000000000000") != user.tenant_id:
            raise HTTPException(404, "Approval request not found")

    normalized_action = action.lower()
    if normalized_action in ("approve", "approved"):
        await approval_manager.approve(approval_id, body.arguments)
        return {"status": "ok", "message": f"Request {approval_id} approved"}
    elif normalized_action in ("reject", "rejected"):
        await approval_manager.reject(approval_id)
        return {"status": "ok", "message": f"Request {approval_id} rejected"}
    else:
        raise HTTPException(400, "Action must be 'approve', 'approved', 'reject', or 'rejected'")


@router.post("/approvals/telegram-webhook")
async def telegram_webhook(payload: dict, request: Request):
    """Callback webhook for Telegram inline keyboard approvals (Phase 5)."""
    # 1. Secret token verification (if configured)
    if settings.telegram_webhook_secret:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_header != settings.telegram_webhook_secret:
            logger.warning("Unauthorized Telegram webhook call (secret token mismatch)")
            raise HTTPException(status_code=401, detail="Unauthorized")

    callback_query = payload.get("callback_query")
    if not callback_query:
        return {"status": "ignored"}
    
    # 2. Chat ID origin validation (if configured)
    chat = callback_query.get("message", {}).get("chat", {})
    chat_id = chat.get("id")
    if settings.telegram_chat_id and str(chat_id) != str(settings.telegram_chat_id):
        logger.warning("Unauthorized Telegram webhook call (chat ID mismatch)", chat_id=chat_id)
        raise HTTPException(status_code=403, detail="Forbidden")

    data = callback_query.get("data")
    if not data or ":" not in data:
        return {"status": "invalid_data"}
    
    action, approval_id = data.split(":", 1)
    
    # Process action
    if action == "approve":
        await approval_manager.approve(approval_id)
        message = f"✅ Request {approval_id} APPROVED via Telegram."
    elif action == "reject":
        await approval_manager.reject(approval_id)
        message = f"❌ Request {approval_id} REJECTED via Telegram."
    else:
        return {"status": "unknown_action"}
        
    # Edit the message on Telegram to show it has been resolved
    import httpx
    
    try:
        chat_id = callback_query["message"]["chat"]["id"]
        message_id = callback_query["message"]["message_id"]
        original_text = callback_query["message"].get("text", "")
        
        updated_text = f"{original_text}\n\nProcessed: {message}"
        
        # Send editMessageText request to Telegram
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/editMessageText"
        async with httpx.AsyncClient() as client:
            await client.post(url, json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": updated_text
            }, timeout=5)
            # Answer callback query
            await client.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/answerCallbackQuery", json={
                "callback_query_id": callback_query["id"],
                "text": f"Processed: {action.upper()}"
            }, timeout=5)
    except Exception as ex:
        # Don't crash if Telegram API fails to respond or is inaccessible
        pass
        
    return {"status": "ok", "message": message}


from fastapi.responses import HTMLResponse

@router.get("/approvals/{approval_id}/{action}_direct", response_class=HTMLResponse)
async def take_approval_action_get(approval_id: str, action: str, token: str | None = None):
    """Approve or reject a pending approval request directly via GET (e.g. from DingTalk actionURL)."""
    normalized_action = action.lower()
    if normalized_action == "approved":
        normalized_action = "approve"
    elif normalized_action == "rejected":
        normalized_action = "reject"
        
    from src.core.governance.approval import generate_approval_signature
    expected_token = generate_approval_signature(approval_id, normalized_action, settings.jwt_secret)
    if not token or not hmac.compare_digest(token, expected_token):
        raise HTTPException(403, "Invalid or missing approval verification token.")
    if normalized_action in ("approve", "approved"):
        await approval_manager.approve(approval_id)
        title = "Approval Granted"
        color = "#10b981"  # Emerald green
        desc = f"Request <b>{approval_id}</b> has been successfully approved. The agent will resume execution immediately."
    elif normalized_action in ("reject", "rejected"):
        await approval_manager.reject(approval_id)
        title = "Approval Rejected"
        color = "#ef4444"  # Red
        desc = f"Request <b>{approval_id}</b> has been rejected. The agent task will be aborted."
    else:
        raise HTTPException(400, "Action must be 'approve' or 'reject'")
        
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #0f172a;
                color: #f1f5f9;
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
            }}
            .card {{
                background-color: #1e293b;
                border-radius: 12px;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                padding: 40px;
                max-width: 450px;
                text-align: center;
                border-top: 5px solid {color};
            }}
            h1 {{
                color: {color};
                font-size: 24px;
                margin-top: 0;
            }}
            p {{
                font-size: 16px;
                line-height: 1.6;
                color: #94a3b8;
            }}
            .footer {{
                margin-top: 30px;
                font-size: 12px;
                color: #64748b;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>{title}</h1>
            <p>{desc}</p>
            <div class="footer">AgentDeepDive Human-In-The-Loop Approval System</div>
        </div>
    </body>
    </html>
    """
    return html_content


@router.post("/approvals/slack-webhook")
async def slack_webhook(request: Request):
    """Callback webhook for Slack interactive actions."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    from urllib.parse import parse_qs
    parsed = parse_qs(body_str)
    payload_list = parsed.get("payload")
    if not payload_list:
        raise HTTPException(400, "Missing payload")
    payload_str = payload_list[0]
        
    import json
    payload = json.loads(payload_str)
    
    actions = payload.get("actions", [])
    if not actions:
        return {"status": "ignored"}
        
    action_val = actions[0].get("value")
    if not action_val or ":" not in action_val:
        return {"status": "invalid_action"}
        
    action, approval_id = action_val.split(":", 1)
    if action == "approve":
        await approval_manager.approve(approval_id)
        message = f"✅ Request {approval_id} APPROVED via Slack."
    elif action == "reject":
        await approval_manager.reject(approval_id)
        message = f"❌ Request {approval_id} REJECTED via Slack."
    else:
        return {"status": "unknown_action"}
        
    response_url = payload.get("response_url")
    if response_url:
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                await client.post(response_url, json={
                    "replace_original": True,
                    "text": f"Processed: {message}"
                }, timeout=5)
        except Exception:
            pass
            
    return {"status": "ok", "message": message}


@router.post("/approvals/feishu-webhook")
async def feishu_webhook(payload: dict):
    """Callback webhook for Feishu card action callback."""
    action_info = payload.get("action")
    if not action_info:
        return {"status": "ignored"}
        
    value = action_info.get("value")
    if not value or not isinstance(value, dict):
        return {"status": "invalid_value"}
        
    action = value.get("action")
    approval_id = value.get("approval_id")
    if not action or not approval_id:
        return {"status": "missing_fields"}
        
    if action == "approve":
        await approval_manager.approve(approval_id)
        message = f"✅ Request {approval_id} APPROVED via Feishu."
    elif action == "reject":
        await approval_manager.reject(approval_id)
        message = f"❌ Request {approval_id} REJECTED via Feishu."
    else:
        return {"status": "unknown_action"}
        
    return {
        "toast": f"Processed: {message}",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🔔 AgentDeepDive Approval Request (L3)"
                },
                "template": "grey"
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**Status**: {message}"
                }
            ]
        }
    }


@router.post("/approvals/discord-webhook")
async def discord_webhook(request: Request):
    """Callback webhook for Discord interaction components."""
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    
    # 1. Optional signature verification (Must occur before processing any payload)
    if settings.discord_public_key:
        signature = request.headers.get("X-Signature-Ed25519")
        timestamp = request.headers.get("X-Signature-Timestamp")
        if not signature or not timestamp:
            logger.warning("Discord webhook request missing signature or timestamp headers")
            raise HTTPException(401, "Missing signature headers")
        
        try:
            public_key_bytes = bytes.fromhex(settings.discord_public_key)
        except ValueError as ex:
            logger.error("Configured discord_public_key is not a valid hex string", error=str(ex))
            raise HTTPException(500, "Invalid server configuration")
            
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError as ex:
            logger.warning("Discord webhook signature decoding failed (invalid hex format)", error=str(ex))
            raise HTTPException(400, "Invalid signature hex format")
            
        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError
            verify_key = VerifyKey(public_key_bytes)
            verify_key.verify(f"{timestamp}{body_str}".encode(), signature_bytes)
        except ImportError:
            logger.error("nacl library is missing from dependencies despite settings.discord_public_key being set")
            raise HTTPException(500, "Cryptography library missing")
        except BadSignatureError:
            logger.warning("Discord webhook signature verification failed: invalid signature")
            raise HTTPException(401, "Invalid request signature")
        except Exception as ex:
            logger.error("Discord signature verification encountered an unexpected error", error=str(ex))
            raise HTTPException(500, "Internal error validating signature")

    # 2. Parse body
    import json
    try:
        payload = json.loads(body_str)
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    interaction_type = payload.get("type")
    
    # 3. Discord PING verification
    if interaction_type == 1:
        # PING -> return PONG
        return {"type": 1}

    if interaction_type == 3:  # MESSAGE_COMPONENT
        custom_id = payload.get("data", {}).get("custom_id")
        if not custom_id or ":" not in custom_id:
            return {"type": 4, "data": {"content": "Invalid action format."}}

        action, approval_id = custom_id.split(":", 1)
        if action == "approve":
            await approval_manager.approve(approval_id)
            msg = f"✅ Approved request {approval_id} via Discord."
        elif action == "reject":
            await approval_manager.reject(approval_id)
            msg = f"❌ Rejected request {approval_id} via Discord."
        else:
            msg = "Unknown action."

        # Response code 7 updates the original message
        return {
            "type": 7,
            "data": {
                "content": msg,
                "embeds": [],
                "components": []
            }
        }

    return {"type": 4, "data": {"content": "Interaction type ignored."}}

@router.get("/approvals/wechat-webhook")
@router.post("/approvals/wechat-webhook")
async def wechat_webhook(request: Request):
    """Callback webhook for WeChat Corp message server."""
    # 1. URL Verification (GET request)
    if request.method == "GET":
        params = request.query_params
        msg_signature = params.get("msg_signature")
        timestamp = params.get("timestamp")
        nonce = params.get("nonce")
        echostr = params.get("echostr")
        if echostr:
            if settings.wechat_token and settings.wechat_encoding_aes_key:
                crypt = WeChatMsgCrypt(
                    token=settings.wechat_token,
                    encoding_aes_key=settings.wechat_encoding_aes_key,
                    corp_id=settings.wechat_corp_id,
                )
                if not crypt.verify_signature(msg_signature, timestamp, nonce, echostr):
                    logger.warning("WeChat webhook verification failed: Invalid signature")
                    raise HTTPException(401, "Invalid request signature")
                try:
                    decrypted_echostr = crypt.decrypt(echostr)
                    return HTMLResponse(content=decrypted_echostr)
                except Exception as ex:
                    logger.error("Failed to decrypt WeChat echostr", error=str(ex))
                    raise HTTPException(400, "Failed to decrypt verification message")
            else:
                return HTMLResponse(content=echostr)
        return {"status": "ok"}

    # 2. Callback Events (POST request)
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8")
    
    params = request.query_params
    msg_signature = params.get("msg_signature")
    timestamp = params.get("timestamp")
    nonce = params.get("nonce")
    
    import defusedxml.ElementTree as ET
    try:
        root = ET.fromstring(body_str)
        encrypt_node = root.find("Encrypt")
        
        if encrypt_node is not None and encrypt_node.text:
            encrypt_str = encrypt_node.text.strip()
            if settings.wechat_token and settings.wechat_encoding_aes_key:
                crypt = WeChatMsgCrypt(
                    token=settings.wechat_token,
                    encoding_aes_key=settings.wechat_encoding_aes_key,
                    corp_id=settings.wechat_corp_id,
                )
                if not crypt.verify_signature(msg_signature, timestamp, nonce, encrypt_str):
                    logger.warning("WeChat POST webhook signature verification failed")
                    raise HTTPException(401, "Invalid request signature")
                try:
                    plain_xml = crypt.decrypt(encrypt_str)
                    root = ET.fromstring(plain_xml)
                except Exception as ex:
                    logger.error("Failed to decrypt WeChat message payload", error=str(ex))
                    raise HTTPException(400, "Failed to decrypt payload")
            else:
                logger.warning("Received encrypted WeChat message but credentials are not configured")
                return {"status": "ignored"}
        
        event_key = root.findtext("EventKey")
        if event_key and ":" in event_key:
            action, approval_id = event_key.split(":", 1)
            if action == "approve":
                await approval_manager.approve(approval_id)
            elif action == "reject":
                await approval_manager.reject(approval_id)
    except HTTPException:
        raise
    except Exception as ex:
        logger.error("Failed to parse WeChat callback XML", error=str(ex))
        raise HTTPException(400, f"Malformed callback payload: {str(ex)}")

    return {"status": "ok"}


@router.post("/approvals/qq-webhook")
async def qq_webhook(payload: dict):
    """Callback webhook for QQ Bot interactions."""
    event = payload.get("t")
    data = payload.get("d", {})
    
    if event == "MESSAGE_BUTTON_CLICKED" or data.get("button_data"):
        button_data = data.get("button_data") or data.get("data")
        if button_data and ":" in button_data:
            action, approval_id = button_data.split(":", 1)
            if action == "approve":
                await approval_manager.approve(approval_id)
            elif action == "reject":
                await approval_manager.reject(approval_id)
                
    return {"status": "ok"}


@router.get("/approvals/twitter-webhook")
async def twitter_webhook_crc(crc_token: str | None = None):
    """GET handler for Twitter/X Account Activity API Webhook Challenge Response Check (CRC)."""
    if not crc_token:
        return {"status": "ok"}
        
    secret = settings.twitter_consumer_secret or settings.twitter_bearer_token
    if not secret:
        logger.warning("Twitter signature secret is not configured for CRC")
        return {"status": "unconfigured"}
        
    key = secret.encode("utf-8")
    signature = hmac.new(key, crc_token.encode("utf-8"), hashlib.sha256).digest()
    response_token = f"sha256={base64.b64encode(signature).decode('utf-8')}"
    
    return {"response_token": response_token}


@router.post("/approvals/twitter-webhook")
async def twitter_webhook_events(request: Request):
    """POST handler for Twitter/X DM and account activity events."""
    if settings.twitter_consumer_secret:
        signature = request.headers.get("x-twitter-webhooks-signature")
        if not signature:
            logger.warning("Missing x-twitter-webhooks-signature header")
            raise HTTPException(401, "Missing signature header")
            
        body_bytes = await request.body()
        key = settings.twitter_consumer_secret.encode("utf-8")
        computed_sig = hmac.new(key, body_bytes, hashlib.sha256).digest()
        expected_sig = f"sha256={base64.b64encode(computed_sig).decode('utf-8')}"
        if not hmac.compare_digest(expected_sig, signature):
            logger.warning("Twitter webhook signature verification failed")
            raise HTTPException(401, "Invalid request signature")
            
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
        
    dm_events = payload.get("direct_message_events", [])
    for event in dm_events:
        message_create = event.get("message_create", {})
        quick_reply = message_create.get("message_data", {}).get("quick_reply_response", {})
        metadata = quick_reply.get("metadata")
        if metadata and ":" in metadata:
            action, approval_id = metadata.split(":", 1)
            if action == "approve":
                await approval_manager.approve(approval_id)
            elif action == "reject":
                await approval_manager.reject(approval_id)
                
    return {"status": "ok"}


@router.get("/approvals/whatsapp-webhook")
async def whatsapp_webhook_verify(request: Request):
    """GET verification endpoint for WhatsApp webhook (Meta Cloud API)."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and challenge:
        if settings.whatsapp_verify_token and token != settings.whatsapp_verify_token:
            logger.warning("WhatsApp webhook verification token mismatch")
            raise HTTPException(401, "Verification token mismatch")
        return HTMLResponse(content=challenge)
    return {"status": "unauthorized"}


@router.post("/approvals/whatsapp-webhook")
async def whatsapp_webhook_events(request: Request):
    """POST callback handler for WhatsApp message status and reply updates."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")

    entries = payload.get("entry", [])
    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for msg in messages:
                msg_type = msg.get("type")
                if msg_type == "interactive":
                    button_reply = msg.get("interactive", {}).get("button_reply", {})
                    reply_id = button_reply.get("id")
                    if reply_id and ":" in reply_id:
                        action, approval_id = reply_id.split(":", 1)
                        if action == "approve":
                            await approval_manager.approve(approval_id)
                        elif action == "reject":
                            await approval_manager.reject(approval_id)
                elif msg_type == "text":
                    body = msg.get("text", {}).get("body", "").lower().strip()
                    if " " in body:
                        parts = body.split(" ", 1)
                        if parts[0] in ("approve", "reject"):
                            action = parts[0]
                            approval_id = parts[1].strip()
                            if action == "approve":
                                await approval_manager.approve(approval_id)
                            elif action == "reject":
                                await approval_manager.reject(approval_id)

    return {"status": "ok"}

