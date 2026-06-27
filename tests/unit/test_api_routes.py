import uuid
import pytest
import httpx
from fastapi import FastAPI
from src.api.main import app
from src.config import settings
from src.database import get_db
from src.core.scheduler.models import ScheduledTaskModel
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor

class MockDBSession:
    def __init__(self):
        self.added_objs = []
        self.deleted_objs = []
        self.committed = False
        self.refreshed_objs = []

    def add(self, obj):
        self.added_objs.append(obj)

    async def commit(self):
        self.committed = True

    async def refresh(self, obj):
        self.refreshed_objs.append(obj)
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()

    async def execute(self, query):
        class MockResult:
            def scalar_one_or_none(self):
                # Returns None so create_schedule doesn't fail unique check
                return None
            def scalars(self):
                class MockScalars:
                    def all(self):
                        return [
                            ScheduledTaskModel(
                                id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
                                name="cron-test",
                                task_description="desc",
                                cron_expression="0 * * * *",
                                is_active=True
                            )
                        ]
                return MockScalars()
        return MockResult()

    async def get(self, model, obj_id):
        return ScheduledTaskModel(
            id=obj_id,
            name="cron-test",
            task_description="desc",
            cron_expression="0 * * * *",
            is_active=True
        )

    async def delete(self, obj):
        self.deleted_objs.append(obj)

    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass

@pytest.fixture
def mock_db():
    return MockDBSession()

@pytest.fixture
async def client(mock_db, monkeypatch):
    # Setup test API key
    monkeypatch.setattr(settings, "api_key", "test_api_key")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "tg_secret")
    monkeypatch.setattr(settings, "telegram_chat_id", "12345")
    monkeypatch.setattr(settings, "telegram_bot_token", "bot_token")

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_approvals_api_routes(client, monkeypatch):
    # 1. Mock approvals managers
    pending_approvals = [{"id": "app-123", "risk_level": "high", "instruction": "rm file"}]
    async def mock_get_pending():
        return pending_approvals

    approved_ids = []
    rejected_ids = []

    async def mock_approve(app_id, arguments=None):
        approved_ids.append(app_id)

    async def mock_reject(app_id):
        rejected_ids.append(app_id)

    async def mock_get_redis():
        class MockRedis:
            async def get(self, key):
                return None
        return MockRedis()

    monkeypatch.setattr("src.api.routes.approvals.approval_manager.get_pending_approvals", mock_get_pending)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager.approve", mock_approve)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager.reject", mock_reject)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._get_redis", mock_get_redis)

    # A. Test unauthorized GET pending
    resp = await client.get("/api/v1/approvals/pending")
    assert resp.status_code == 401

    # B. Test authorized GET pending
    resp = await client.get("/api/v1/approvals/pending", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json() == pending_approvals

    # C. Test POST action approve
    resp = await client.post(
        "/api/v1/approvals/app-123/action",
        json={"action": "approve"},
        headers={"X-API-Key": "test_api_key"}
    )
    assert resp.status_code == 200
    assert "approved" in resp.json()["message"]
    assert "app-123" in approved_ids

    # D. Test POST action reject
    resp = await client.post(
        "/api/v1/approvals/app-123/action",
        json={"action": "reject"},
        headers={"X-API-Key": "test_api_key"}
    )
    assert resp.status_code == 200
    assert "rejected" in resp.json()["message"]
    assert "app-123" in rejected_ids

    # E. Test POST direct approved
    resp = await client.post(
        "/api/v1/approvals/app-456/approved",
        headers={"X-API-Key": "test_api_key"}
    )
    assert resp.status_code == 200
    assert "app-456" in approved_ids

    # F. Test POST direct reject
    resp = await client.post(
        "/api/v1/approvals/app-789/reject",
        headers={"X-API-Key": "test_api_key"}
    )
    assert resp.status_code == 200
    assert "app-789" in rejected_ids

    # G. Telegram Webhook validation
    # Unauthorized secret mismatch
    resp = await client.post(
        "/api/v1/approvals/telegram-webhook",
        json={"callback_query": {"data": "approve:tg-123"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"}
    )
    assert resp.status_code == 401

    # Unauthorized chat ID mismatch
    resp = await client.post(
        "/api/v1/approvals/telegram-webhook",
        json={
            "callback_query": {
                "message": {"chat": {"id": 99999}},
                "data": "approve:tg-123"
            }
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg_secret"}
    )
    assert resp.status_code == 403

    # Successful Callback Query
    # Mock httpx.AsyncClient.post directly to capture Telegram API requests
    telegram_calls = []
    original_post = httpx.AsyncClient.post
    async def mock_async_client_post(self, url, **kwargs):
        if str(url).startswith("https://api.telegram.org/"):
            telegram_calls.append((url, kwargs))
            return httpx.Response(200, json={"ok": True})
        return await original_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_async_client_post)

    resp = await client.post(
        "/api/v1/approvals/telegram-webhook",
        json={
            "callback_query": {
                "id": "query_id_123",
                "message": {
                    "chat": {"id": 12345},
                    "message_id": 999,
                    "text": "original request text"
                },
                "data": "approve:tg-123"
            }
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": "tg_secret"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "tg-123" in approved_ids
    assert len(telegram_calls) == 2  # editMessageText and answerCallbackQuery

    # H. Test GET direct HTML approvals
    from src.core.governance.approval import generate_approval_signature
    from src.config import settings
    token_approve = generate_approval_signature("get-123", "approve", settings.jwt_secret)
    resp_get = await client.get(f"/api/v1/approvals/get-123/approve_direct?token={token_approve}")
    assert resp_get.status_code == 200
    assert "text/html" in resp_get.headers.get("content-type", "")
    assert "Approval Granted" in resp_get.text
    assert "get-123" in approved_ids

    token_reject = generate_approval_signature("get-456", "reject", settings.jwt_secret)
    resp_get_rej = await client.get(f"/api/v1/approvals/get-456/reject_direct?token={token_reject}")
    assert resp_get_rej.status_code == 200
    assert "Approval Rejected" in resp_get_rej.text
    assert "get-456" in rejected_ids

    # I. Test POST Slack Webhook
    import json
    slack_payload = {
        "payload": json.dumps({
            "actions": [{"value": "approve:slack-123"}],
            "response_url": "http://slack-response"
        })
    }
    
    slack_responses = []
    original_post_slack = httpx.AsyncClient.post
    async def mock_slack_post(self, url, json=None, **kwargs):
        if str(url) == "http://slack-response":
            slack_responses.append(json)
            return httpx.Response(200, json={"ok": True})
        return await original_post_slack(self, url, json=json, **kwargs)
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_slack_post)
    
    resp_slack = await client.post(
        "/api/v1/approvals/slack-webhook",
        data=slack_payload
    )
    assert resp_slack.status_code == 200
    assert "slack-123" in approved_ids
    assert len(slack_responses) == 1
    assert "APPROVED" in slack_responses[0]["text"]

    # J. Test POST Feishu Webhook
    feishu_payload = {
        "action": {
            "value": {
                "action": "reject",
                "approval_id": "feishu-456"
            }
        }
    }
    resp_feishu = await client.post(
        "/api/v1/approvals/feishu-webhook",
        json=feishu_payload
    )
    assert resp_feishu.status_code == 200
    assert "feishu-456" in rejected_ids
    assert resp_feishu.json()["toast"] is not None

    # K. Test Webhook Diagnostics (diagnose_webhook_connection)
    tg_sent = []
    slack_sent = []
    feishu_sent = []
    ding_sent = []
    discord_sent = []
    wechat_sent = []
    qq_sent = []
    twitter_sent = []
    whatsapp_sent = []

    async def mock_tg_send(payload): tg_sent.append(payload)
    async def mock_slack_send(payload): slack_sent.append(payload)
    async def mock_feishu_send(payload): feishu_sent.append(payload)
    async def mock_ding_send(payload): ding_sent.append(payload)
    async def mock_discord_send(payload): discord_sent.append(payload)
    async def mock_wechat_send(payload): wechat_sent.append(payload)
    async def mock_qq_send(payload): qq_sent.append(payload)
    async def mock_twitter_send(payload): twitter_sent.append(payload)
    async def mock_whatsapp_send(payload): whatsapp_sent.append(payload)

    monkeypatch.setattr(settings, "telegram_bot_token", "bot")
    monkeypatch.setattr(settings, "telegram_chat_id", "chat")
    monkeypatch.setattr(settings, "slack_webhook_url", "http://slack")
    monkeypatch.setattr(settings, "feishu_webhook_url", "http://feishu")
    monkeypatch.setattr(settings, "dingtalk_webhook_url", "http://ding")
    monkeypatch.setattr(settings, "discord_bot_token", "bot")
    monkeypatch.setattr(settings, "discord_channel_id", "channel")
    monkeypatch.setattr(settings, "wechat_webhook_url", "http://wechat")
    monkeypatch.setattr(settings, "qq_bot_appid", "appid")
    monkeypatch.setattr(settings, "qq_bot_token", "token")
    monkeypatch.setattr(settings, "qq_channel_id", "channel")
    monkeypatch.setattr(settings, "twitter_bearer_token", "token")
    monkeypatch.setattr(settings, "twitter_admin_userid", "userid")
    monkeypatch.setattr(settings, "whatsapp_token", "token")
    monkeypatch.setattr(settings, "whatsapp_phone_id", "phoneid")
    monkeypatch.setattr(settings, "whatsapp_admin_phone", "adminphone")

    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_telegram_notification", mock_tg_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_slack_notification", mock_slack_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_feishu_notification", mock_feishu_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_dingtalk_notification", mock_ding_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_discord_notification", mock_discord_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_wechat_notification", mock_wechat_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_qq_notification", mock_qq_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_twitter_notification", mock_twitter_send)
    monkeypatch.setattr("src.api.routes.approvals.approval_manager._send_whatsapp_notification", mock_whatsapp_send)

    # 1. Test Telegram Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/telegram", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(tg_sent) == 1

    # 2. Test Slack Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/slack", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(slack_sent) == 1

    # 3. Test Feishu Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/feishu", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(feishu_sent) == 1

    # 4. Test DingTalk Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/dingtalk", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(ding_sent) == 1

    # 5. Test Discord Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/discord", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(discord_sent) == 1

    # 6. Test WeChat Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/wechat", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(wechat_sent) == 1

    # 7. Test QQ Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/qq", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(qq_sent) == 1

    # 8. Test Twitter/X Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/twitter", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(twitter_sent) == 1

    # 9. Test WhatsApp Diagnosis
    resp = await client.post("/api/v1/approvals/diagnose/whatsapp", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert len(whatsapp_sent) == 1

    # 10. Test Invalid Channel
    resp = await client.post("/api/v1/approvals/diagnose/invalidchannel", headers={"X-API-Key": "test_api_key"})
    assert resp.status_code == 400
    assert "Unsupported channel" in resp.json()["detail"]

@pytest.mark.anyio
async def test_schedules_api_routes(client, mock_db, monkeypatch):
    # Mock scheduler_manager
    registered_tasks = []
    removed_task_ids = []

    class MockSchedulerManager:
        def register_task(self, task):
            registered_tasks.append(task)
        def remove_task(self, task_id):
            removed_task_ids.append(task_id)

    monkeypatch.setattr("src.api.routes.schedules.scheduler_manager", MockSchedulerManager())

    headers = {"X-API-Key": "test_api_key"}

    # 1. POST /schedules
    payload = {
        "name": "daily-diagnostic",
        "task_description": "Run diagnostic optimization",
        "cron_expression": "0 0 * * *",
        "is_active": True
    }
    resp = await client.post("/api/v1/schedules", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "daily-diagnostic"
    assert len(mock_db.added_objs) == 1
    assert mock_db.committed is True
    assert len(registered_tasks) == 1

    # 2. GET /schedules
    resp = await client.get("/api/v1/schedules", headers=headers)
    assert resp.status_code == 200
    schedules = resp.json()
    assert len(schedules) == 1
    assert schedules[0]["name"] == "cron-test"

    # 3. PUT /schedules/{schedule_id}
    sched_id = uuid.uuid4()
    resp = await client.put(f"/api/v1/schedules/{sched_id}", json={"cron_expression": "*/5 * * * *"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["cron_expression"] == "*/5 * * * *"
    assert len(registered_tasks) == 2

    # 4. DELETE /schedules/{schedule_id}
    resp = await client.delete(f"/api/v1/schedules/{sched_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert len(mock_db.deleted_objs) == 1
    assert len(removed_task_ids) == 1

    # 5. POST /schedules/{schedule_id}/trigger
    from unittest.mock import patch
    with patch("src.core.scheduler.manager.execute_scheduled_task") as mock_exec:
        resp = await client.post(f"/api/v1/schedules/{sched_id}/trigger", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "triggered"



@pytest.mark.anyio
async def test_workspaces_api_routes(client, monkeypatch):
    # Mock workspace_manager
    class MockWorkspaceManager:
        def __init__(self):
            self.active_workspace = "/mock/workspace"
            self.workspaces = ["/mock/workspace"]
        def get_status(self):
            return {"active_workspace": self.active_workspace, "workspaces": self.workspaces}
        def set_active_workspace(self, path):
            self.active_workspace = path
            if path not in self.workspaces:
                self.workspaces.append(path)

    mock_wm = MockWorkspaceManager()
    monkeypatch.setattr("src.api.routes.workspaces.workspace_manager", mock_wm)

    # Mock OS and subprocess operations for workspace creation
    monkeypatch.setattr("os.makedirs", lambda path, exist_ok=False: None)
    monkeypatch.setattr("os.path.exists", lambda path: True)

    headers = {"X-API-Key": "test_api_key"}
    
    # 1. GET /workspaces
    resp = await client.get("/api/v1/workspaces", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active_workspace"] == "/mock/workspace"

    # 2. POST /workspaces/active
    resp = await client.post("/api/v1/workspaces/active", json={"path": "/new/workspace"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active_workspace"] == "/new/workspace"

    # 3. POST /workspaces (Create/register new)
    resp = await client.post("/api/v1/workspaces", json={"path": "/created/workspace"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active_workspace"] == "/created/workspace"

@pytest.mark.anyio
async def test_evolution_api_routes(client, monkeypatch):
    # Mock evaluator, diagnostics_engine, skill_optimizer, ab_manager
    async def mock_evaluate_trace(*args, **kwargs):
        return {"score": 0.4, "reasons": ["slow execution"]}

    def mock_diagnose(*args, **kwargs):
        return {"root_cause": "missing cache", "patch_suggestion": "add dict lookup"}

    async def mock_optimize_skill(*args, **kwargs):
        return True

    async def mock_generate_prompt(*args, **kwargs):
        return "optimized prompt"

    async def mock_fork_grey_skill(*args, **kwargs):
        return {"skill_id": "file-writer:flywheel:123", "version": "1.0.0-beta.flywheel"}

    monkeypatch.setattr("src.api.routes.evolution.evaluator.evaluate_trace", mock_evaluate_trace)
    monkeypatch.setattr("src.api.routes.evolution.diagnostics_engine.diagnose", mock_diagnose)
    monkeypatch.setattr("src.api.routes.evolution.skill_optimizer.optimize_skill", mock_optimize_skill)
    monkeypatch.setattr("src.api.routes.evolution.skill_optimizer.generate_optimized_prompt", mock_generate_prompt)
    monkeypatch.setattr("src.api.routes.evolution.ab_manager.fork_grey_skill", mock_fork_grey_skill)

    payload = {
        "task_id": "task-evolve-1",
        "task_description": "optimize file operations",
        "skill_id": "file-writer",
        "trace_steps": [{"step": 1, "action": "write"}],
        "agent_output": "file written successfully",
        "error_message": "Timeout occurred",
        "fork_ab_variant": True
    }

    headers = {"X-API-Key": "test_api_key"}

    # Test 1: fork_ab_variant = True (default/explicit)
    resp = await client.post("/api/v1/evolution/evaluate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 0.4
    assert data["needs_optimization"] is True
    assert data["optimized"] is True
    assert data["variant"]["variant_id"] == "file-writer:flywheel:123"
    assert data["diagnostics"]["root_cause"] == "missing cache"

    # Test 2: fork_ab_variant = False (direct patch on disk)
    payload["fork_ab_variant"] = False
    resp = await client.post("/api/v1/evolution/evaluate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["optimized"] is True
    assert data["variant"] is None

@pytest.mark.anyio
async def test_webhooks_n8n_and_background_flow(client, monkeypatch):
    headers = {"X-API-Key": "test_api_key"}
    monkeypatch.setattr("src.core.governance.ssrf.is_safe_url", lambda url: True)

    # Mock run_n8n_flow_in_background to do nothing so we don't spin up background thread during endpoint test
    background_calls = []
    async def mock_run_bg(task_description, callback_url):
        background_calls.append((task_description, callback_url))

    import src.api.routes.webhooks as webhooks_module
    original_run_bg = webhooks_module.run_n8n_flow_in_background
    monkeypatch.setattr(webhooks_module, "run_n8n_flow_in_background", mock_run_bg)

    # 1. Test POST /webhooks/n8n (Trigger API)
    payload = {
        "event": "github_issue",
        "task_description": "Analyze repository coverage",
        "callback_url": "http://n8n-server/callback"
    }
    resp = await client.post("/api/v1/webhooks/n8n", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert len(background_calls) == 1
    assert background_calls[0] == ("Analyze repository coverage", "http://n8n-server/callback")

    # 2. Test run_n8n_flow_in_background runner
    # Mock split_task to return a DAG
    node = DAGNode(node_id="node-1", skill_id="coverage", name="Run coverage", color=NodeColor.BLUE)
    mock_dag = DAGDefinition(dag_id="dag-n8n-123", name="n8n test DAG", nodes=[node], status="pending")

    async def mock_split_task(desc):
        return mock_dag

    class MockDAGEngine:
        def __init__(self, skill_svc):
            pass
        async def execute(self, dag):
            dag.status = "completed"
            dag.nodes[0].result = "Coverage: 88%"
            return dag

    monkeypatch.setattr("src.api.routes.webhooks.split_task", mock_split_task)
    monkeypatch.setattr("src.api.routes.webhooks.DAGEngine", MockDAGEngine)
    monkeypatch.setattr("src.api.routes.webhooks.async_session", lambda: MockDBSession())

    # Mock httpx.AsyncClient.post directly for callbacks
    callback_calls = []
    original_post = httpx.AsyncClient.post
    async def mock_async_client_post_callback(self, url, **kwargs):
        if str(url).startswith("http://n8n-server/"):
            callback_calls.append((url, kwargs))
            return httpx.Response(200, json={"status": "received"})
        return await original_post(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_async_client_post_callback)

    # Run background runner function
    await original_run_bg(
        task_description="Analyze coverage",
        callback_url="http://n8n-server/callback"
    )

    assert mock_dag.status == "completed"
    assert len(callback_calls) == 1
    assert callback_calls[0][0] == "http://n8n-server/callback"
    assert callback_calls[0][1]["json"]["dag_id"] == "dag-n8n-123"


@pytest.mark.anyio
async def test_saas_keys_api_routes(client, monkeypatch):
    headers = {"X-API-Key": "test_api_key"}

    # 1. Test GET /config/saas-keys initially
    resp = await client.get("/config/saas-keys", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["openai_api_key"] == ""
    assert data["openai_api_base"] == ""

    # 2. Test POST /config/saas-keys to update keys
    payload = {
        "openai_api_key": "sk-1234567890abcdefghijklmnopqrst",
        "openai_api_base": "https://custom-openai-endpoint/v1",
        "supabase_url": "https://project.supabase.co",
        "supabase_key": "sb-secret-key-value-here-long"
    }
    resp = await client.post("/config/saas-keys", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify setting values are set in Settings
    assert settings.openai_api_key == "sk-1234567890abcdefghijklmnopqrst"
    assert settings.openai_api_base == "https://custom-openai-endpoint/v1"
    assert settings.supabase_url == "https://project.supabase.co"
    assert settings.supabase_key == "sb-secret-key-value-here-long"

    # Verify that environment variables were updated
    import os
    assert os.environ.get("OPENAI_API_KEY") == "sk-1234567890abcdefghijklmnopqrst"
    assert os.environ.get("OPENAI_API_BASE") == "https://custom-openai-endpoint/v1"

    # 3. Test GET /config/saas-keys to check masking
    resp = await client.get("/config/saas-keys", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["openai_api_key"] == "sk-1...qrst"
    assert data["openai_api_base"] == "https://custom-openai-endpoint/v1"
    assert data["supabase_url"] == "https://project.supabase.co"
    assert data["supabase_key"] == "sb-s...long"


@pytest.mark.anyio
async def test_opa_api_routes(client, monkeypatch):
    headers = {"X-API-Key": "test_api_key"}

    # 1. Test GET /api/v1/opa/policy without auth
    resp = await client.get("/api/v1/opa/policy")
    assert resp.status_code == 401

    # 2. Test GET /api/v1/opa/policy with auth
    resp = await client.get("/api/v1/opa/policy", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "policy_content" in data
    assert "package guardrails" in data["policy_content"]

    # 3. Test PUT /api/v1/opa/policy to update policy
    original_policy = data["policy_content"]
    test_rego = original_policy + "\n# Test Comment Add"

    # Mock OPA push to prevent real HTTP call during tests
    from src.core.governance.guardrails import GuardrailEngine
    monkeypatch.setattr(GuardrailEngine, "_upload_policy_to_opa", lambda self: True)

    resp = await client.put("/api/v1/opa/policy", json={"policy_content": test_rego}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 4. Verify update was saved to disk
    resp = await client.get("/api/v1/opa/policy", headers=headers)
    assert resp.status_code == 200
    assert "# Test Comment Add" in resp.json()["policy_content"]

    # Restore original policy content to prevent dirtying workspace files
    await client.put("/api/v1/opa/policy", json={"policy_content": original_policy}, headers=headers)

    # 5. Test POST /api/v1/opa/test with mocked urllib responses
    class MockResponse:
        def __init__(self, status, body=b""):
            self.status = status
            self.body = body
        def read(self):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_calls = []
    def mock_urlopen(req, timeout=None):
        method = req.method if hasattr(req, "method") else "GET"
        url = req.full_url if hasattr(req, "full_url") else ""
        mock_calls.append((method, url))
        
        if method == "PUT":
            return MockResponse(200, b"")
        elif method == "POST":
            # return L4 decision mock
            return MockResponse(200, b'{"result": "L4"}')
        elif method == "DELETE":
            return MockResponse(200, b"")
        return MockResponse(200, b"")

    import urllib.request
    from src.config import settings
    monkeypatch.setattr(settings, "opa_enabled", True)
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    test_input = {
        "tool_name": "file_write",
        "arguments": {
            "target_path": "../etc/passwd"
        }
    }
    resp = await client.post(
        "/api/v1/opa/test",
        json={"policy_content": original_policy, "mock_input": test_input},
        headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["risk_level"] == "L4"
    assert len(mock_calls) >= 3  # PUT, POST, DELETE


@pytest.mark.anyio
async def test_cancel_paused_dag_api_route(client, monkeypatch):
    headers = {"X-API-Key": "test_api_key"}
    
    # 1. Mock load_dags_from_disk and save_dag_to_disk
    from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
    test_dag = DAGDefinition(
        dag_id="test-paused-dag-1",
        name="Test Paused DAG",
        status="paused",
        nodes=[DAGNode(node_id="N1", name="Node 1", skill_id="test", color=NodeColor.ORANGE)]
    )
    
    saved_dags = []
    def mock_load_dags_from_disk(tenant_id=None):
        return {"test-paused-dag-1": test_dag}
        
    def mock_save_dag_to_disk(dag, tenant_id=None):
        saved_dags.append(dag)
        
    # Mock message bus publish to prevent actual Redis publish
    published_events = []
    async def mock_publish(topic, sender_id, payload):
        published_events.append((topic, payload))
        
    monkeypatch.setattr("src.api.routes.dags.load_dags_from_disk", mock_load_dags_from_disk)
    monkeypatch.setattr("src.api.routes.dags.save_dag_to_disk", mock_save_dag_to_disk)
    monkeypatch.setattr("src.core.agent.pool.agent_bus.publish", mock_publish)
    
    # Post cancel request for paused DAG
    resp = await client.post("/api/v1/dags/test-paused-dag-1/cancel", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    
    # Verify DAG status was updated on disk
    assert len(saved_dags) == 1
    assert saved_dags[0].status == "failed"
    assert saved_dags[0].nodes[0].color == NodeColor.RED
    assert saved_dags[0].nodes[0].error == "Execution cancelled by user"
    
    # Verify WebSocket event was published
    assert len(published_events) == 1
    assert published_events[0][0] == "dag_updates"
    assert published_events[0][1]["dag_status"] == "failed"



