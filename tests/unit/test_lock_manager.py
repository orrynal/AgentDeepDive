import pytest
import fnmatch
from src.core.concurrency.lock_manager import FileLockManager, LockResult, LockInfo

class MockRedis:
    def __init__(self):
        self.store = {}
        self.published = []

    async def hgetall(self, key):
        return self.store.get(key, {})

    async def hget(self, key, field):
        return self.store.get(key, {}).get(field)

    async def hset(self, key, mapping):
        if key not in self.store:
            self.store[key] = {}
        self.store[key].update({k: str(v) for k, v in mapping.items()})
        return len(mapping)

    async def expire(self, key, ttl):
        return True

    async def delete(self, key):
        if key in self.store:
            del self.store[key]
            return 1
        return 0

    async def publish(self, channel, message):
        self.published.append((channel, message))
        return 1

    async def zadd(self, key, mapping):
        if key not in self.store:
            self.store[key] = {}
        for member, score in mapping.items():
            self.store[key][member] = float(score)
        return len(mapping)

    async def zrevrank(self, key, member):
        if key not in self.store or member not in self.store[key]:
            return None
        sorted_members = sorted(self.store[key].items(), key=lambda x: x[1], reverse=True)
        for idx, (m, _) in enumerate(sorted_members):
            if m == member:
                return idx
        return None

    async def zpopmax(self, key):
        if key not in self.store or not self.store[key]:
            return []
        sorted_members = sorted(self.store[key].items(), key=lambda x: x[1], reverse=True)
        max_member, max_score = sorted_members[0]
        del self.store[key][max_member]
        # Return format is list of tuples: [(member, score)]
        return [(max_member, max_score)]

    async def scan_iter(self, match):
        for key in list(self.store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key

    async def aclose(self):
        pass

@pytest.mark.anyio
async def test_file_lock_manager_acquire_and_release():
    manager = FileLockManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedis()
    manager._redis = mock_redis

    file_path = "src/core/agent/executor.py"

    # 1. Acquire direct lock
    res1 = await manager.acquire(file_path, "agent-1", "task-1", priority=50)
    assert res1.granted is True
    assert res1.holder_agent == "agent-1"
    
    lock_info = await manager.get_lock_info(file_path)
    assert lock_info is not None
    assert lock_info.holder_agent == "agent-1"
    assert lock_info.priority == 50

    # 2. Lock contention: enqueue lower priority request
    res2 = await manager.acquire(file_path, "agent-2", "task-2", priority=60)
    assert res2.granted is False
    assert res2.holder_agent == "agent-1"
    assert res2.queue_position == 1

    # 3. Lock preemption: high priority request (diff > 30, e.g. 95 - 50 = 45)
    res3 = await manager.acquire(file_path, "agent-3", "task-3", priority=95)
    assert res3.granted is True
    assert res3.holder_agent == "agent-3"
    assert res3.preempted_agent == "agent-1"
    assert ("agentdeep:preempt:agent-1", f"preempted:{file_path}") in mock_redis.published

    # 4. Release lock - should promote highest in queue (agent-2)
    next_holder = await manager.release(file_path, "agent-3")
    assert next_holder == "agent-2"
    assert ("agentdeep:lock_available:agent-2", f"granted:{file_path}") in mock_redis.published

@pytest.mark.anyio
async def test_file_lock_manager_release_all_for_agent():
    manager = FileLockManager(redis_url="redis://localhost:6379")
    mock_redis = MockRedis()
    manager._redis = mock_redis

    # Acquire multiple locks for agent-1
    await manager.acquire("file1.py", "agent-1", "task-1")
    await manager.acquire("file2.py", "agent-1", "task-2")
    await manager.acquire("file3.py", "agent-2", "task-3")

    # Release all for agent-1
    await manager.release_all_for_agent("agent-1")

    # Verify locks released
    assert await manager.get_lock_info("file1.py") is None
    assert await manager.get_lock_info("file2.py") is None
    assert await manager.get_lock_info("file3.py") is not None


@pytest.mark.anyio
async def test_file_lock_strategy_switching(monkeypatch):
    from src.config import settings
    from src.core.concurrency.lock_manager import LocalFileLockStrategy, RedisLockStrategy
    
    # 1. Test strategy switching based on system_mode
    monkeypatch.setattr(settings, "system_mode", "lightweight")
    manager_light = FileLockManager()
    strategy_light = manager_light.get_strategy()
    assert isinstance(strategy_light, LocalFileLockStrategy)
    
    monkeypatch.setattr(settings, "system_mode", "full")
    manager_full = FileLockManager()
    strategy_full = manager_full.get_strategy()
    assert isinstance(strategy_full, RedisLockStrategy)
    
    # 2. Test LocalFileLockStrategy functionality
    monkeypatch.setattr(settings, "system_mode", "lightweight")
    manager = FileLockManager()
    
    # Acquire a local lock
    res = await manager.acquire("test_file_local.py", "agent-local", "task-local")
    assert res.granted is True
    assert res.holder_agent == "agent-local"
    
    # Info
    info = await manager.get_lock_info("test_file_local.py")
    assert info is not None
    assert info.holder_agent == "agent-local"
    
    # Release
    next_holder = await manager.release("test_file_local.py", "agent-local")
    assert next_holder is None
    assert await manager.get_lock_info("test_file_local.py") is None
