import pytest
import asyncio
import time
from src.core.concurrency.lock_manager import FileLockManager, LockResult
from src.core.redis_pool import get_async_redis_client

@pytest.fixture
async def redis_cleaner():
    r = get_async_redis_client()
    # Clean up any test locks before and after tests
    async for key in r.scan_iter("agentdeep:lock:concurrency_*"):
        await r.delete(key)
    async for key in r.scan_iter("agentdeep:queue:concurrency_*"):
        await r.delete(key)
    yield
    async for key in r.scan_iter("agentdeep:lock:concurrency_*"):
        await r.delete(key)
    async for key in r.scan_iter("agentdeep:queue:concurrency_*"):
        await r.delete(key)


@pytest.mark.anyio
async def test_high_concurrency_lock_acquisition(redis_cleaner):
    """Stress/Concurrency Test: Verify exclusive ownership and queue ordering under 30 concurrent requests of equal priority."""
    manager = FileLockManager()
    file_path = "concurrency_test_file.txt"
    
    # 30 tasks with equal priority to prevent preemption and test exclusive acquisition + queueing
    num_tasks = 30
    
    async def acquire_lock(task_id: int):
        priority = 50
        agent_id = f"agent-{task_id}"
        result = await manager.acquire(
            file_path=file_path,
            agent_id=agent_id,
            task_id=f"task-{task_id}",
            priority=priority
        )
        return task_id, priority, result

    # Launch all acquisitions concurrently using asyncio.gather
    results = await asyncio.gather(*(acquire_lock(i) for i in range(num_tasks)))
    
    # Verify: Exactly one agent got the lock granted
    granted_results = [res for res in results if res[2].granted]
    assert len(granted_results) == 1, f"Expected exactly 1 lock to be granted, got {len(granted_results)}"
    
    holder_task_id, holder_priority, holder_result = granted_results[0]
    
    # All other agents must be queued
    queued_results = [res for res in results if not res[2].granted]
    assert len(queued_results) == num_tasks - 1
    
    # Verify the queued items exist in Redis
    r = await manager._get_redis()
    queue_key = f"agentdeep:queue:{file_path}"
    queue_items = await r.zrevrange(queue_key, 0, -1, withscores=True)
    assert len(queue_items) == num_tasks - 1


@pytest.mark.anyio
async def test_high_concurrency_preemption_race(redis_cleaner):
    """Stress/Concurrency Test: Multiple high priority agents race to preempt a low priority holder."""
    manager = FileLockManager()
    file_path = "concurrency_preempt_file.txt"
    
    # 1. Low priority agent acquires lock
    res1 = await manager.acquire(file_path, "agent-low", "task-low", priority=10)
    assert res1.granted is True
    
    # Subscribe to preemption channel for the low priority agent to listen to preemption
    r = await manager._get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe("agentdeep:preempt:agent-low")
    
    # 2. Spawn 15 high-priority agents concurrently to trigger preemption.
    # All have priority >= 50, diff to 10 is >= 40 (which is > PREEMPT_THRESHOLD = 30).
    # Since they run concurrently, one will preempt, others will queue up.
    num_preempters = 15
    
    async def run_preempter(preempter_id: int):
        priority = 50 + preempter_id  # 50, 51, ..., 64
        return await manager.acquire(
            file_path=file_path,
            agent_id=f"agent-high-{preempter_id}",
            task_id=f"task-high-{preempter_id}",
            priority=priority
        )
        
    preempt_results = await asyncio.gather(*(run_preempter(i) for i in range(num_preempters)))
    
    # Verify: At least one preempted the current lock holder, and others got queued
    granted_preempts = [res for res in preempt_results if res.granted]
    assert len(granted_preempts) >= 1
    
    # Check that agent-low received preemption message
    msg = None
    try:
        # Loop to read from pubsub message queue resiliently
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=True)
            if msg and msg["type"] == "message":
                break
            await asyncio.sleep(0.05)
    finally:
        await pubsub.unsubscribe("agentdeep:preempt:agent-low")
        await pubsub.aclose()
        
    assert msg is not None
    data = msg["data"]
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    assert data == f"preempted:{file_path}"


@pytest.mark.anyio
async def test_concurrent_release_and_promotion(redis_cleaner):
    """Stress/Concurrency Test: Releasing the lock promotes the highest priority queue waiter correctly."""
    manager = FileLockManager()
    file_path = "concurrency_release_file.txt"
    
    # 1. Acquire direct lock
    await manager.acquire(file_path, "agent-holder", "task-holder", priority=50)
    
    # 2. Queue 5 waiters with different priorities (all <= 80 to avoid preempting agent-holder at 50)
    waiters = [
        ("agent-w1", 10),
        ("agent-w2", 80), # Highest priority waiter
        ("agent-w3", 40),
        ("agent-w4", 70),
        ("agent-w5", 20),
    ]
    for agent_id, priority in waiters:
        res = await manager.acquire(file_path, agent_id, f"task-{agent_id}", priority=priority)
        assert res.granted is False
        
    # Subscribe to lock_available channel for the expected highest priority winner (agent-w2)
    r = await manager._get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe("agentdeep:lock_available:agent-w2")
    
    # 3. Release the lock and verify agent-w2 is promoted
    next_holder = await manager.release(file_path, "agent-holder")
    assert next_holder == "agent-w2"
    
    # Check lock info
    info = await manager.get_lock_info(file_path)
    assert info is not None
    assert info.holder_agent == "agent-w2"
    assert info.priority == 80
    
    # Verify pubsub notification
    msg = None
    try:
        for _ in range(10):
            msg = await pubsub.get_message(ignore_subscribe_messages=True)
            if msg and msg["type"] == "message":
                break
            await asyncio.sleep(0.05)
    finally:
        await pubsub.unsubscribe("agentdeep:lock_available:agent-w2")
        await pubsub.aclose()
        
    assert msg is not None
    data = msg["data"]
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    assert data == f"granted:{file_path}"
