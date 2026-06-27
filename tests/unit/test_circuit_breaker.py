import time
import uuid
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.core.governance.circuit_breaker import ResourceCircuitBreaker, CircuitBreakerState


@pytest.mark.anyio
async def test_circuit_breaker_resource_checking():
    cb = ResourceCircuitBreaker()
    cb._mock_cpu_ratio = 0.50
    cb._mock_mem_ratio = 0.50
    
    # Resources normal
    ok, reason = await cb.check_resources()
    assert ok is True
    assert "normal" in reason

    # CPU too high
    cb._mock_cpu_ratio = 0.95
    ok, reason = await cb.check_resources()
    assert ok is False
    assert "CPU" in reason

    # Memory too high
    cb._mock_cpu_ratio = 0.50
    cb._mock_mem_ratio = 0.99
    ok, reason = await cb.check_resources()
    assert ok is False
    assert "Memory" in reason


@pytest.mark.anyio
async def test_circuit_breaker_states_allowance(monkeypatch):
    cb = ResourceCircuitBreaker()
    cb._mock_cpu_ratio = 0.50
    cb._mock_mem_ratio = 0.50

    # Mock external services to prevent Redis/notification connections
    from src.core.agent.pool import agent_bus
    monkeypatch.setattr(agent_bus, "publish", AsyncMock())
    monkeypatch.setattr("src.core.governance.circuit_breaker.dispatch_workflow_notification", AsyncMock())
    
    # 1. Closed state allows task
    allowed, reason = await cb.allow_execution("Run tests")
    assert allowed is True
    assert cb.state == CircuitBreakerState.CLOSED

    # 2. Trip to open on failures
    await cb.record_failure("Test failure 1")
    await cb.record_failure("Test failure 2")
    await cb.record_failure("Test failure 3")
    assert cb.state == CircuitBreakerState.OPEN

    allowed, reason = await cb.allow_execution("Run tests")
    assert allowed is False
    assert "OPEN" in reason

    # 3. Force override bypasses OPEN state
    allowed, reason = await cb.allow_execution("Run tests", force=True)
    assert allowed is True

    # 4. Transition to HALF_OPEN after cooldown
    cb.cooldown_sec = 0.05
    import asyncio
    await asyncio.sleep(0.08)
    
    allowed, reason = await cb.allow_execution("Run tests")
    assert allowed is True
    assert cb.state == CircuitBreakerState.HALF_OPEN

    # 5. Success in HALF_OPEN transitions to CLOSED
    await cb.record_success()
    assert cb.state == CircuitBreakerState.CLOSED


@pytest.mark.anyio
async def test_circuit_breaker_half_open_failure(monkeypatch):
    cb = ResourceCircuitBreaker()
    cb._mock_cpu_ratio = 0.50
    cb._mock_mem_ratio = 0.50

    # Mock external services to prevent Redis/notification connections
    from src.core.agent.pool import agent_bus
    monkeypatch.setattr(agent_bus, "publish", AsyncMock())
    monkeypatch.setattr("src.core.governance.circuit_breaker.dispatch_workflow_notification", AsyncMock())
    
    # Trip the circuit
    cb.state = CircuitBreakerState.OPEN
    cb.tripped_at = time.time() - 10
    cb.cooldown_sec = 5.0
    
    # Cooldown elapsed -> HALF_OPEN
    allowed, reason = await cb.allow_execution("Test task")
    assert allowed is True
    assert cb.state == CircuitBreakerState.HALF_OPEN
    
    # Failure in HALF_OPEN immediately trips it back to OPEN
    await cb.record_failure("Trial failure")
    assert cb.state == CircuitBreakerState.OPEN


@pytest.mark.anyio
async def test_api_circuit_breaker_integration(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src.api.main import app
    from src.config import settings
    from src.database import get_db
    
    # Tripped circuit breaker
    from src.core.governance.circuit_breaker import resource_circuit_breaker
    monkeypatch.setattr(resource_circuit_breaker, "state", CircuitBreakerState.OPEN)
    monkeypatch.setattr(resource_circuit_breaker, "tripped_at", time.time())
    
    # Mock database session returning a task
    class MockDBSession:
        async def get(self, model, obj_id):
            return MagicMock(id=obj_id, tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000000"), task_description="Stress test")

            
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            pass

    async def override_get_db():
        yield MockDBSession()

    monkeypatch.setattr(settings, "api_key", "test_api_key")
    app.dependency_overrides[get_db] = override_get_db
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-API-Key": "test_api_key"}
        sched_id = uuid.uuid4()
        
        # 1. Normal trigger blocked (503)
        resp = await client.post(f"/api/v1/schedules/{sched_id}/trigger", headers=headers)
        assert resp.status_code == 503
        assert "Circuit Breaker" in resp.json()["detail"]
        
        # 2. Forced trigger allowed (200)
        with patch("src.core.scheduler.manager.execute_scheduled_task") as mock_exec:
            resp = await client.post(f"/api/v1/schedules/{sched_id}/trigger?force=true", headers=headers)
            assert resp.status_code == 200
            assert resp.json()["status"] == "triggered"
            
    app.dependency_overrides.clear()
