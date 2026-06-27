import asyncio
import json
import pytest
from src.core.governance.guardrails import GuardrailEngine
from src.core.governance.approval import ApprovalManager
from src.config import Settings, settings

def test_guardrail_engine(monkeypatch):
    engine = GuardrailEngine()
    monkeypatch.setattr(Settings, "resolved_workspace_path", property(lambda self: "/workspace"))

    # 1. Directory list and file read (L0)
    assert engine.evaluate("directory_list", {}) == "L0"
    assert engine.evaluate("file_read", {}) == "L0"

    # 2. File write (L4 path traversal / L3 sensitive / L1 normal)
    assert engine.evaluate("file_write", {"target_path": "../etc/passwd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "/etc/passwd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "/workspace/sandbox/../../etc/passwd\x00/dummy"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "..%2fetc%2fpasswd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "\\u002e\\u002e\\u002fetc\\u002fpasswd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "\\x2e\\x2e\\x2fetc\\x2fpasswd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "/workspace/.env"}) == "L3"
    assert engine.evaluate("file_write", {"target_path": "/workspace/src/config.py"}) == "L3"
    assert engine.evaluate("file_write", {"target_path": "/workspace/main.py"}) == "L1"

    # 3. Shell exec (L4 forbidden / L3 risky / L2 normal)
    assert engine.evaluate("shell_exec", {"command": "rm -rf /"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "sudo apt-get update"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "rm file.txt"}) == "L3"
    assert engine.evaluate("shell_exec", {"command": "mv file.txt dest/"}) == "L3"
    assert engine.evaluate("shell_exec", {"command": "curl http://google.com"}) == "L3"
    assert engine.evaluate("shell_exec", {"command": "ls -la"}) == "L2"

    # AST and Subcommand Bypass Checks
    assert engine.evaluate("shell_exec", {"command": "sh -c 'rm -rf /'"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "python -c \"import os; os.system('rm -rf /')\""}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "python3 -c \"import shutil; shutil.rmtree('/')\""}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "python -c \"__import__('shutil').rmtree('/')\""}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "python -c \"open('/etc/passwd', 'w').write('hack')\""}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "ls; rm -rf /"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "find / -delete"}) == "L4"

    # 4. Default fallback (L1)
    assert engine.evaluate("other_tool", {}) == "L1"

    # 5. Whitelist Mode test
    monkeypatch.setattr(settings, "guardrails_whitelist_enabled", True)
    monkeypatch.setattr(settings, "guardrails_whitelist_commands", [
        r"^ls(?:\s+.*)?$",
        r"^pwd$",
        r"^git\s+status$",
    ])
    try:
        # Allowed commands
        assert engine.evaluate("shell_exec", {"command": "ls"}) == "L2"
        assert engine.evaluate("shell_exec", {"command": "ls -la"}) == "L2"
        assert engine.evaluate("shell_exec", {"command": "pwd"}) == "L2"
        assert engine.evaluate("shell_exec", {"command": "git status"}) == "L2"

        # Blocked commands (not in whitelist)
        assert engine.evaluate("shell_exec", {"command": "whoami"}) == "L4"
        assert engine.evaluate("shell_exec", {"command": "git commit -m 'test'"}) == "L4"
        assert engine.evaluate("shell_exec", {"command": "rm file.txt"}) == "L4"
    finally:
        monkeypatch.setattr(settings, "guardrails_whitelist_enabled", False)

class MockRedis:
    def __init__(self):
        self.store = {}
        self.published = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, val):
        self.store[key] = val
        return True

    async def lpush(self, key, val):
        if key not in self.store:
            self.store[key] = []
        self.store[key].insert(0, val)
        return len(self.store[key])

    async def lrem(self, key, count, val):
        if key in self.store and isinstance(self.store[key], list):
            self.store[key] = [x for x in self.store[key] if x != val]
            return 1
        return 0

    async def lrange(self, key, start, stop):
        lst = self.store.get(key, [])
        if stop == -1:
            return lst[start:]
        return lst[start:stop+1]

@pytest.mark.anyio
async def test_approval_manager_flow(monkeypatch):
    manager = ApprovalManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedis()
    manager._redis = mock_redis

    # Disable Telegram notifications for general flow
    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_chat_id", None)

    # 1. Request Approval
    approval_id = await manager.request_approval(
        task_id="task-123",
        agent_id="agent-abc",
        tool_name="shell_exec",
        arguments={"command": "rm file.txt"},
        priority=60
    )
    assert approval_id.startswith("appr-")

    # 2. Get Pending Approvals
    pending = await manager.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0]["approval_id"] == approval_id
    assert pending[0]["status"] == "pending"

    # 3. Approve
    await manager.approve(approval_id)
    resolved_pending = await manager.get_pending_approvals()
    assert len(resolved_pending) == 0

    # 4. Check status change in Redis
    data_str = await mock_redis.get(f"agentdeep:approvals:{approval_id}")
    payload = json.loads(data_str)
    assert payload["status"] == "approved"

@pytest.mark.anyio
async def test_approval_manager_wait_and_timeout(monkeypatch):
    manager = ApprovalManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedis()
    manager._redis = mock_redis

    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_chat_id", None)

    # Mock asyncio.sleep to respond instantly without recursion
    original_sleep = asyncio.sleep
    monkeypatch.setattr("src.core.governance.approval.asyncio.sleep", lambda delay: original_sleep(0.01))

    # 1. Test Timeout scenario
    approval_id_to = await manager.request_approval(
        task_id="task-to", agent_id="agent-abc", tool_name="shell_exec", arguments={}, priority=50
    )
    # Wait with short timeout
    granted = await manager.wait_for_approval(approval_id_to, timeout=0.1)
    assert granted is False
    # Auto-rejected on timeout
    pending = await manager.get_pending_approvals()
    assert len(pending) == 0

    # 2. Test Success scenario (approved asynchronously)
    approval_id_ok = await manager.request_approval(
        task_id="task-ok", agent_id="agent-abc", tool_name="shell_exec", arguments={}, priority=50
    )

    async def approve_later():
        await asyncio.sleep(0.02)
        await manager.approve(approval_id_ok)

    asyncio.create_task(approve_later())
    granted_ok = await manager.wait_for_approval(approval_id_ok, timeout=2.0)
    assert granted_ok is True


@pytest.mark.anyio
async def test_generate_tool_diff(tmp_path):
    from src.core.governance.approval import generate_tool_diff
    
    # Create a dummy file
    f_path = tmp_path / "hello.txt"
    f_path.write_text("Hello line 1\nHello line 2\nHello line 3\n")
    
    # 1. Test replace_file_content
    args = {
        "TargetFile": str(f_path),
        "TargetContent": "Hello line 2\n",
        "ReplacementContent": "World line 2\n"
    }
    diff = generate_tool_diff("replace_file_content", args)
    assert diff is not None
    assert "-Hello line 2" in diff
    assert "+World line 2" in diff

    # 2. Test write_to_file (completely new file)
    new_f = tmp_path / "new.txt"
    args_new = {
        "TargetFile": str(new_f),
        "CodeContent": "New file line 1\n"
    }
    diff_new = generate_tool_diff("write_to_file", args_new)
    assert diff_new is not None
    assert "+New file line 1" in diff_new


@pytest.mark.anyio
async def test_multi_channel_notifications(monkeypatch):
    import httpx
    manager = ApprovalManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedis()
    manager._redis = mock_redis

    monkeypatch.setattr(settings, "telegram_bot_token", None)
    monkeypatch.setattr(settings, "telegram_chat_id", None)
    monkeypatch.setattr(settings, "slack_webhook_url", "http://slack-mock")
    monkeypatch.setattr(settings, "feishu_webhook_url", "http://feishu-mock")
    monkeypatch.setattr(settings, "dingtalk_webhook_url", "http://dingtalk-mock")

    posted_urls = []
    async def mock_post(self, url, json=None, **kwargs):
        posted_urls.append((str(url), json))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    # Trigger request_approval
    approval_id = await manager.request_approval(
        task_id="task-multi",
        agent_id="agent-abc",
        tool_name="replace_file_content",
        arguments={"TargetFile": "/some/file.txt", "TargetContent": "old", "ReplacementContent": "new"},
        priority=50
    )

    # Let the background task tasks run
    await asyncio.sleep(0.05)

    # Verify that Slack, Feishu, and DingTalk notifications were triggered
    urls = [url for url, _ in posted_urls]
    assert "http://slack-mock" in urls
    assert "http://feishu-mock" in urls
    assert "http://dingtalk-mock" in urls


@pytest.mark.anyio
@pytest.mark.integration
async def test_audit_logger_db():
    import uuid
    from src.core.governance.audit import AuditLogger
    from src.database import async_session
    from src.core.governance.models import AuditLogModel
    from sqlalchemy import select

    logger_instance = AuditLogger()
    task_id = f"test-task-audit-{uuid.uuid4()}"
    agent_id = "test-agent-audit-abc"
    event_type = "test_event"
    details = {"foo": "bar", "test_run": True}

    # Log the event (writes to local file and DB)
    await logger_instance.log_event(
        event_type=event_type,
        task_id=task_id,
        agent_id=agent_id,
        details=details,
    )

    # Query the DB to check if it was persisted
    async with async_session() as session:
        result = await session.execute(
            select(AuditLogModel).where(AuditLogModel.task_id == task_id)
        )
        logs = result.scalars().all()
        
        assert len(logs) == 1
        db_log = logs[0]
        assert db_log.event_type == event_type
        assert db_log.agent_id == agent_id
        assert db_log.details == details

        # Clean up the test record
        await session.delete(db_log)
        await session.commit()


def test_guardrail_engine_with_opa(monkeypatch):
    from src.config import Settings, settings
    
    # 1. Enable OPA in settings
    monkeypatch.setattr(settings, "opa_enabled", True)
    monkeypatch.setattr(settings, "opa_url", "http://localhost:8181")
    monkeypatch.setattr(Settings, "resolved_workspace_path", property(lambda self: "/workspace"))
    
    # 2. Mock urllib.request.urlopen
    uploaded_policies = {}
    evaluated_inputs = []
    
    class MockResponse:
        def __init__(self, data, status=200):
            self.data = data
            self.status = status
            
        def read(self):
            return self.data
            
        def __enter__(self):
            return self
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(req, timeout=None):
        url = req.full_url
        method = req.get_method()
        
        if method == "PUT" and "/v1/policies/guardrails" in url:
            policy_data = req.data.decode("utf-8")
            uploaded_policies["guardrails"] = policy_data
            return MockResponse(b"{}", 200)
            
        elif method == "POST" and "/v1/data/guardrails/risk_level" in url:
            input_payload = json.loads(req.data.decode("utf-8"))
            evaluated_inputs.append(input_payload)
            
            tool_name = input_payload["input"]["tool_name"]
            command = input_payload["input"]["arguments"].get("command", "")
            target_path = input_payload["input"]["arguments"].get("target_path", "")
            
            decision = "L1"
            if tool_name in ["directory_list", "file_read"]:
                decision = "L0"
            elif tool_name == "file_write":
                if ".." in target_path or target_path.startswith("~") or (target_path.startswith("/") and not target_path.startswith("/workspace")):
                    decision = "L4"
                elif target_path.endswith(".env"):
                    decision = "L3"
            elif tool_name == "shell_exec":
                if "rm -rf /" in command:
                    decision = "L4"
                elif "rm " in command or "curl " in command:
                    decision = "L3"
                else:
                    decision = "L2"
                    
            response_payload = {"result": decision}
            return MockResponse(json.dumps(response_payload).encode("utf-8"), 200)
            
        return MockResponse(b"{}", 404)
        
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    engine = GuardrailEngine()
    
    # Verify policy upload and evaluation works
    assert engine.evaluate("directory_list", {}) == "L0"
    assert "guardrails" in uploaded_policies
    assert "package guardrails" in uploaded_policies["guardrails"]
    
    # File write checks
    assert engine.evaluate("file_write", {"target_path": "../etc/passwd"}) == "L4"
    assert engine.evaluate("file_write", {"target_path": "/workspace/.env"}) == "L3"
    assert engine.evaluate("file_write", {"target_path": "main.py"}) == "L1"
    
    # Shell exec checks
    assert engine.evaluate("shell_exec", {"command": "rm -rf /"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "rm file.txt"}) == "L3"
    assert engine.evaluate("shell_exec", {"command": "ls"}) == "L2"

    # 4. Verify OPA failure fallback to local implementation
    uploaded_policies.clear()
    
    def mock_urlopen_failing(req, timeout=None):
        raise Exception("Connection refused")
        
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_failing)
    
    engine._policy_uploaded = False
    
    assert engine.evaluate("directory_list", {}) == "L0"
    assert engine.evaluate("shell_exec", {"command": "rm -rf /"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "rm file.txt"}) == "L3"
    assert engine.evaluate("shell_exec", {"command": "ls"}) == "L2"


@pytest.mark.anyio
async def test_workflow_notification_dispatcher(monkeypatch):
    import httpx
    from src.core.governance.notifications import dispatch_workflow_notification

    # Set up mock configuration values
    monkeypatch.setattr(settings, "slack_webhook_url", "http://slack-alert")
    monkeypatch.setattr(settings, "telegram_bot_token", "tg-token")
    monkeypatch.setattr(settings, "telegram_chat_id", "tg-chat")
    monkeypatch.setattr(settings, "feishu_webhook_url", "http://feishu-alert")
    monkeypatch.setattr(settings, "dingtalk_webhook_url", "http://dingtalk-alert")
    monkeypatch.setattr(settings, "discord_bot_token", "discord-token")
    monkeypatch.setattr(settings, "discord_channel_id", "discord-channel")

    posted_urls = {}

    async def mock_post(self, url, json=None, **kwargs):
        posted_urls[str(url)] = json
        return httpx.Response(200, json={"status": "success"})

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    # 1. Test dispatch_workflow_notification for suspension event
    await dispatch_workflow_notification(
        event_type="workflow.suspended",
        dag_id="dag-111",
        node_id="node-222",
        error="Self-healing exceeded max attempts limit",
        tenant_id="tenant-333",
        timestamp="2026-06-22T09:47:00Z"
    )

    # Verify Slack payload
    assert "http://slack-alert" in posted_urls
    slack_payload = posted_urls["http://slack-alert"]
    assert "attachments" in slack_payload
    assert slack_payload["attachments"][0]["color"] == "#FF8C00"
    assert "dag-111" in slack_payload["attachments"][0]["blocks"][1]["text"]["text"]
    assert "node-222" in slack_payload["attachments"][0]["blocks"][1]["text"]["text"]

    # Verify Telegram payload
    tg_url = "https://api.telegram.org/bottg-token/sendMessage"
    assert tg_url in posted_urls
    tg_payload = posted_urls[tg_url]
    assert tg_payload["chat_id"] == "tg-chat"
    assert "dag-111" in tg_payload["text"]
    assert "node-222" in tg_payload["text"]

    # Verify Feishu payload
    assert "http://feishu-alert" in posted_urls
    feishu_payload = posted_urls["http://feishu-alert"]
    assert feishu_payload["card"]["header"]["template"] == "orange"
    assert "dag-111" in feishu_payload["card"]["elements"][0]["content"]

    # Verify DingTalk payload
    assert "http://dingtalk-alert" in posted_urls
    ding_payload = posted_urls["http://dingtalk-alert"]
    assert "dag-111" in ding_payload["markdown"]["text"]

    # Verify Discord payload
    discord_url = "https://discord.com/api/v10/channels/discord-channel/messages"
    assert discord_url in posted_urls
    discord_payload = posted_urls[discord_url]
    assert discord_payload["embeds"][0]["color"] == 16747520
    assert "dag-111" in discord_payload["embeds"][0]["description"]

    # 2. Test dispatch_workflow_notification for failure event
    posted_urls.clear()
    await dispatch_workflow_notification(
        event_type="workflow.failed",
        dag_id="dag-444",
        error="Severe configuration error",
        tenant_id="tenant-555",
        timestamp="2026-06-22T09:48:00Z"
    )

    # Verify Slack color is red
    slack_payload_fail = posted_urls["http://slack-alert"]
    assert slack_payload_fail["attachments"][0]["color"] == "#FF0000"

    # Verify Feishu template is red
    feishu_payload_fail = posted_urls["http://feishu-alert"]
    assert feishu_payload_fail["card"]["header"]["template"] == "red"

    # Verify Discord color is red
    discord_payload_fail = posted_urls[discord_url]
    assert discord_payload_fail["embeds"][0]["color"] == 16711680



