import pytest
import os
import json
import time
import urllib.request
from unittest.mock import AsyncMock, MagicMock
import redis.asyncio as aioredis
from src.core.governance.guardrails import GuardrailEngine
from src.core.governance.audit import AuditLogger
from src.core.governance.approval import ApprovalManager
from src.config import settings

@pytest.fixture
def clean_audit_log():
    log_file = "logs/test_audit_chaos.log"
    if os.path.exists(log_file):
        os.remove(log_file)
    yield log_file
    if os.path.exists(log_file):
        os.remove(log_file)


def test_opa_timeout_and_fallback_chaos(monkeypatch):
    """Chaos Test: Verify OPA service downtime/latency gracefully falls back to local AST engine."""
    monkeypatch.setattr(settings, "opa_enabled", True)
    monkeypatch.setattr(settings, "opa_url", "http://unreachable-opa-service:8181")

    # 1. Simulate OPA DNS resolution failure/Connection refused
    def mock_urlopen_connection_refused(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_connection_refused)
    
    engine = GuardrailEngine()
    engine._policy_uploaded = False

    # Under OPA outage, writing code outside workspace must STILL be blocked by local fallback
    assert engine.evaluate("file_write", {"target_path": "../etc/passwd"}) == "L4"
    # Local AST checks must block forbidden shell commands
    assert engine.evaluate("shell_exec", {"command": "sudo rm -rf /"}) == "L4"
    # Normal commands should default to L2
    assert engine.evaluate("shell_exec", {"command": "echo hello"}) == "L2"

    # 2. Simulate OPA High Latency/Timeout
    def mock_urlopen_timeout(req, timeout=None):
        raise TimeoutError("Connection timed out after 2.0 seconds")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_timeout)
    engine._policy_uploaded = False

    assert engine.evaluate("file_write", {"target_path": "../etc/passwd"}) == "L4"
    assert engine.evaluate("shell_exec", {"command": "echo hello"}) == "L2"

    # 3. Restore OPA Service and ensure it heals and starts querying OPA again
    queried_opa = False
    class MockResponse:
        def __init__(self):
            self.status = 200
        def read(self):
            return b'{"result": "L4"}'
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen_healthy(req, timeout=None):
        nonlocal queried_opa
        if "risk_level" in req.full_url:
            queried_opa = True
        return MockResponse()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_healthy)
    engine._policy_uploaded = True  # Avoid re-uploading policy to keep test simple

    # OPA returns L4, so it should evaluate to L4 now
    assert engine.evaluate("shell_exec", {"command": "echo hello"}) == "L4"
    assert queried_opa is True


@pytest.mark.anyio
async def test_postgres_outage_audit_fallback_chaos(monkeypatch):
    """Chaos Test: Verify PostgreSQL outage does not crash the audit system, falling back to structlog stdout."""
    
    # 1. Mock db session provider to throw connection/socket error on enter
    class MockFailingSession:
        async def __aenter__(self):
            raise ConnectionRefusedError("PostgreSQL connection lost - Socket Closed")
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
            
    def mock_session_failing():
        return MockFailingSession()
    
    monkeypatch.setattr("src.database.async_session", mock_session_failing)
    
    # Mock structlog info call to capture logs
    logged_events = []
    def mock_info(event, **kwargs):
        logged_events.append((event, kwargs))
        
    monkeypatch.setattr("src.core.governance.audit.logger.info", mock_info)
    
    logger = AuditLogger()
    
    # Trigger logging event during DB outage
    await logger.log_event(
        event_type="test_chaos_event",
        task_id="task-chaos-999",
        agent_id="agent-chaos-123",
        details={"attacker_payload": "rm -rf /"},
        tenant_id="00000000-0000-0000-0000-000000000000"
    )
    
    # Verify the event completed without crashing the program and logged to structlog
    assert len(logged_events) == 1
    event, kwargs = logged_events[0]
    assert event == "Security Audit Event"
    assert kwargs["event_type"] == "test_chaos_event"
    assert kwargs["task_id"] == "task-chaos-999"
    assert kwargs["attacker_payload"] == "rm -rf /"


@pytest.mark.anyio
async def test_redis_connection_loss_recovery(monkeypatch):
    """Chaos Test: Verify Redis connection drops during approvals and message bus recovers self-healing connection."""
    
    # Create mock Redis client that fails on first call, recovers on second call
    call_count = 0
    
    class MockRedisClient:
        def __init__(self):
            self.store = {}
            
        async def get(self, key):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aioredis.ConnectionError("Redis connection lost")
            return self.store.get(key)
            
        async def set(self, key, value):
            self.store[key] = value
            return True
            
        async def lpush(self, key, value):
            return 1
            
        async def lrem(self, key, count, value):
            return 1
            
    mock_redis = MockRedisClient()
    
    # Mock approval manager's Redis retrieval
    manager = ApprovalManager()
    monkeypatch.setattr(manager, "_get_redis", AsyncMock(return_value=mock_redis))
    
    # 1. The first call to get the approval status will raise Redis ConnectionError
    # We verify the error is bubbled up so the agent can catch it or retry
    await mock_redis.set("agentdeep:approvals:appr-chaos-1", json.dumps({"status": "pending"}))
    
    with pytest.raises(aioredis.ConnectionError):
        await manager.wait_for_approval("appr-chaos-1", timeout=1.0)
        
    # 2. The second call succeeds because the mock Redis client is now healthy
    # This demonstrates the connection is self-healing/resilient to temporary drops
    assert await manager.wait_for_approval("appr-chaos-1", timeout=1.0) is False  # Timeout returns False
