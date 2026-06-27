import pytest
import base64
import hashlib
import hmac
import struct
import xml.etree.ElementTree as ET
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.config import settings

pytestmark = pytest.mark.integration
from src.api.routes.approvals import WeChatMsgCrypt
from tests.unit.test_api_routes import client, mock_db, MockDBSession

def encrypt_wechat_message(plain_text: str, encoding_aes_key: str, corp_id: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend

    key = base64.b64decode(encoding_aes_key + "=")
    iv = key[:16]
    
    # Format: [Random 16 bytes] + [4 bytes msg length] + [msg] + [corp_id]
    random_bytes = b"A" * 16
    msg_bytes = plain_text.encode("utf-8")
    msg_len = len(msg_bytes)
    corp_id_bytes = corp_id.encode("utf-8")
    
    payload = random_bytes + struct.pack(">I", msg_len) + msg_bytes + corp_id_bytes
    
    # PKCS7 padding
    pad_len = 32 - (len(payload) % 32)
    payload += bytes([pad_len] * pad_len)
    
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_bytes = encryptor.update(payload) + encryptor.finalize()
    return base64.b64encode(encrypted_bytes).decode("utf-8")

def test_wechat_msg_crypt_basic():
    token = "my_token"
    aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG" # 43 chars
    corp_id = "wx_corp_123"
    plain_xml = "<xml><EventKey>approve:test-appr</EventKey></xml>"
    
    # Encrypt
    encrypted_str = encrypt_wechat_message(plain_xml, aes_key, corp_id)
    
    # Decrypt
    crypt = WeChatMsgCrypt(token, aes_key, corp_id)
    decrypted = crypt.decrypt(encrypted_str)
    assert decrypted == plain_xml
    
    # Verify Signature
    timestamp = "12345678"
    nonce = "abcd"
    signature = crypt.verify_signature("invalid_sig", timestamp, nonce, encrypted_str)
    assert signature is False
    
    # Compute correct signature
    items = sorted([token, timestamp, nonce, encrypted_str])
    concat = "".join(items).encode("utf-8")
    correct_sig = hashlib.sha1(concat).hexdigest()
    assert crypt.verify_signature(correct_sig, timestamp, nonce, encrypted_str) is True

@pytest.mark.anyio
async def test_wechat_webhook_get(client, monkeypatch):
    token = "wx_token"
    aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    corp_id = "wx_corp_id"
    
    monkeypatch.setattr(settings, "wechat_token", token)
    monkeypatch.setattr(settings, "wechat_encoding_aes_key", aes_key)
    monkeypatch.setattr(settings, "wechat_corp_id", corp_id)
    
    plain_echostr = "my_echostr_data"
    encrypted_echostr = encrypt_wechat_message(plain_echostr, aes_key, corp_id)
    
    # Signature computation
    timestamp = "9876543"
    nonce = "xyz"
    items = sorted([token, timestamp, nonce, encrypted_echostr])
    signature = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    
    # Test valid request
    resp = await client.get(
        "/api/v1/approvals/wechat-webhook",
        params={
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": encrypted_echostr
        }
    )
    assert resp.status_code == 200
    assert resp.text == plain_echostr
    
    # Test invalid signature request
    resp_invalid = await client.get(
        "/api/v1/approvals/wechat-webhook",
        params={
            "msg_signature": "badsignature",
            "timestamp": timestamp,
            "nonce": nonce,
            "echostr": encrypted_echostr
        }
    )
    assert resp_invalid.status_code == 401
    assert "Invalid request signature" in resp_invalid.text

@pytest.mark.anyio
async def test_wechat_webhook_post(client, monkeypatch, mock_db):
    token = "wx_token"
    aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    corp_id = "wx_corp_id"
    
    monkeypatch.setattr(settings, "wechat_token", token)
    monkeypatch.setattr(settings, "wechat_encoding_aes_key", aes_key)
    monkeypatch.setattr(settings, "wechat_corp_id", corp_id)
    
    plain_xml = "<xml><EventKey>approve:wechat-appr-123</EventKey></xml>"
    encrypted_xml = encrypt_wechat_message(plain_xml, aes_key, corp_id)
    
    # Signature computation
    timestamp = "9876543"
    nonce = "xyz"
    items = sorted([token, timestamp, nonce, encrypted_xml])
    signature = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    
    # XML body structure standard for WeChat
    post_body = f"<xml><Encrypt><![CDATA[{encrypted_xml}]]></Encrypt></xml>"
    
    # Mock approval manager actions
    approved_ids = []
    async def mock_approve(appr_id):
        approved_ids.append(appr_id)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager.approve", mock_approve)
    
    # Test valid POST request
    resp = await client.post(
        "/api/v1/approvals/wechat-webhook",
        params={
            "msg_signature": signature,
            "timestamp": timestamp,
            "nonce": nonce
        },
        content=post_body,
        headers={"Content-Type": "application/xml"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert approved_ids == ["wechat-appr-123"]

@pytest.mark.anyio
async def test_twitter_webhook_crc(client, monkeypatch):
    # Setup settings
    monkeypatch.setattr(settings, "twitter_consumer_secret", "my_consumer_secret")
    
    crc_token = "some_crc_challenge_token"
    resp = await client.get("/api/v1/approvals/twitter-webhook", params={"crc_token": crc_token})
    assert resp.status_code == 200
    data = resp.json()
    assert "response_token" in data
    
    # Validate the signature
    expected_sig = hmac.new(b"my_consumer_secret", crc_token.encode("utf-8"), hashlib.sha256).digest()
    expected_token = f"sha256={base64.b64encode(expected_sig).decode('utf-8')}"
    assert data["response_token"] == expected_token

@pytest.mark.anyio
async def test_twitter_webhook_events(client, monkeypatch):
    monkeypatch.setattr(settings, "twitter_consumer_secret", "my_consumer_secret")
    
    payload = {
        "direct_message_events": [
            {
                "message_create": {
                    "message_data": {
                        "quick_reply_response": {
                            "metadata": "reject:twitter-appr-555"
                        }
                    }
                }
            }
        ]
    }
    
    import json
    body_str = json.dumps(payload)
    
    # Generate signature
    computed_sig = hmac.new(b"my_consumer_secret", body_str.encode("utf-8"), hashlib.sha256).digest()
    signature_header = f"sha256={base64.b64encode(computed_sig).decode('utf-8')}"
    
    # Mock approval manager actions
    rejected_ids = []
    async def mock_reject(appr_id):
        rejected_ids.append(appr_id)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager.reject", mock_reject)
    
    # Post with valid signature
    resp = await client.post(
        "/api/v1/approvals/twitter-webhook",
        content=body_str,
        headers={
            "x-twitter-webhooks-signature": signature_header,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 200
    assert rejected_ids == ["twitter-appr-555"]
    
    # Post with invalid signature
    resp_invalid = await client.post(
        "/api/v1/approvals/twitter-webhook",
        content=body_str,
        headers={
            "x-twitter-webhooks-signature": "sha256=invalidsig",
            "Content-Type": "application/json"
        }
    )
    assert resp_invalid.status_code == 401

@pytest.mark.anyio
async def test_whatsapp_webhook_verify(client, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_verify_token", "wa_secret_token")
    
    # Valid token
    resp = await client.get(
        "/api/v1/approvals/whatsapp-webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wa_secret_token",
            "hub.challenge": "12345678"
        }
    )
    assert resp.status_code == 200
    assert resp.text == "12345678"
    
    # Invalid token
    resp_invalid = await client.get(
        "/api/v1/approvals/whatsapp-webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "12345678"
        }
    )
    assert resp_invalid.status_code == 401


@pytest.mark.anyio
async def test_discord_webhook_ping_and_approval(client, monkeypatch):
    from nacl.signing import SigningKey
    
    # Generate an Ed25519 keypair
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    public_key_hex = verify_key.encode().hex()
    
    # Configure the test settings
    monkeypatch.setattr(settings, "discord_public_key", public_key_hex)
    
    # 1. Test PING (type = 1)
    ping_payload = {"type": 1}
    import json
    body_str = json.dumps(ping_payload)
    timestamp = "1700000000"
    
    # Generate signature
    message_to_sign = f"{timestamp}{body_str}".encode("utf-8")
    signature_bytes = signing_key.sign(message_to_sign).signature
    signature_hex = signature_bytes.hex()
    
    # Call endpoint
    resp = await client.post(
        "/api/v1/approvals/discord-webhook",
        content=body_str,
        headers={
            "X-Signature-Ed25519": signature_hex,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 200
    assert resp.json() == {"type": 1}
    
    # 2. Test Component interaction approval
    approval_payload = {
        "type": 3,
        "data": {
            "custom_id": "approve:discord-appr-999"
        }
    }
    body_str = json.dumps(approval_payload)
    message_to_sign = f"{timestamp}{body_str}".encode("utf-8")
    signature_hex = signing_key.sign(message_to_sign).signature.hex()
    
    approved_ids = []
    async def mock_approve(appr_id):
        approved_ids.append(appr_id)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager.approve", mock_approve)
    
    resp = await client.post(
        "/api/v1/approvals/discord-webhook",
        content=body_str,
        headers={
            "X-Signature-Ed25519": signature_hex,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json"
        }
    )
    assert resp.status_code == 200
    assert "Approved request discord-appr-999" in resp.json()["data"]["content"]
    assert approved_ids == ["discord-appr-999"]
    
    # 3. Test Invalid Signature
    resp_invalid = await client.post(
        "/api/v1/approvals/discord-webhook",
        content=body_str,
        headers={
            "X-Signature-Ed25519": "a" * 128,  # invalid signature
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json"
        }
    )
    assert resp_invalid.status_code == 401


@pytest.mark.anyio
async def test_send_wechat_notification_webhook(monkeypatch):
    import httpx
    from src.core.governance.approval import approval_manager
    
    # Configure settings
    monkeypatch.setattr(settings, "wechat_webhook_url", "http://mock-wechat-webhook")
    monkeypatch.setattr(settings, "wechat_corp_id", "")
    monkeypatch.setattr(settings, "wechat_corp_secret", "")
    
    # Capture requests
    captured_requests = []
    
    async def mock_post(self, url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {}
        return MockResponse()
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    payload = {
        "approval_id": "appr-1",
        "task_id": "task-1",
        "tool_name": "test_tool",
        "arguments": {"arg1": "val1"}
    }
    
    await approval_manager._send_wechat_notification(payload)
    
    assert len(captured_requests) == 1
    method, url, kwargs = captured_requests[0]
    assert method == "POST"
    assert url == "http://mock-wechat-webhook"
    assert kwargs["json"]["msgtype"] == "markdown"
    assert "appr-1" in kwargs["json"]["markdown"]["content"]


@pytest.mark.anyio
async def test_send_wechat_notification_corp_app(monkeypatch):
    import httpx
    from src.core.governance.approval import approval_manager
    
    # Configure settings
    monkeypatch.setattr(settings, "wechat_webhook_url", "")
    monkeypatch.setattr(settings, "wechat_corp_id", "my_corp_id")
    monkeypatch.setattr(settings, "wechat_corp_secret", "my_corp_secret")
    monkeypatch.setattr(settings, "wechat_agent_id", 1000001)
    
    # Capture requests
    captured_requests = []
    
    async def mock_get(self, url, **kwargs):
        captured_requests.append(("GET", url, kwargs))
        class MockResponse:
            status_code = 200
            def json(self):
                return {"access_token": "mock_token_123"}
        return MockResponse()
        
    async def mock_post(self, url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {}
        return MockResponse()
        
    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    payload = {
        "approval_id": "appr-1",
        "task_id": "task-1",
        "tool_name": "test_tool",
        "arguments": {"arg1": "val1"}
    }
    
    await approval_manager._send_wechat_notification(payload)
    
    assert len(captured_requests) == 2
    # 1. GET token
    method1, url1, kwargs1 = captured_requests[0]
    assert method1 == "GET"
    assert "corpid=my_corp_id" in url1
    assert "corpsecret=my_corp_secret" in url1
    
    # 2. POST message
    method2, url2, kwargs2 = captured_requests[1]
    assert method2 == "POST"
    assert "access_token=mock_token_123" in url2
    assert kwargs2["json"]["msgtype"] == "template_card"
    assert kwargs2["json"]["agentid"] == 1000001
    assert kwargs2["json"]["template_card"]["card_type"] == "button_interaction"


@pytest.mark.anyio
async def test_send_qq_notification(monkeypatch):
    import httpx
    from src.core.governance.approval import approval_manager
    
    # Configure settings
    monkeypatch.setattr(settings, "qq_bot_appid", "qq_app_123")
    monkeypatch.setattr(settings, "qq_bot_token", "qq_tok_456")
    monkeypatch.setattr(settings, "qq_channel_id", "qq_chan_789")
    
    # Capture requests
    captured_requests = []
    
    async def mock_post(self, url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {}
        return MockResponse()
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    payload = {
        "approval_id": "appr-1",
        "task_id": "task-1",
        "tool_name": "test_tool",
        "arguments": {"arg1": "val1"}
    }
    
    await approval_manager._send_qq_notification(payload)
    
    assert len(captured_requests) == 1
    method, url, kwargs = captured_requests[0]
    assert method == "POST"
    assert "channels/qq_chan_789/messages" in url
    assert kwargs["headers"]["Authorization"] == "Bot qq_app_123.qq_tok_456"
    assert "appr-1" in kwargs["json"]["markdown"]["content"]


@pytest.mark.anyio
async def test_send_twitter_notification(monkeypatch):
    import httpx
    from src.core.governance.approval import approval_manager
    
    monkeypatch.setattr(settings, "twitter_bearer_token", "tw_bear_123")
    monkeypatch.setattr(settings, "twitter_admin_userid", "tw_user_456")
    
    captured_requests = []
    
    async def mock_post(self, url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {}
        return MockResponse()
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    payload = {
        "approval_id": "appr-1",
        "task_id": "task-1",
        "tool_name": "test_tool",
        "arguments": {"arg1": "val1"}
    }
    
    await approval_manager._send_twitter_notification(payload)
    
    assert len(captured_requests) == 1
    method, url, kwargs = captured_requests[0]
    assert method == "POST"
    assert "dm_conversations/with/tw_user_456/messages" in url
    assert kwargs["headers"]["Authorization"] == "Bearer tw_bear_123"
    assert "appr-1" in kwargs["json"]["message"]["text"]


@pytest.mark.anyio
async def test_send_whatsapp_notification(monkeypatch):
    import httpx
    from src.core.governance.approval import approval_manager
    
    monkeypatch.setattr(settings, "whatsapp_token", "wa_tok_123")
    monkeypatch.setattr(settings, "whatsapp_phone_id", "wa_phone_456")
    monkeypatch.setattr(settings, "whatsapp_admin_phone", "wa_admin_789")
    
    captured_requests = []
    
    async def mock_post(self, url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        class MockResponse:
            status_code = 200
            text = "ok"
            def json(self):
                return {}
        return MockResponse()
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    payload = {
        "approval_id": "appr-1",
        "task_id": "task-1",
        "tool_name": "test_tool",
        "arguments": {"arg1": "val1"}
    }
    
    await approval_manager._send_whatsapp_notification(payload)
    
    assert len(captured_requests) == 2
    # 1. First request is interactive message
    method1, url1, kwargs1 = captured_requests[0]
    assert method1 == "POST"
    assert "wa_phone_456/messages" in url1
    assert kwargs1["headers"]["Authorization"] == "Bearer wa_tok_123"
    assert kwargs1["json"]["type"] == "interactive"
    
    # 2. Second request is fallback text link message
    method2, url2, kwargs2 = captured_requests[1]
    assert method2 == "POST"
    assert kwargs2["json"]["type"] == "text"
    assert "approve_direct" in kwargs2["json"]["text"]["body"]


@pytest.mark.anyio
async def test_idempotency_and_replay_prevention(monkeypatch, mock_db):
    import asyncio
    from src.core.governance.approval import approval_manager
    
    # 1. Mock agent_bus.publish to count publishes
    published_payloads = []
    async def mock_publish(*args, **kwargs):
        payload = kwargs.get("payload") or (args[2] if len(args) > 2 else None)
        published_payloads.append(payload)
    
    from src.core.agent.pool import agent_bus
    monkeypatch.setattr(agent_bus, "publish", mock_publish)
    
    # 2. Register approval request
    approval_id = await approval_manager.request_approval(
        task_id="task-123",
        agent_id="agent-456",
        tool_name="test_tool",
        arguments={"arg": "val"}
    )
    
    # Wait a tiny bit for the async task of first publish to execute
    await asyncio.sleep(0.05)
    assert len(published_payloads) == 1
    assert published_payloads[0]["status"] == "pending"
    
    # 3. Call approve first time
    await approval_manager.approve(approval_id)
    await asyncio.sleep(0.05)
    assert len(published_payloads) == 2
    assert published_payloads[1]["status"] == "approved"
    
    # Record first resolved time
    r = await approval_manager._get_redis()
    res = await r.get(f"agentdeep:approvals:{approval_id}")
    import json
    payload1 = json.loads(res)
    resolved_time_1 = payload1["resolved_at"]
    
    # 4. Call approve second time (redundant replay)
    await approval_manager.approve(approval_id)
    await asyncio.sleep(0.05)
    # Check that no new publish task is dispatched
    assert len(published_payloads) == 2
    
    # 5. Call reject on already approved request (replay/hijack)
    await approval_manager.reject(approval_id)
    await asyncio.sleep(0.05)
    # Check that it remains approved and no new publish is dispatched
    assert len(published_payloads) == 2
    res2 = await r.get(f"agentdeep:approvals:{approval_id}")
    payload2 = json.loads(res2)
    assert payload2["status"] == "approved"
    assert payload2["resolved_at"] == resolved_time_1


@pytest.mark.anyio
async def test_malformed_payload_webhooks(client, monkeypatch):
    # 1. Malformed WeChat POST XML
    resp_wechat = await client.post(
        "/api/v1/approvals/wechat-webhook",
        content="<xml><Encrypt>invalid-not-xml",
        headers={"Content-Type": "application/xml"}
    )
    assert resp_wechat.status_code == 400
    assert "Malformed callback payload" in resp_wechat.json()["detail"]
    
    # 2. Malformed Discord POST JSON
    resp_discord = await client.post(
        "/api/v1/approvals/discord-webhook",
        content="not-valid-json",
        headers={"Content-Type": "application/json"}
    )
    assert resp_discord.status_code == 400
    assert "Invalid JSON payload" in resp_discord.json()["detail"]
    
    # 3. Invalid Discord Hex signature
    monkeypatch.setattr(settings, "discord_public_key", "ab" * 32)
    resp_discord_sig = await client.post(
        "/api/v1/approvals/discord-webhook",
        content="{}",
        headers={
            "X-Signature-Ed25519": "not-hex-sig",
            "X-Signature-Timestamp": "1700000",
            "Content-Type": "application/json"
        }
    )
    assert resp_discord_sig.status_code == 400
    assert "Invalid signature hex format" in resp_discord_sig.json()["detail"]


@pytest.mark.anyio
async def test_message_bus_self_healing(monkeypatch):
    import asyncio
    from src.core.agent.pool import AgentMessageBus
    
    # Create a test message bus instance
    bus = AgentMessageBus(redis_url=settings.redis_url)
    
    # Track calls
    get_message_calls = 0
    psubscribe_calls = 0
    
    class MockPubSub:
        async def get_message(self, ignore_subscribe_messages=True, timeout=0.1):
            nonlocal get_message_calls
            get_message_calls += 1
            if get_message_calls == 2:
                # Trigger a connection error on the second call to trigger self-healing reconnect
                raise ConnectionError("Mock connection drop")
            await asyncio.sleep(0.01)
            return None
            
        async def psubscribe(self, **kwargs):
            nonlocal psubscribe_calls
            psubscribe_calls += 1
            
        async def aclose(self):
            pass
            
    # Mock _get_redis return value
    class MockRedis:
        def pubsub(self):
            return MockPubSub()
            
    async def mock_get_redis(*args, **kwargs):
        return MockRedis()
        
    monkeypatch.setattr(bus, "_get_redis", mock_get_redis)
    
    # Initialize listener callbacks and pubsub
    bus._listeners["test_topic"] = [lambda msg: None]
    bus._pubsub = MockPubSub()
    
    # Start the listen loop task
    listen_task = asyncio.create_task(bus._listen_loop())
    
    # Let it run to trigger the connection error and subsequent recovery
    await asyncio.sleep(1.5)
    
    # Cancel the loop to clean up
    listen_task.cancel()
    try:
        await listen_task
    except asyncio.CancelledError:
        pass
        
    # Verify that get_message was called, error was caught, and psubscribe was called to recover!
    assert get_message_calls >= 2
    assert psubscribe_calls >= 1
