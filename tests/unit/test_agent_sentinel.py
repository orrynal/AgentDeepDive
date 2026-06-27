import asyncio
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.core.agent.pool import AgentPool, agent_bus
from src.config import settings

class MockRedis:
    def __init__(self):
        self.data = {}
    async def get(self, key):
        return self.data.get(key)
    async def set(self, key, value):
        self.data[key] = value

class MockMessageBus:
    def __init__(self):
        self.published = []
        self.redis = None
    async def _get_redis(self):
        return self.redis
    async def publish(self, topic: str, sender_id: str, payload: dict):
        self.published.append((topic, sender_id, payload))

@pytest.fixture
def mock_redis():
    return MockRedis()

@pytest.fixture
def mock_bus(monkeypatch):
    bus = MockMessageBus()
    monkeypatch.setattr("src.core.agent.pool.agent_bus", bus)
    return bus

@pytest.mark.anyio
async def test_sentinel_lifecycle():
    pool = AgentPool()
    
    # Verify not running initially
    assert not hasattr(pool, "_sentinel_task") or pool._sentinel_task is None
    
    # Start sentinel
    pool.start_sentinel(check_interval_sec=0.1, expiry_threshold_sec=0.2)
    assert pool._sentinel_task is not None
    assert not pool._sentinel_task.done()
    
    # Stop sentinel
    await pool.stop_sentinel()
    assert pool._sentinel_task.done()

@pytest.mark.anyio
async def test_sentinel_zombie_detection(monkeypatch, mock_redis, mock_bus):
    pool = AgentPool()
    
    # Mock active agents
    async def mock_get_active_agents():
        return {
            "agent_alive": "task_1",
            "agent_zombie_expired": "task_2",
            "agent_zombie_missing": "task_3"
        }
    
    monkeypatch.setattr(pool, "get_active_agents", mock_get_active_agents)
    
    # Setup Redis heartbeats
    current_time = time.time()
    mock_redis.data["agentdeep:heartbeat:agent_alive"] = str(current_time)
    mock_redis.data["agentdeep:heartbeat:agent_zombie_expired"] = str(current_time - 100)  # Expired
    # agent_zombie_missing is missing from Redis data
    
    # Mock redis client getter
    mock_bus.redis = mock_redis
    
    # Mock active tasks
    mock_task_alive = MagicMock()
    mock_task_alive.done.return_value = False
    
    mock_task_expired = MagicMock()
    mock_task_expired.done.return_value = False
    
    mock_task_missing = MagicMock()
    mock_task_missing.done.return_value = True  # Already done, shouldn't cancel
    
    async def mock_get_active_tasks():
        return {
            "agent_alive": mock_task_alive,
            "agent_zombie_expired": mock_task_expired,
            "agent_zombie_missing": mock_task_missing
        }
    monkeypatch.setattr(pool, "get_active_tasks", mock_get_active_tasks)
    
    # Mock lock manager and release slot
    mock_lock_release = AsyncMock()
    monkeypatch.setattr("src.core.concurrency.lock_manager.lock_manager.release_all_for_agent", mock_lock_release)
    
    mock_release_slot = AsyncMock()
    monkeypatch.setattr(pool, "release_slot", mock_release_slot)
    
    # Run loop iteration once by starting the sentinel with a small interval, sleeping, and stopping it
    pool.start_sentinel(check_interval_sec=0.01, expiry_threshold_sec=5.0)
    await asyncio.sleep(0.05)
    await pool.stop_sentinel()
    
    # Assertions
    # 1. Alive task is not cancelled
    mock_task_alive.cancel.assert_not_called()
    
    # 2. Expired task is cancelled (zombie)
    assert mock_task_expired.cancel.call_count >= 1
    
    # 3. Missing task is not cancelled since it was done
    mock_task_missing.cancel.assert_not_called()
    
    # 4. Locks are released for both zombie agents
    mock_lock_release.assert_any_call("agent_zombie_expired")
    mock_lock_release.assert_any_call("agent_zombie_missing")
    
    # 5. Slots are released for both zombie agents
    mock_release_slot.assert_any_call("agent_zombie_expired")
    mock_release_slot.assert_any_call("agent_zombie_missing")
    
    # 6. Recovery events are published for both zombie agents
    recovery_events = [p for t, s, p in mock_bus.published if t == "recovery"]
    assert len(recovery_events) >= 2
    agent_ids = [e["agent_id"] for e in recovery_events]
    assert "agent_zombie_expired" in agent_ids
    assert "agent_zombie_missing" in agent_ids

@pytest.mark.anyio
async def test_sentinel_sandbox_gc(monkeypatch):
    pool = AgentPool()
    
    # Enable sandboxes in settings
    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)
    
    mock_prune = AsyncMock()
    monkeypatch.setattr("src.core.workspace.runtime.sandbox_runtime_manager.prune_zombie_resources", mock_prune)
    
    # Mock active agents to be empty to stop further loop processing
    async def mock_get_active_agents():
        return {}
    monkeypatch.setattr(pool, "get_active_agents", mock_get_active_agents)
    
    pool.start_sentinel(check_interval_sec=0.01, expiry_threshold_sec=5.0)
    await asyncio.sleep(0.05)
    await pool.stop_sentinel()
    
    # Verify prune_zombie_resources was called
    mock_prune.assert_called()
