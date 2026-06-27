import sys
from pathlib import Path

agent_deep_dive_path = str(Path(__file__).parent.parent.parent)
if agent_deep_dive_path not in sys.path:
    sys.path.insert(0, agent_deep_dive_path)

# Remove any paths containing ProsodyFlow from sys.path to prevent namespace collision
sys.path = [p for p in sys.path if "ProsodyFlow" not in p]

# Clear cached src and all its submodules only if it was loaded from the wrong path (e.g. ProsodyFlow)
if "src" in sys.modules:
    src_file = getattr(sys.modules["src"], "__file__", "") or ""
    if src_file:
        try:
            abs_src_path = str(Path(src_file).resolve())
        except Exception:
            abs_src_path = src_file
        if "ProsodyFlow" in abs_src_path:
            for key in list(sys.modules.keys()):
                if key == "src" or key.startswith("src."):
                    sys.modules.pop(key, None)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings
from src.api.schemas.skill import SkillPreviewRequest
from scripts.sandbox_cleanup_daemon import run_cleanup

client = TestClient(app)

from src.core.auth.security import get_current_user
from src.core.auth.models import UserModel
import uuid

def mock_get_current_user():
    return UserModel(
        id=uuid.uuid4(),
        username="test_preview_admin",
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        role="admin"
    )

@pytest.fixture(autouse=True)
def setup_dependencies():
    app.dependency_overrides[get_current_user] = mock_get_current_user
    yield
    # No need to clear, just ensure it's there before each test in this module


# ----------------------------------------------------
# 1. Daemon Cleanup Tests
# ----------------------------------------------------

@patch("scripts.sandbox_cleanup_daemon.redis.Redis")
@patch("scripts.sandbox_cleanup_daemon.subprocess.run")
@patch("scripts.sandbox_cleanup_daemon.settings")
def test_daemon_cleanup_docker_flow(mock_settings, mock_sub_run, mock_redis_class):
    """Test that Docker cleanup runs and calls delete on target container IDs."""
    mock_redis = MagicMock()
    mock_redis_class.from_url.return_value = mock_redis
    
    # Mock Redis active heartbeats
    mock_redis.keys.return_value = [b"agentdeep:heartbeat:active-agent-1"]
    mock_redis.get.return_value = b"active-task-1"
    
    # Mock docker ps returns:
    # - container-1 (agent active-agent-1, task active-task-1) -> keep
    # - container-2 (agent dead-agent, task dead-task) -> prune
    mock_sub_run.side_effect = [
        MagicMock(returncode=0),  # docker info
        MagicMock(
            returncode=0,
            stdout="container-1|active-agent-1|active-task-1|2026-06-11\ncontainer-2|dead-agent|dead-task|2026-06-11"
        ),  # docker ps
        MagicMock(returncode=0),  # docker rm -f container-2
    ]
    
    run_cleanup()
    
    # Assert container-2 is pruned
    mock_sub_run.assert_any_call(
        ["docker", "rm", "-f", "container-2"],
        capture_output=True,
        timeout=10
    )


# ----------------------------------------------------
# 2. Skill Preview Endpoint Tests
# ----------------------------------------------------

def test_skills_preview_yaml_valid():
    """Test previewing a valid YAML skill."""
    payload = {
        "content": """
skill_id: test-yaml-preview
name: YAML Preview Skill
version: 1.0.0
description: A test YAML skill
system_prompt: Hello world
"""
    }
    response = client.post("/api/v1/skills/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["parser_type"] == "yaml"
    assert data["metadata"]["skill_id"] == "test-yaml-preview"
    assert data["metadata"]["name"] == "YAML Preview Skill"
    assert data["metadata"]["system_prompt"] == "Hello world"
    assert len(data["warnings"]) == 0


def test_skills_preview_yaml_missing_fields():
    """Test previewing YAML skill with missing fields generates warnings."""
    payload = {
        "content": """
version: 2.0.0
description: Incomplete YAML
"""
    }
    response = client.post("/api/v1/skills/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["parser_type"] == "yaml"
    assert "Missing 'skill_id'." in data["warnings"]
    assert "Missing 'name'." in data["warnings"]
    assert "Missing 'system_prompt'." in data["warnings"]


def test_skills_preview_markdown_valid():
    """Test previewing a valid Markdown skill."""
    payload = {
        "content": """---
skill_id: test-md-preview
name: MD Preview Skill
version: 1.5.0
tags: [test, md]
trigger_patterns: [hello, test]
---
# Name: MD Preview Skill
# ID: test-md-preview

System prompt content here.
"""
    }
    response = client.post("/api/v1/skills/preview", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["parser_type"] == "markdown"
    assert data["metadata"]["skill_id"] == "test-md-preview"
    assert data["metadata"]["name"] == "MD Preview Skill"
    assert data["metadata"]["version"] == "1.5.0"
    assert "test" in data["metadata"]["tags"]
    assert "hello" in data["metadata"]["trigger_patterns"]
    assert "System prompt content here." in data["metadata"]["system_prompt"]


# ----------------------------------------------------
# 3. Webhook Connection Diagnostics Tests
# ----------------------------------------------------

@patch("src.api.routes.approvals.settings")
@patch("src.api.routes.approvals.approval_manager")
def test_approvals_diagnose_slack_success(mock_approval_manager, mock_settings):
    """Test successful Slack diagnostics."""
    mock_settings.slack_webhook_url = "https://hooks.slack.com/services/test"
    mock_approval_manager._send_slack_notification = AsyncMock()
    
    # Mock api key check
    headers = {"X-API-Key": "test-key"} if settings.api_key else {}
    with patch("src.api.routes.approvals.verify_api_key", return_value="valid-api-key"):
        response = client.post("/api/v1/approvals/diagnose/slack", headers=headers)
        
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_approval_manager._send_slack_notification.assert_called_once()


@patch("src.api.routes.approvals.settings")
def test_approvals_diagnose_slack_missing_config(mock_settings):
    """Test Slack diagnostics fails if config is missing."""
    mock_settings.slack_webhook_url = ""
    
    with patch("src.api.routes.approvals.verify_api_key", return_value="valid-api-key"):
        response = client.post("/api/v1/approvals/diagnose/slack")
        
    assert response.status_code == 400
    assert "Slack webhook url is not configured" in response.json()["detail"]


@patch("src.api.routes.approvals.settings")
def test_approvals_diagnose_unsupported_channel(mock_settings):
    """Test diagnostics fails for unsupported channels."""
    with patch("src.api.routes.approvals.verify_api_key", return_value="valid-api-key"):
        response = client.post("/api/v1/approvals/diagnose/invalidchannel")
        
    assert response.status_code == 400
    assert "Unsupported channel" in response.json()["detail"]


@pytest.mark.asyncio
async def test_health_diagnostics_endpoint(monkeypatch):
    """Test the comprehensive /health/diagnostics endpoint and verify all systems report."""
    from src.api.routes import health
    from unittest.mock import AsyncMock, MagicMock
    
    # 1. Mock DB connection success
    class MockConnection:
        async def execute(self, statement):
            return True
        async def close(self):
            pass
            
    class MockEngine:
        def __init__(self):
            class MockPool:
                def size(self):
                    return 10
            class MockEngineInner:
                pool = MockPool()
            self._engine = MockEngineInner()

        def connect(self):
            class MockConnectCtx:
                async def __aenter__(self):
                    return MockConnection()
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass
            return MockConnectCtx()
            
    mock_engine = MockEngine()
    monkeypatch.setattr("src.database.engine", mock_engine)

    # 2. Mock Redis connection success
    class MockRedis:
        async def ping(self):
            return True
    monkeypatch.setattr("src.core.redis_pool.get_async_redis_client", lambda: MockRedis())

    # 3. Call endpoint handler directly
    resp = await health.diagnostics_check()
    
    assert resp["health_level"] in ("GREEN", "YELLOW")
    assert len(resp["errors"]) == 0
    assert "system" in resp["diagnostics"]
    assert "database" in resp["diagnostics"]
    assert "redis" in resp["diagnostics"]
    assert "scheduler" in resp["diagnostics"]
    assert "agent_pool" in resp["diagnostics"]
    assert resp["diagnostics"]["database"]["status"] == "healthy"
    assert resp["diagnostics"]["redis"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_lifespan_shutdown_and_close_connections(monkeypatch):
    """Test that all database and redis connections can be closed successfully."""
    from src.database import close_db_connections, engine
    from src.core.redis_pool import close_redis_connections
    from src.core.scheduler.manager import scheduler_manager
    from unittest.mock import AsyncMock, MagicMock
    import src.core.redis_pool as rp
    
    # Save original references to avoid cross-test pollution
    orig_engine = engine._engine
    orig_async_redis = rp._async_redis_client
    orig_sync_redis = rp._sync_redis_client
    orig_scheduler = scheduler_manager.scheduler
    orig_initialized = scheduler_manager._initialized
    
    try:
        # Mock engine._engine
        class MockEngineInner:
            def __init__(self):
                self.dispose = AsyncMock()
        engine._engine = MockEngineInner()
        
        # Mock redis clients
        rp._async_redis_client = AsyncMock()
        rp._sync_redis_client = MagicMock()
        
        # Mock scheduler_manager
        scheduler_manager._initialized = True
        scheduler_manager.scheduler = MagicMock()
        
        # Call connection close helpers
        await close_db_connections()
        assert engine._engine is None
        
        await close_redis_connections()
        assert rp._async_redis_client is None
        assert rp._sync_redis_client is None
        
        await scheduler_manager.shutdown()
        assert scheduler_manager._initialized is False
    finally:
        # Restore original states
        engine._engine = orig_engine
        rp._async_redis_client = orig_async_redis
        rp._sync_redis_client = orig_sync_redis
        scheduler_manager.scheduler = orig_scheduler
        scheduler_manager._initialized = orig_initialized
